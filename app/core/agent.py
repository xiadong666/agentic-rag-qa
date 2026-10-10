"""Agentic RAG 编排层：把「规划 → 检索 → 判定 → 反思/改写 → 生成 → 校验」写成显式状态机。

为什么用显式状态机，而不是把决策全丢给 Function Calling 的 ReAct 循环（核心设计取舍）：

    维度            朴素 RAG          裸 ReAct（全自主）        本项目：受控 Agentic RAG
    控制流          写死一条链        每步由 LLM 决定            框架固定 + 关键决策点交给 LLM
    可观测性        只有最终答案      有工具调用日志             每步都是结构化事件，可推前端
    稳定性          高（但不会纠错）  易发散/易死循环/易超时     有轮数上限、有兜底、有短路
    可评测性        能测              难（路径不固定）           路径可枚举，指标可复现
    成本            低                不可预测                   可控（记账到每一步）

    结论：企业级 Agent 的关键不是"让模型想干嘛就干嘛"，而是
    **把不确定的部分收敛到少数几个明确的决策点上**（这里是 plan/grade/verify），
    其余流程用确定性代码兜住 —— 这就是"受控 Agent"。

本文件是 engine 的方法宿主类：它需要访问 store / retriever / reranker / nodes / stats，
所以由引擎在构造时注入（组合优于继承，避免 engine.py 变成上帝类）。
"""
from __future__ import annotations

import json
import time
from typing import AsyncIterator

from ..schemas import SourceRef
from .agent_nodes import AgentNodes
from .agent_state import AgentState, AgentStep, DecisionMemo
from .agent_tools import build_registry
from .memory import ChatTurn
from .prompts import format_evidence_block

# 需要"压缩后再生成"的问题特征：长问题 + 方案/建议类问题
_COMPRESS_HINTS = ("建议", "怎么办", "排查", "选型", "方案", "优化", "如何改进", "决策", "思路")

# stats 分支的口径守卫（两组关键词都要命中才放行）。
# 为什么需要它（真实踩坑①）：规划器会把"你们系统每天的 QPS 峰值是多少"判成 stats，
# 于是 kb_stats 输出"4 篇文档 / 72 个分块"——答非所问，评测里表现为"库外问题被误答"。
# 为什么需要它（真实踩坑②）：只写"知识库/库里"这类名词也不够 ——
# "库里那位负责部署的同事叫什么"同样含"库里"，但它问的是**具体实体**，必须走检索。
# 所以判据必须是"在问清单/数量/规模"这个**意图**，而不是出现某个名词。
_KB_TOKENS = ("知识库", "文档库", "库里", "库中", "收录", "kb", "corpus", "向量库")
_KB_INVENTORY_HINTS = (
    "有哪些", "有什么", "哪些文档", "多少", "几篇", "几个", "几条", "多大规模", "有多大",
    "规模", "概览", "概况", "清单", "列表", "统计", "收录", "包含哪些", "有些什么",
    "list", "how many", "count", "overview",
)
# 问"具体实体"的问题必须走检索（即使含"库里"与"多少"）：人员、联系方式、具体内容等
_KB_ENTITY_ASK_HINTS = ("谁", "叫什么", "姓名", "名字", "工号", "电话", "邮箱", "联系方式",
                        "负责", "作者", "联系人", "什么时候", "哪天", "哪一年")
# 故障/性能/容量类问题必须走检索（资料里可能有降级方案）
_KB_TROUBLE_HINTS = ("挂了", "故障", "宕机", "不可用", "qps", "并发", "峰值", "延迟", "耗时",
                     "压力", "容量", "负载", "超时", "限流", "崩", "失败")


def _to_snippet(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _looks_like_kb_self_question(question: str) -> bool:
    """判断问题是不是在问"知识库自身的清单/数量/规模"（这类问题才允许走确定性统计工具）。

    判据必须落在**意图**上，而不是某个名词上：
      - "知识库里有哪些文档"     → 问清单      → 放行（kb_stats 能准确回答）
      - "库里那位同事叫什么名字" → 问具体实体  → 拦截（含"库里"但必须走检索/拒答）
      - "你们系统每天的 QPS 峰值" → 问性能指标  → 拦截（含不了性能类词也要拦）
    """
    q = (question or "").lower()
    if not any(t in q for t in _KB_TOKENS):
        return False
    if any(t in q for t in _KB_TROUBLE_HINTS):       # 故障/性能问题必须检索
        return False
    # "多少"这类数量词太泛（"工号是多少"也命中），必须排除在问"具体实体"的问题
    if any(t in q for t in _KB_ENTITY_ASK_HINTS):
        return False
    return any(h in q for h in _KB_INVENTORY_HINTS)  # 必须是在问清单/数量/规模


class AgentOrchestrator:
    """一次 Agent 运行的编排器（无状态，可被多请求共享）。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.settings = engine.settings

    @property
    def nodes(self) -> AgentNodes:
        return self.engine.agent_nodes

    # ------------------------------------------------------------------ 主循环
    async def run(
        self,
        question: str,
        session_id: str | None,
        use_history: bool = True,
        *,
        stream: bool = False,
        max_rounds: int | None = None,
    ) -> AsyncIterator[dict]:
        """跑到结束，逐个 yield 事件；最后一个事件 type="final"。

        stream=True 时，答案会以 token 事件边生成边推送（SSE 用）；
        stream=False 时只在最后一次性给答案（普通 JSON 接口用）。
        """
        s = self.settings
        started = time.perf_counter()
        sid = self.engine.memory.get_or_create(session_id)
        history_text = (
            self.engine.memory.format_history(sid, s.history_max_turns) if use_history else ""
        )
        state = AgentState(question=question, session_id=sid, history_text=history_text)
        registry = build_registry(self.engine, state)

        # ---------- ① 规划 ----------
        t0 = time.perf_counter()
        plan = await self.nodes.plan(state, question, registry.names())
        state.task_type = plan.task_type
        state.intent = plan.intent or question
        state.plan_steps = plan.steps
        state.queries = [q.strip() for q in plan.search_queries if q and q.strip()] or [question]
        state.max_retrieval_rounds = max_rounds or s.agent_max_retrieval_rounds

        # 规划结果的口径守卫：stats 分支只服务"问知识库自身"的问题，
        # 否则退化成普通问答（按资料检索 + 必要时拒答），避免答非所问。
        guard_note = ""
        if state.task_type == "stats" and not _looks_like_kb_self_question(question):
            guard_note = "规划器判为 stats，但问题并非在问知识库自身 → 守卫改为普通问答"
            state.task_type = "qa"
            state.reflections.append(guard_note)

        state.add_step(AgentStep(
            index=0, kind="plan", title=f"规划：{state.task_type}",
            detail=" / ".join(state.plan_steps) + (f"（{guard_note}）" if guard_note else ""),
            observation={
                "task_type": state.task_type,
                "intent": state.intent,
                "search_queries": state.queries,
                "answer_style": plan.answer_style,
                "guard": guard_note or None,
            },
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        ))
        yield {"type": "plan", "data": state.steps[-1].to_dict()}

        # chitchat：与知识库无关，直接礼貌收场，不浪费检索与 token
        if state.task_type == "chitchat":
            state.answer = (
                "我是企业知识库问答助手，只能基于库内文档回答问题。"
                "请提出与知识库内容相关的问题，例如：“混合检索为什么要用 RRF 融合？”"
            )
            state.stop_reason = "chitchat"
            yield {"type": "token", "data": {"text": state.answer}}
            yield self._final_event(state, started)
            self._remember(state)
            return

        # ---------- ② 检索循环（act → observe → grade → reflect/rewrite）----------
        for rnd in range(1, state.max_retrieval_rounds + 1):
            state.round = rnd
            # 首轮只打最可能命中的那条检索式：省一次检索开销，也让轨迹更好读；
            # 后续轮次才把多条改写检索式都打出去（这是"越检越宽"的正常策略）。
            turn_queries = state.queries[:1] if rnd == 1 else self._pending_queries
            for q in turn_queries:
                t0 = time.perf_counter()
                obs = await registry.call("knowledge_search", query=q)
                step = state.add_step(AgentStep(
                    index=0, kind="act", title=f"第 {rnd} 轮检索：{q}",
                    detail=f"命中 {obs.get('returned', 0)} 条（新增 {obs.get('new', 0)} 条）",
                    tool="knowledge_search", args={"query": q},
                    observation=obs, elapsed_ms=int((time.perf_counter() - t0) * 1000),
                ))
                yield {"type": "tool", "data": step.to_dict()}

            # kb_stats 是确定性工具：stats 类问题直接用它回答，不需要生成
            if state.task_type == "stats":
                t0 = time.perf_counter()
                stats_obs = await registry.call("kb_stats")
                step = state.add_step(AgentStep(
                    index=0, kind="act", title="读取知识库统计",
                    detail=f"{stats_obs.get('doc_count', 0)} 篇文档 / {stats_obs.get('chunk_count', 0)} 个分块",
                    tool="kb_stats", observation=stats_obs,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                ))
                yield {"type": "tool", "data": step.to_dict()}
                state.answer = self._render_stats(stats_obs)
                state.verdict = "deterministic"
                state.stop_reason = "stats_tool"
                for piece in _chunk_text(state.answer):
                    yield {"type": "token", "data": {"text": piece}}
                yield self._final_event(state, started)
                self._remember(state)
                return

            # ---------- ③ 相关性判定（第一道防幻觉闸门）----------
            t0 = time.perf_counter()
            grade = await self.nodes.grade(state, question, state.evidence)
            relevant_ids = {str(x).strip() for x in (grade.relevant_ids or [])}
            # 分数下限保护：精排分数接近本批最高分的片段，即使判定器说"不相关"也保留。
            # 为什么需要它（真实踩坑）：判定器是 LLM，会误杀 —— 实测出现过
            # 「命中片段含关键词、字数 1921，被判定器过滤后只剩 459 字」的情况，
            # 直接导致回答缺要点。过滤可以少留，但不能把高分证据扔掉。
            # 分情况取值：判定"资料不足"时说明我们本就缺信息，此时更不该再裁证据
            # （越裁越缺）；判定"充分"时才放心收紧。
            ratio = s.agent_score_floor_ratio if grade.sufficient else s.agent_score_floor_ratio_loose
            scores = [e.score for e in state.evidence] or [0.0]
            floor = max(scores) * ratio
            relevant: list = []
            protected = 0
            for i, item in enumerate(state.evidence, start=1):
                keep_by_id = str(i) in relevant_ids
                keep_by_score = item.score >= floor and item.score > 0
                if not grade.sufficient and not keep_by_id and not keep_by_score:
                    item.relevant, item.reason = False, "判定：与问题不直接相关"
                    continue
                if keep_by_id or (grade.sufficient and not relevant_ids):
                    item.relevant, item.reason = True, "判定：相关资料"
                else:
                    item.relevant = True
                    item.reason = f"分数保护：{item.score:.3f} ≥ 本批最高分的 {ratio:.0%}"
                    protected += 1
                relevant.append(item)
            top_score = max((e.score for e in relevant), default=0.0)
            step = state.add_step(AgentStep(
                index=0, kind="grade", title=f"第 {rnd} 轮判定：{'资料充分' if grade.sufficient else '资料不足'}",
                detail=grade.reason or grade.missing,
                observation={
                    "sufficient": grade.sufficient, "confidence": grade.confidence,
                    "missing": grade.missing, "relevant_ids": sorted(relevant_ids),
                    "kept": len(relevant), "total": len(state.evidence),
                    "score_protected": protected, "floor_ratio": ratio,
                    "top_score": round(float(top_score), 4),
                },
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            ))
            yield {"type": "grade", "data": step.to_dict()}

            enough = grade.sufficient and bool(relevant)
            if enough and grade.confidence >= s.agent_grade_min_confidence:
                break
            # 「强证据提前收束」：判定器天然偏严（宁可说不足也不要放过噪声），
            # 但精排分数很高且相关片段不止一条时，再检一轮的边际收益很低。
            # 用确定性规则提前停机，是"省时省钱"与"效果不降"之间最划算的一刀。
            if relevant and top_score >= s.agent_strong_score:
                state.reflections.append(
                    f"第 {rnd} 轮精排最高分 {top_score:.3f} ≥ 阈值 {s.agent_strong_score}，"
                    f"已收束（判定器仍判不足：{grade.missing or '未说明'}）"
                )
                step = state.add_step(AgentStep(
                    index=0, kind="reflect", title="强证据提前收束，停止继续检索",
                    detail=f"精排最高分 {top_score:.3f}，相关片段 {len(relevant)} 条",
                    observation={"top_score": round(float(top_score), 4), "round": rnd},
                ))
                yield {"type": "reflect", "data": step.to_dict()}
                break
            if enough:
                state.reflections.append(
                    f"第 {rnd} 轮资料相关但置信度偏低（{grade.confidence:.2f}），补检一轮"
                )
            if rnd >= state.max_retrieval_rounds:
                state.stop_reason = "max_rounds"
                break

            # ---------- ④ 反思 + 改写检索式（第二轮的输入）----------
            t0 = time.perf_counter()
            rw = await registry.call(
                "query_rewrite", question=question, missing=grade.missing or "",
                n=s.agent_rewrite_n,
            )
            self._pending_queries = rw.get("queries") or [question]
            state.queries.extend(self._pending_queries)
            note = f"资料不足（{grade.missing or '未说明缺什么'}）→ 换检索式：{'；'.join(self._pending_queries)}"
            state.reflections.append(note)
            step = state.add_step(AgentStep(
                index=0, kind="reflect", title=f"第 {rnd} 轮反思：改写检索式",
                detail=note, tool="query_rewrite",
                args={"missing": grade.missing}, observation=rw,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            ))
            yield {"type": "reflect", "data": step.to_dict()}

        # ---------- ⑤ 证据压缩（条件触发，多一步工具调用）----------
        evidence = state.relevant_evidence()
        if evidence and (
            len(question) > s.agent_compress_min_question_chars
            or any(h in question for h in _COMPRESS_HINTS)
        ):
            t0 = time.perf_counter()
            obs = await registry.call("evidence_compress", question=question)
            step = state.add_step(AgentStep(
                index=0, kind="act", title="压缩证据（去噪 + 控上下文预算）",
                detail=f"压缩 {obs.get('compressed', 0)} 段，节省约 "
                       f"{float(obs.get('token_save_ratio', 0)):.0%} 字符",
                tool="evidence_compress", observation=obs,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            ))
            yield {"type": "tool", "data": step.to_dict()}
            evidence = state.relevant_evidence()

        # 证据为空 → 在控制流上直接短路（不调用生成），拒答模板保证不编造
        if not evidence:
            state.answer = self.nodes._refusal_text(state)
            state.stop_reason = state.stop_reason or "no_relevant_evidence"
            for piece in _chunk_text(state.answer):
                yield {"type": "token", "data": {"text": piece}}
            yield self._final_event(state, started)
            self._remember(state)
            return

        # ---------- ⑥ 决策类问题：先生成结构化备忘录 ----------
        memo: DecisionMemo | None = None
        if state.task_type == "decision":
            t0 = time.perf_counter()
            obs = await registry.call("decision_memo", topic=state.intent or question)
            if "memo" in obs:
                memo = DecisionMemo.model_validate(obs["memo"])
            step = state.add_step(AgentStep(
                index=0, kind="act", title="生成决策备忘录（结论/依据/风险/行动）",
                detail=(memo.conclusion[:80] if memo else str(obs.get("error", "")))[:120],
                tool="decision_memo", observation=obs,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            ))
            yield {"type": "tool", "data": step.to_dict()}
            if memo is not None:
                state.memo = memo

        # ---------- ⑦ 生成答案 ----------
        t0 = time.perf_counter()
        yield {"type": "answer_start", "data": {"evidence_count": len(evidence)}}
        style = plan.answer_style
        extra = ""
        if memo is not None:
            extra = (
                "【已生成的决策备忘录，请在其基础上组织成自然语言回答，"
                "保留结论/依据/风险/行动的结构并标注引用】\n"
                + json.dumps(memo.model_dump(), ensure_ascii=False)
            )
        if stream:
            pieces: list[str] = []
            async for piece in self.nodes.answer_stream(
                state, question, evidence, style=style, extra=extra
            ):
                pieces.append(piece)
                yield {"type": "token", "data": {"text": piece}}
            state.answer = "".join(pieces)
        else:
            state.answer = await self.nodes.answer(
                state, question, evidence, style=style, extra=extra
            )
            for piece in _chunk_text(state.answer):
                yield {"type": "token", "data": {"text": piece}}
        state.add_step(AgentStep(
            index=0, kind="answer", title="生成回答",
            detail=f"{len(state.answer)} 字，引用 {len(evidence)} 条证据",
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        ))

        # ---------- ⑧ 忠实度校验（第二道防幻觉闸门）----------
        if s.agent_verify_enabled and state.answer.strip():
            t0 = time.perf_counter()
            verdict = await self.nodes.verify(state, question, state.answer, evidence)
            state.verdict = verdict.reason[:200] if not verdict.grounded else "grounded"
            state.grounded = verdict.score
            state.unsupported = verdict.unsupported
            state.verdict = "grounded" if verdict.grounded else "ungrounded"
            state.verify_reason = verdict.reason
            if not verdict.grounded:
                state.answer += self._verify_warning(verdict)
            step = state.add_step(AgentStep(
                index=0, kind="verify",
                title=f"忠实度校验：{'通过' if verdict.grounded else '发现问题'}",
                detail=verdict.reason,
                observation={
                    "grounded": verdict.grounded, "score": verdict.score,
                    "unsupported": verdict.unsupported,
                },
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            ))
            yield {"type": "verify", "data": step.to_dict()}

        state.stop_reason = state.stop_reason or "answered"
        yield self._final_event(state, started)
        self._remember(state)

    # ------------------------------------------------------------------ 内部工具
    _pending_queries: list[str] = []

    @staticmethod
    def _verify_warning(verdict) -> str:
        """校验未通过时的显式提示：宁可让用户看到"这句可能没依据"，也不静默放行。"""
        items = "；".join(verdict.unsupported[:3]) if verdict.unsupported else "部分表述"
        return (
            "\n\n---\n"
            "⚠️ 忠实度自检提示：以下表述在检索到的资料中未找到直接依据，请谨慎采信 —— "
            f"{items}。建议补充相关文档，或换一种问法复核。"
        )

    @staticmethod
    def _render_stats(obs: dict) -> str:
        lines = [
            f"知识库当前共有 {obs.get('doc_count', 0)} 篇文档、{obs.get('chunk_count', 0)} 个分块，"
            f"向量后端为 {obs.get('vector_backend', '-')}，"
            f"重排{'已开启' if obs.get('rerank_enabled') else '未开启'}。",
            "",
            "文档清单（按上传时间倒序）：",
        ]
        for d in obs.get("docs", []):
            lines.append(f"- 《{d['title']}》（{d['filename']}）：{d['chunks']} 个分块，{d.get('uploaded_at', '')}")
        return "\n".join(lines)

    def _final_event(self, state: AgentState, started: float) -> dict:
        """把状态编译成对外契约：答案 + 证据 + 来源 + 轨迹 + 用量。"""
        evidence = state.relevant_evidence() or state.evidence
        sources = [
            SourceRef(
                chunk_id=e.chunk_id, doc_id=e.doc_id, doc_title=e.doc_title, page=e.page,
                score=round(float(e.score), 4), snippet=_to_snippet(e.body), cite_index=i,
            )
            for i, e in enumerate(evidence, start=1)
        ]
        return {
            "type": "final",
            "data": {
                "session_id": state.session_id,
                "answer": state.answer,
                "sources": [s.model_dump() for s in sources],
                "used_history": bool(state.history_text),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "model": self.nodes.router.model_name("agent"),
                "usage": state.usage_total(),
                "agent": {
                    "task_type": state.task_type,
                    "intent": state.intent,
                    "plan": state.plan_steps,
                    "queries": state.queries,
                    "rounds": state.round,
                    "stop_reason": state.stop_reason,
                    "verdict": state.verdict,
                    "verify_reason": state.verify_reason,
                    "grounded_score": state.grounded,
                    "unsupported": state.unsupported,
                    "reflections": state.reflections,
                    "evidence": [
                        e.to_evidence(i) for i, e in enumerate(evidence, start=1)
                    ],
                    "memo": state.memo.model_dump() if state.memo else None,
                    "steps": state.trace(),
                },
            },
        }

    def _remember(self, state: AgentState) -> None:
        """把这一轮写回会话记忆（多轮对话与后续评测都要用）。"""
        self.engine.memory.add_turn(
            state.session_id,
            ChatTurn(
                state.question, state.answer,
                " / ".join(state.queries[:2]) or None,
                [t for t in dict.fromkeys(e.doc_title for e in state.evidence)],
            ),
        )


def _chunk_text(text: str, size: int = 24):
    """把非流式答案切成小片段发 token 事件：让前端两种模式用同一套渲染逻辑。"""
    for i in range(0, len(text), size):
        yield text[i: i + size]
