"""Agent 工具集：把"检索能力"包装成 Agent 可调用、可观测的工具。

设计要点（设计考虑）：
  1. **统一契约**：每个工具 = 名称 + 描述 + JSON Schema 参数 + 异步实现。
     描述是写给 LLM 看的"说明书"，参数是写给调用方看的"接口文档" ——
     工具描述质量直接决定 Agent 选不选得对，这一点比代码本身更重要。
  2. **工具要"窄"**：一个工具只做一件事（检索/改写/压缩/成文）。
     窄工具组合性更强、更好测、更省 token；"万能工具"是 Agent 失控的常见原因。
  3. **确定性的活不要交给 LLM**：知识库统计、引用编号、格式拼装全部用代码做，
     只有"需要语义理解"的部分（改写、判定、压缩、成文）才调模型 —— 又稳又省。
  4. **失败即降级**：工具抛错不炸整个 Agent 循环，而是返回 {"error": ...}，
     让 LLM（或编排代码）决定换个工具/换个检索式再来一次。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from .agent_state import DecisionMemo, ToolSpec

logger = logging.getLogger(__name__)


class ToolRegistry:
    """极简工具注册表：名字 → (描述, 参数, 实现)。"""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._impls: dict[str, Callable[..., Awaitable[dict]]] = {}

    def register(self, spec: ToolSpec, impl: Callable[..., Awaitable[dict]]) -> None:
        if spec.name in self._specs:
            raise ValueError(f"工具名重复：{spec.name}")
        self._specs[spec.name] = spec
        self._impls[spec.name] = impl

    def spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs)

    def schemas(self) -> list[dict]:
        return [s.to_openai_schema() for s in self._specs.values()]

    def describe(self) -> list[dict]:
        """给 /health、调试接口看的工具清单。"""
        return [
            {"name": s.name, "description": s.description, "parameters": list(s.parameters.get("properties", {}))}
            for s in self._specs.values()
        ]

    async def call(self, name: str, **kwargs: Any) -> dict:
        impl = self._impls.get(name)
        if impl is None:
            return {"error": f"未知工具：{name}", "available": self.names()}
        try:
            return await impl(**kwargs)
        except Exception as e:  # noqa: BLE001 —— 工具失败不应中断 Agent 循环
            logger.warning("工具 %s 执行失败：%s", name, e)
            return {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------- 工具参数 Schema
_PARAM_KNOWLEDGE_SEARCH = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "检索式（自然语言问题或关键词组合），越具体越好"},
        "top_k": {"type": "integer", "description": "返回条数，默认 4，范围 1~8"},
    },
    "required": ["query"],
}

_PARAM_QUERY_REWRITE = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "用户原始问题"},
        "missing": {"type": "string", "description": "上一轮判定为还缺什么信息（可为空）"},
        "n": {"type": "integer", "description": "生成几条互补检索式，默认 2"},
    },
    "required": ["question"],
}

_PARAM_EVIDENCE_COMPRESS = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "压缩要以它为中心，保留与它相关的信息"},
        "max_chars": {"type": "integer", "description": "每段压缩后的最大字符数，默认 320"},
    },
    "required": ["question"],
}

_PARAM_DECISION_MEMO = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "要给出的决策主题"},
        "constraints": {"type": "string", "description": "约束条件（预算、合规、时限等），可为空"},
    },
    "required": ["topic"],
}

_PARAM_KB_STATS = {
    "type": "object",
    "properties": {},
}

_PARAM_CALC = {
    "type": "object",
    "properties": {
        "expression": {"type": "string", "description": "只含数字与 + - * / ( ) 的四则运算表达式"},
        "note": {"type": "string", "description": "这个计算在算什么，一句话"},
    },
    "required": ["expression"],
}

# 纯数值四则运算白名单（不使用 eval —— 安全底线）
_CALC_RE = re.compile(r"^[0-9+\-*/().\s]+$")


class AgentTools:
    """所有工具的实现。构造时注入 engine（检索/重写/统计）与 run 上下文。

    每个 run 创建一个实例：工具需要读写"本次运行"的证据池，不能跨请求共享。
    """

    def __init__(self, engine, state) -> None:
        self.engine = engine
        self.state = state
        self._compressed_cache: dict[str, str] = {}

    # ---------------------------------------------------------- 1) 混合检索
    async def knowledge_search(self, query: str, top_k: int | None = None) -> dict:
        """走 engine 的混合检索链路（embedding → dense + BM25 → RRF → rerank）。

        这一步**不调用 LLM**，是纯检索：把结果写成 GradedChunk 进证据池，
        并返回带编号的摘要给"观察"环节用。
        """
        k = max(1, min(int(top_k or self.engine.settings.agent_retrieve_top_k), 8))
        sources, ranked = await self.engine._search_ranked(query, k)
        items = [
            self._to_graded(r.chunk, r.score, r.stage)
            for r in ranked
            if r.chunk is not None
        ]
        added = self.state.add_evidence(items)
        return {
            "query": query,
            "returned": len(items),
            "new": added,
            "preview": [
                {
                    "cite_index": i,
                    "doc_title": it.doc_title,
                    "page": it.page,
                    "score": round(float(it.score), 4),
                    "head": it.text[:120].replace("\n", " "),
                }
                for i, it in enumerate(items, start=1)
            ],
            "total_evidence": len(self.state.evidence),
        }

    # ---------------------------------------------------------- 2) 查询改写
    async def query_rewrite(self, question: str, missing: str = "", n: int = 2) -> dict:
        """生成互补检索式：把"问法"和"文档里的说法"对齐（同义词/上位词/术语）。"""
        n = max(1, min(int(n or 2), 3))
        return await self.engine.agent_nodes.rewrite_queries(self.state, question, missing, n)

    # ---------------------------------------------------------- 3) 证据压缩
    async def evidence_compress(self, question: str, max_chars: int = 320) -> dict:
        """压缩证据池（去噪 + 去重 + 抽关键句），降低生成 token 与"分心"噪声。

        压缩只改 GradedChunk.compressed，不改原文：引用时仍能回溯原文，
        这是"可审计"与"省 token"的折中。
        """
        max_chars = max(120, min(int(max_chars or 320), 800))
        targets = self.state.relevant_evidence()
        if not targets:
            return {"compressed": 0, "note": "证据池为空，先调用 knowledge_search"}
        # 完全重复的正文先去重（同一段被多路召回时常见）
        seen: set[str] = set()
        dedup = 0
        for it in targets:
            key = it.body.strip()
            if key in seen:
                it.compressed = self._compressed_cache.get(key, key[:max_chars])
                dedup += 1
            else:
                seen.add(key)
        need = [it for it in targets if not it.compressed and len(it.text) > max_chars]
        done = 0
        if need:
            pairs = await self.engine.agent_nodes.compress_chunks(question, need, max_chars)
            for it, text in zip(need, pairs):
                it.compressed = text
                self._compressed_cache[it.text.strip()] = text
                done += 1
        # 上下文预算裁剪：按分数从高到低装，装不下的标记为不相关（而不是硬截断）
        budget = int(self.engine.settings.agent_context_max_chars)
        ordered = sorted(targets, key=lambda x: x.score, reverse=True)
        kept: list[str] = []
        used = 0
        for it in ordered:
            body = it.body
            if used + len(body) > budget:
                it.relevant = False
                it.reason = (it.reason + "；超出上下文预算被丢弃").strip("；")
                continue
            used += len(body)
            kept.append(it.chunk_id)
        raw = sum(len(it.text) for it in targets) or 1
        save_ratio = round(1 - sum(len(it.body) for it in targets) / raw, 4)
        return {
            "compressed": done,
            "dup_collapsed": dedup,
            "kept": len(kept),
            "dropped_over_budget": len(targets) - len(kept),
            "context_chars": used,
            "budget": budget,
            "token_save_ratio": save_ratio,
        }

    # ---------------------------------------------------------- 4) 决策备忘录
    async def decision_memo(self, topic: str, constraints: str = "") -> dict:
        """把证据池变成结构化决策备忘录（结论/依据/风险/动作/引用）。

        企业级"决策系统"与"问答系统"的差别就在这一步：
        问答要的是"答案"，决策要的是"可执行、可追责的结构化建议"。
        """
        evidence = self.state.relevant_evidence() or self.state.evidence
        if not evidence:
            return {"error": "证据池为空，无法生成决策备忘录"}
        memo = await self.engine.agent_nodes.build_memo(self.state, topic, constraints, evidence)
        return {"memo": memo.model_dump()}

    # ---------------------------------------------------------- 5) 知识库统计
    async def kb_stats(self) -> dict:
        """确定性工具：知识库规模/文档清单（不调 LLM，零成本零幻觉）。"""
        store = self.engine.store
        docs = sorted(store.doc_list(), key=lambda d: d.uploaded_at, reverse=True)
        return {
            "doc_count": len(docs),
            "chunk_count": store.total_chunks(),
            "vector_backend": self.engine.settings.vector_backend,
            "rerank_enabled": self.engine.reranker is not None,
            "docs": [
                {"title": d.title, "filename": d.filename, "chunks": d.chunk_count,
                 "uploaded_at": d.uploaded_at}
                for d in docs[:20]
            ],
        }

    # ---------------------------------------------------------- 6) 安全计算
    async def calc(self, expression: str, note: str = "") -> dict:
        """白名单四则运算（绝不用 eval）：把"算数"从 LLM 手里拿走。

        LLM 做算术容易出错且不可复现；凡是能用代码算准的，就不要让模型猜。
        """
        expr = (expression or "").strip()
        if not expr or not _CALC_RE.match(expr):
            return {"error": "表达式只允许数字与 + - * / ( ) ."}
        try:
            value = eval(compile(expr, "<calc>", "eval"), {"__builtins__": {}}, {})  # noqa: S307
        except Exception as e:  # noqa: BLE001
            return {"error": f"计算失败：{e}"}
        return {"expression": expr, "value": value, "note": note}

    # ---------------------------------------------------------- 内部
    @staticmethod
    def _to_graded(chunk, score: float, stage: str):
        from .agent_state import GradedChunk

        return GradedChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            doc_title=chunk.doc_title,
            page=chunk.page,
            text=chunk.text,
            score=float(score),
            stage=stage,
        )


def build_registry(engine, state) -> ToolRegistry:
    """注册本次运行可用的全部工具。

    工具集刻意保持小而正交（6 个）：Agent 的工具越多，选错的概率越高；
    真正提升效果的是"检索质量 + 判定与反思"，而不是堆工具数量。
    """
    tools = AgentTools(engine, state)
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="knowledge_search",
            description=(
                "在企业知识库上做混合检索（向量 + BM25 + RRF + cross-encoder 重排），"
                "返回带来源与页码的资料片段并加入证据池。任何需要事实依据的问题都必须先调用它。"
            ),
            parameters=_PARAM_KNOWLEDGE_SEARCH,
        ),
        tools.knowledge_search,
    )
    reg.register(
        ToolSpec(
            name="query_rewrite",
            description=(
                "把问题改写成多条互补的检索式（同义说法/上位概念/文档里的专业术语），"
                "用于上一轮检索没命中或信息不足时扩大召回。返回的检索式要再用 knowledge_search 执行。"
            ),
            parameters=_PARAM_QUERY_REWRITE,
        ),
        tools.query_rewrite,
    )
    reg.register(
        ToolSpec(
            name="evidence_compress",
            description=(
                "压缩证据池：去掉与问题无关的内容与重复段落，只保留关键句，"
                "用于资料很长、上下文预算紧张时。压缩不改变来源，引用仍可回溯原文。"
            ),
            parameters=_PARAM_EVIDENCE_COMPRESS,
        ),
        tools.evidence_compress,
    )
    reg.register(
        ToolSpec(
            name="decision_memo",
            description=(
                "基于证据池生成结构化决策备忘录（结论/依据/风险/行动项/引用），"
                "用于「该怎么做 / 选哪个方案 / 给建议」这类决策型问题。"
            ),
            parameters=_PARAM_DECISION_MEMO,
        ),
        tools.decision_memo,
    )
    reg.register(
        ToolSpec(
            name="kb_stats",
            description=(
                "查询知识库自身的统计信息：文档数量、分块数量、文档清单、向量后端、是否开启重排。"
                "用于「库里有哪些文档 / 规模多大」这类系统性问题，不消耗检索与生成成本。"
            ),
            parameters=_PARAM_KB_STATS,
        ),
        tools.kb_stats,
    )
    reg.register(
        ToolSpec(
            name="calc",
            description=(
                "对数字做精确四则运算（只允许数字与 + - * / ( )）。"
                "凡是涉及计算都必须用它，不要自己心算。"
            ),
            parameters=_PARAM_CALC,
        ),
        tools.calc,
    )
    return reg
