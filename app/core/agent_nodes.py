"""Agent 节点：把"需要语义理解"的决策点各自封装成一次结构化 LLM 调用。

六个决策点（对应 Agentic RAG 的四个经典改进点 + 两个交付增强）：
    1. plan        —— 先规划再检索（Query Planning，替代"上来就检索"）
    2. rewrite     —— 检索不足时改写检索式（Query Rewriting，多轮召回）
    3. grade       —— 检索后自评相关性（Retrieval Grading，第一道防幻觉闸门）
    4. verify      —— 生成后自检忠实度（Self-Verification / 防幻觉，第二道闸门）
    5. compress    —— 证据压缩（Context Compression，省 token 去噪声）
    6. memo        —— 决策备忘录（Decision Memo，企业级交付物）

工程上最重要的三条约定（面试高频）：
    A. **结构化输出必须能兜底**：JSON 解析失败/校验失败就退化成保守默认值
       （比如"判定为不足"），绝不让异常穿透到用户。LLM 是概率组件，
       控制流必须比它更确定。
    B. **每个节点都记账**：node 名 + 模型 + token + 成本写进 UsageStats，
       这样"Agent 比朴素 RAG 贵多少、贵在哪一步"是可以直接查出来的。
    C. **上下文要编号且与返回的 sources 严格对齐**：判定、校验、生成三处
       看到的 [n] 必须是同一份列表，否则引用会错位 —— 这是引用准确率的根。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Settings
from .agent_state import GradeOutcome, Plan, VerifyOutcome, DecisionMemo
from .prompts import (
    AGENT_ANSWER_SYSTEM,
    AGENT_COMPRESS_SYSTEM,
    AGENT_GRADE_SYSTEM,
    AGENT_MEMO_SYSTEM,
    AGENT_PLAN_SYSTEM,
    AGENT_REFORMULATE_SYSTEM,
    AGENT_VERIFY_SYSTEM,
    format_evidence_block,
)
from .token_stats import estimate_tokens, extract_usage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_loose(text: str) -> dict | None:
    """从模型输出里抠出第一个 JSON 对象。

    为什么需要：即使要求"只输出 JSON"，模型仍可能加 ```json 围栏、
    加一句"好的，这是结果："，或在末尾多写解释。工程上必须容错解析。
    """
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            # 模型偶尔直接返回数组（如压缩节点给 ["...","..."]）→ 包一层
            return {"items": obj}
    except Exception:  # noqa: BLE001
        pass
    m = _JSON_BLOCK_RE.search(s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _extract_keywords(text: str, limit: int = 6) -> list[str]:
    """关键词抽取（确定性兜底）：中文按 jieba 切词，去停用词后取较长的词。"""
    try:
        import jieba

        words = [w.strip() for w in jieba.lcut(text) if len(w.strip()) >= 2]
    except Exception:  # noqa: BLE001
        words = [w for w in re.split(r"[\s,，。？?！!、；;：:]+", text) if len(w) >= 2]
    stop = {"什么", "怎么", "如何", "为什么", "哪些", "哪个", "这个", "那个", "我们", "你们",
            "可以", "需要", "应该", "以及", "但是", "因为", "所以", "如果", "就是", "一个"}
    out: list[str] = []
    for w in sorted(set(words), key=len, reverse=True):
        if w in stop or w in out:
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


class AgentNodes:
    """所有 Agent 决策节点的实现（无状态，可被多请求共享）。"""

    def __init__(self, settings: Settings, router, stats) -> None:
        self.settings = settings
        self.router = router
        self.stats = stats

    # ------------------------------------------------------------ 底层：结构化调用
    async def _json_call(
        self,
        *,
        node: str,
        system: str,
        user: str,
        schema: Type[T],
        fallback: T,
        state=None,
        max_tokens: int | None = None,
    ) -> tuple[T, dict]:
        """调用 LLM 并要求 JSON 输出 → 校验成 Pydantic 模型。

        返回 (模型实例, 元信息)。任何一步失败都返回 fallback ——
        控制流永远拿得到"一个合法的决策结果"，这是 Agent 不崩的前提。
        """
        llm = self.router.get("agent")
        if llm is None:
            return fallback, {"ok": False, "reason": "no_llm"}
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        model_name = self.router.model_name("agent")
        last_err = ""
        for attempt in range(2):
            try:
                resp = await llm.ainvoke(messages)
            except Exception as e:  # noqa: BLE001 —— 网络/限流等，重试一次
                last_err = f"{type(e).__name__}: {e}"
                logger.warning("Agent 节点 %s 调用失败（第 %d 次）：%s", node, attempt + 1, last_err)
                continue
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            usage = extract_usage(resp)
            estimated = usage is None
            if usage is None:
                usage = (estimate_tokens(system + user), estimate_tokens(text))
            rec = self.stats.record(
                task=f"agent:{node}", model=model_name,
                prompt_tokens=usage[0], completion_tokens=usage[1],
                price_input_per_m=self.settings.llm_price_input_per_m,
                price_output_per_m=self.settings.llm_price_output_per_m,
                session_id=getattr(state, "session_id", "") or "", estimated=estimated,
            )
            if state is not None:
                state.llm_calls.append({
                    "step": node, "model": model_name,
                    "prompt_tokens": rec.prompt_tokens, "completion_tokens": rec.completion_tokens,
                    "cost": rec.cost, "estimated": rec.estimated,
                })
            obj = parse_json_loose(text)
            if obj is not None:
                try:
                    return schema.model_validate(obj), {"ok": True, "raw": obj}
                except ValidationError as e:
                    last_err = f"字段校验失败：{e.errors()[:2]}"
            else:
                last_err = "输出不是合法 JSON"
            logger.warning("Agent 节点 %s 输出不可用（第 %d 次）：%s", node, attempt + 1, last_err)
        return fallback, {"ok": False, "reason": last_err}

    async def _text_call(self, *, node: str, system: str, user: str, state=None) -> str:
        """普通文本调用（生成答案用）。同样记账。"""
        llm = self.router.get("agent")
        if llm is None:
            return ""
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage = extract_usage(resp)
        estimated = usage is None
        if usage is None:
            usage = (estimate_tokens(system + user), estimate_tokens(text))
        rec = self.stats.record(
            task=f"agent:{node}", model=self.router.model_name("agent"),
            prompt_tokens=usage[0], completion_tokens=usage[1],
            price_input_per_m=self.settings.llm_price_input_per_m,
            price_output_per_m=self.settings.llm_price_output_per_m,
            session_id=getattr(state, "session_id", "") or "", estimated=estimated,
        )
        if state is not None:
            state.llm_calls.append({
                "step": node, "model": self.router.model_name("agent"),
                "prompt_tokens": rec.prompt_tokens, "completion_tokens": rec.completion_tokens,
                "cost": rec.cost, "estimated": rec.estimated,
            })
        return text

    # ------------------------------------------------------------ 1) 规划
    async def plan(self, state, question: str, tool_names: list[str]) -> Plan:
        user = (
            f"可用工具：{', '.join(tool_names)}\n"
            f"对话历史：\n{state.history_text or '（无）'}\n\n"
            f"用户问题：{question}"
        )
        plan, meta = await self._json_call(
            node="plan", system=AGENT_PLAN_SYSTEM, user=user,
            schema=Plan, fallback=Plan(), state=state,
        )
        if not plan.search_queries:
            plan.search_queries = [question]
        if not plan.steps:
            plan.steps = ["检索知识库", "判定资料是否足够", "基于资料生成带引用的回答"]
        return plan

    # ------------------------------------------------------------ 2) 检索式改写
    async def rewrite_queries(self, state, question: str, missing: str, n: int = 2) -> dict:
        used = state.queries
        user = (
            f"用户问题：{question}\n"
            f"上一轮已用检索式：{used or '（无）'}\n"
            f"判定缺失的信息：{missing or '（未说明）'}\n"
            f"上一轮命中的文档：{sorted({e.doc_title for e in state.evidence}) or '（无）'}\n"
            f"请给出 {n} 条新的检索式。"
        )
        obj, meta = await self._json_call(
            node="rewrite", system=AGENT_REFORMULATE_SYSTEM, user=user,
            schema=_RewriteOut, fallback=_RewriteOut(), state=state,
        )
        queries = [q.strip() for q in (obj.queries or []) if q and q.strip()]
        queries = [q for q in queries if q not in used][:n]
        if not queries:  # 确定性兜底：关键词 + 缺什么补什么
            kws = _extract_keywords(question, 4)
            if kws:
                queries.append(" ".join(kws))
            if missing:
                queries.append(f"{question} {missing}".strip()[:60])
            queries = [q for q in queries if q and q not in used][:n] or [question]
        return {"queries": queries, "ok": meta.get("ok", False)}

    # ------------------------------------------------------------ 3) 相关性判定
    async def grade(self, state, question: str, evidence: list) -> GradeOutcome:
        if not evidence:
            return GradeOutcome(sufficient=False, confidence=0.0,
                                missing="没有任何检索结果", relevant_ids=[], reason="证据池为空")
        block = format_evidence_block(evidence)
        user = f"用户问题：{question}\n\n【检索到的资料】\n{block}"
        verdict, meta = await self._json_call(
            node="grade", system=AGENT_GRADE_SYSTEM, user=user,
            schema=GradeOutcome,
            fallback=GradeOutcome(sufficient=False, confidence=0.0,
                                  missing="判定器不可用，按保守策略处理", reason="fallback"),
            state=state,
        )
        return verdict

    # ------------------------------------------------------------ 4) 忠实度自检
    async def verify(self, state, question: str, answer: str, evidence: list) -> VerifyOutcome:
        if not answer.strip():
            return VerifyOutcome(grounded=False, score=0.0, reason="回答为空")
        block = format_evidence_block(evidence)
        user = f"用户问题：{question}\n\n【检索到的资料】\n{block}\n\n【系统回答】\n{answer}"
        verdict, meta = await self._json_call(
            node="verify", system=AGENT_VERIFY_SYSTEM, user=user,
            schema=VerifyOutcome,
            fallback=VerifyOutcome(grounded=True, score=0.5, reason="校验器不可用，放行"),
            state=state,
        )
        return verdict

    # ------------------------------------------------------------ 5) 证据压缩
    async def compress_chunks(self, question: str, items: list, max_chars: int) -> list[str]:
        """批量压缩：一次调用压多条，比逐条调用省 token 也省时间。"""
        block = "\n\n".join(f"[{i}] {it.body}" for i, it in enumerate(items, start=1))
        user = (
            f"用户问题：{question}\n每条压缩后不超过 {max_chars} 字。\n\n"
            f"【待压缩资料】\n{block}"
        )
        obj, meta = await self._json_call(
            node="compress", system=AGENT_COMPRESS_SYSTEM, user=user,
            schema=_CompressOut, fallback=_CompressOut(), state=None,
        )
        got = [str(x) for x in (obj.items or [])]
        out: list[str] = []
        for i, it in enumerate(items):
            text = got[i].strip() if i < len(got) and got[i] else ""
            out.append(text or it.text[:max_chars])
        return out

    # ------------------------------------------------------------ 6) 决策备忘录
    async def build_memo(self, state, topic: str, constraints: str, evidence: list) -> DecisionMemo:
        block = format_evidence_block(evidence)
        user = (
            f"决策主题：{topic}\n约束条件：{constraints or '（未提供）'}\n\n"
            f"【参考资料】\n{block}"
        )
        memo, meta = await self._json_call(
            node="memo", system=AGENT_MEMO_SYSTEM, user=user,
            schema=DecisionMemo, fallback=DecisionMemo(
                conclusion="资料库信息不足以支撑该决策",
                rationale=[], risks=[], actions=[], citations=[],
            ),
            state=state,
        )
        return memo

    # ------------------------------------------------------------ 7) 生成答案
    async def answer(
        self, state, question: str, evidence: list, *, style: str = "", extra: str = ""
    ) -> str:
        """基于证据生成回答。**证据为空时不调用 LLM**，直接给确定性拒答。

        为什么这一步很关键：让模型在"没有任何资料"时空转，是幻觉率最高的场景。
        直接在控制流上短路，比写十句"不要编造"的提示词都有效。
        """
        if not evidence:
            return self._refusal_text(state)
        block = format_evidence_block(evidence)
        system = AGENT_ANSWER_SYSTEM
        if style:
            system += f"\n\n[本次回答的结构要求]\n{style}"
        parts = [f"问题：{question}", f"【参考资料】\n{block}"]
        if extra:
            parts.append(extra)
        text = await self._text_call(
            node="answer", system=system, user="\n\n".join(parts), state=state
        )
        return (text or "").strip()

    async def answer_stream(
        self, state, question: str, evidence: list, *, style: str = "", extra: str = ""
    ):
        """流式生成回答：逐 token 产出文本片段。

        流式的价值不只是"体验好"：它让用户更早看到内容，也让"生成很慢"不再像卡死。
        但注意 —— 流式下**校验必须在生成之后**，也就是说校验发现的幻觉无法再撤回，
        只能用"答案末尾追加提示 + 返回 verdict"的方式暴露出来（诚实优于假装）。
        """
        if not evidence:
            text = self._refusal_text(state)
            yield text
            return
        llm = self.router.get("agent")
        if llm is None:
            return
        from langchain_core.messages import HumanMessage, SystemMessage

        block = format_evidence_block(evidence)
        system = AGENT_ANSWER_SYSTEM
        if style:
            system += f"\n\n[本次回答的结构要求]\n{style}"
        parts = [f"问题：{question}", f"【参考资料】\n{block}"]
        if extra:
            parts.append(extra)
        messages = [SystemMessage(content=system), HumanMessage(content="\n\n".join(parts))]
        model_name = self.router.model_name("agent")
        usage: tuple[int, int] | None = None
        pieces: list[str] = []
        async for chunk in llm.astream(messages):
            u = extract_usage(chunk)
            if u:
                usage = u
            piece = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if piece:
                pieces.append(piece)
                yield piece
        text = "".join(pieces)
        estimated = usage is None
        if usage is None:
            usage = (estimate_tokens(system + "\n".join(parts)), estimate_tokens(text))
        rec = self.stats.record(
            task="agent:answer", model=model_name,
            prompt_tokens=usage[0], completion_tokens=usage[1],
            price_input_per_m=self.settings.llm_price_input_per_m,
            price_output_per_m=self.settings.llm_price_output_per_m,
            session_id=getattr(state, "session_id", "") or "", estimated=estimated,
        )
        state.llm_calls.append({
            "step": "answer", "model": model_name,
            "prompt_tokens": rec.prompt_tokens, "completion_tokens": rec.completion_tokens,
            "cost": rec.cost, "estimated": rec.estimated,
        })

    @staticmethod
    def _refusal_text(state) -> str:
        """确定性拒答模板：讲清楚"没找到 + 检索了什么 + 为什么"，而不是干巴巴说不知道。"""
        tried = "；".join(state.queries[:3]) if state.queries else "（未执行检索）"
        return (
            "资料库中没有找到相关信息。\n\n"
            f"- 已检索的内容：{tried}\n"
            "- 结论：现有知识库无法支撑该问题的回答，为避免编造，这里不做推测。\n"
            "- 建议：补充相关文档后重新上传入库，或换一种更具体的问法再试。"
        )


class _CompressOut(BaseModel):
    """压缩节点的输出容器（单独定义，避免污染领域模型）。"""

    items: list[str] = []


class _RewriteOut(BaseModel):
    """改写节点的输出容器：只关心新检索式。"""

    queries: list[str] = []
