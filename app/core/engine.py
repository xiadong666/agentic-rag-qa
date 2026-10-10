"""RAG 引擎：把 解析/分块/向量化/存储/检索/重排/记忆/生成 串成一条完整链路。

这是全项目最重要的“编排层”。它解释了 RAG 的本质：
  文档(离线) → 切块 → 向量化入库            [知识沉淀]
  问题(在线) → 检索 → 重排 → 拼上下文 → 生成 [知识取用]

知识点：
1. 同步的 CPU 密集操作（解析/embedding/FAISS）包在 asyncio.to_thread 里，
   避免阻塞事件循环 —— 但用一把 asyncio.Lock 串行化“写操作与搜索”，
   保证索引一致性（单进程内安全且好讲）。
2. LLM 生成使用 LCEL：ChatPromptTemplate | llm | StrOutputParser，
   支持 astream 逐 token 输出（SSE 推送前端）。
3. 引用来源贯穿始终：分块时记 page → 检索命中带出处 → 拼上下文编号 →
   模型按 [n] 引用 → 响应里把 sources 结构化返回。链路每一环都在为溯源服务。
"""
from __future__ import annotations

import asyncio
import time
import uuid

# —— 关键：HF 环境必须在任何会连带导入 transformers / huggingface_hub 的库
#    （如 langchain 系）之前设置好，否则其“联网常量”会在 import 时被固化，
#    导致后续设置 HF_HUB_OFFLINE=1 / HF_ENDPOINT 镜像不再生效（国内报
#    WinError 10051 直连 huggingface.co）。所以这里在导入前立刻执行。 ——
from ..config import get_settings as _get_settings
from .hf_env import apply as _apply_hf_env

_apply_hf_env(_get_settings())

from ..config import Settings
from ..schemas import SourceRef
from .agent import AgentOrchestrator
from .agent_nodes import AgentNodes
from .bm25 import BM25Index
from .chunking import Chunk, split_pages_into_chunks
from .embeddings import Embedder, create_embedder
from .llm_router import LLMRouter
from .memory import ChatMemory, ChatTurn
from .parsing import ParsedDocument, parse_file
from .prompts import ANSWER_SYSTEM, REWRITE_SYSTEM, format_context_block, format_history_block
from .rerank import create_reranker
from .retrieval import HybridRetriever, RankedChunk
from .store import ChunkRecord, DocRecord, KnowledgeStore
from .token_stats import UsageStats, estimate_tokens, extract_usage
from .vector_factory import create_vector_store
from .vector_store import FaissVectorStore


def _to_snippet(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class RAGEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = KnowledgeStore(settings.kb_json_path)
        self.embedder: Embedder = create_embedder(settings)
        self.vectors = create_vector_store(settings)   # FAISS / Qdrant 可配置切换
        self.bm25 = BM25Index()
        self.retriever = HybridRetriever(self.vectors, self.bm25, self.store)
        self.reranker = create_reranker(settings)
        self.memory = ChatMemory(settings.sessions_path)
        self.router = LLMRouter(settings)              # 模型路由（中台能力）
        self.stats = UsageStats(settings.stats_path)   # Token 统计与成本（中台能力）
        # ---- Agentic RAG：节点（LLM 决策点） + 编排器（状态机）----
        # 组合而非继承：engine 管"知识与检索"，agent_nodes 管"决策"，agent 管"控制流"
        self.agent_nodes = AgentNodes(settings, self.router, self.stats)
        self.agent = AgentOrchestrator(self)
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- 初始化
    @property
    def llm(self):
        """默认（answer 档）模型客户端；未配置 key 时返回 None。"""
        return self.router.get("answer")

    def _rebuild_all_sync(self) -> None:
        """按当前 store 全量重建向量索引与 BM25（启动或删除文档后调用）。"""
        chunks = self.store.chunks
        self.vectors.clear()
        self.bm25.clear()
        if not chunks:
            return
        vecs = self.embedder.encode([c.text for c in chunks])
        self.vectors.add(vecs)
        self.vectors.save(self.settings.faiss_index_path)
        for c in chunks:
            self.bm25.add(c.chunk_id, c.text)
        self.bm25.rebuild_stats()

    async def initialize(self) -> None:
        """启动时：有索引文件直接加载，否则全量重建。"""
        async with self._lock:
            loaded = await asyncio.to_thread(self.vectors.load, self.settings.faiss_index_path)
            if not loaded or self.vectors.size != self.store.total_chunks():
                await asyncio.to_thread(self._rebuild_all_sync)
            else:
                for c in self.store.chunks:
                    self.bm25.add(c.chunk_id, c.text)
                self.bm25.rebuild_stats()

    # ---------------------------------------------------------------- 入库
    async def ingest_file(self, path: str, filename: str, title: str | None = None) -> dict:
        """解析 → 分块 → 向量化 → 入库。返回统计信息。"""
        started = time.perf_counter()
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        display_title = (title or "").strip() or filename.rsplit(".", 1)[0]

        # 1) 解析（CPU：丢线程池）
        parsed: ParsedDocument = await asyncio.to_thread(parse_file, path, filename)
        # 2) 分块（参数来自配置）
        chunks: list[Chunk] = split_pages_into_chunks(
            parsed.pages,
            doc_id=doc_id,
            doc_title=display_title,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            raise ValueError("解析成功但没有产出任何分块，请检查文档内容。")

        async with self._lock:
            # 3) 向量化（CPU：丢线程池）
            vecs = await asyncio.to_thread(self.embedder.encode, [c.text for c in chunks])
            # 4) 落库：先写 JSONL 记录（位置 0..n-1），再往 FAISS 追加同序向量
            doc = DocRecord.new(doc_id, display_title, filename, parsed.char_count)
            records = [
                ChunkRecord(
                    chunk_id=c.chunk_id,
                    doc_id=doc_id,
                    doc_title=display_title,
                    page=c.page,
                    text=c.text,
                    meta=c.meta,
                )
                for c in chunks
            ]
            self.store.add_doc_with_chunks(doc, records)
            self.vectors.add(vecs)
            self.vectors.save(self.settings.faiss_index_path)
            # 5) BM25 增量更新
            for c in chunks:
                self.bm25.add(c.chunk_id, c.text)
            self.bm25.rebuild_stats()

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "doc_id": doc_id,
            "char_count": parsed.char_count,
            "chunk_count": len(chunks),
            "elapsed_ms": elapsed_ms,
        }

    async def delete_document(self, doc_id: str) -> bool:
        async with self._lock:
            ok = self.store.delete_doc(doc_id)
            if ok:
                await asyncio.to_thread(self._rebuild_all_sync)
            return ok

    # ---------------------------------------------------------------- 检索
    async def search(self, question: str, top_k: int | None = None) -> list[SourceRef]:
        """对外检索接口：混合检索 → (可选)重排 → 转 SourceRef。"""
        sources, _ = await self._search_ranked(question, top_k)
        return sources

    async def _search_ranked(
        self, query: str, top_k: int | None = None
    ) -> tuple[list[SourceRef], list[RankedChunk]]:
        """核心检索：embedding → 稠密 + BM25 → RRF 融合 → cross-encoder 重排。"""
        async with self._lock:
            q_emb = await asyncio.to_thread(self.embedder.embed_query, query)
            ranked = await asyncio.to_thread(
                self.retriever.hybrid_search,
                query,
                q_emb,
                dense_k=self.settings.retrieve_dense_k,
                sparse_k=self.settings.retrieve_sparse_k,
                rrf_k=self.settings.rrf_constant,
            )
            if self.reranker is not None:
                ranked = await asyncio.to_thread(
                    self.reranker.rerank, query, ranked, self.settings.rerank_top_k
                )
        top = ranked[: top_k if top_k else self.settings.rerank_top_k]
        return self._ranked_to_sources(top), top

    @staticmethod
    def _ranked_to_sources(ranked: list[RankedChunk]) -> list[SourceRef]:
        sources: list[SourceRef] = []
        for i, r in enumerate(ranked, start=1):
            c = r.chunk
            sources.append(
                SourceRef(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    doc_title=c.doc_title,
                    page=c.page,
                    score=round(r.score, 4),
                    snippet=_to_snippet(c.text),
                    cite_index=i,
                )
            )
        return sources

    # ---------------------------------------------------------------- 生成
    async def _rewrite_question(self, question: str, history_text: str) -> str | None:
        """用 LLM 把“原问题+历史”改写为独立问题。返回 None = 无需/不可改写。

        这里用 **rewrite 档（通常是轻量模型）**，并通过 UsageStats 记账 ——
        改写属于高频低价值任务，是成本治理最该关注的一环。
        """
        llm = self.router.get("rewrite")
        if not self.settings.query_rewrite or llm is None or not history_text:
            return None
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await llm.ainvoke(
            [
                SystemMessage(content=REWRITE_SYSTEM),
                HumanMessage(content=f"对话历史：\n{history_text}\n\n用户最新问题：{question}"),
            ]
        )
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage = extract_usage(resp)
        estimated = usage is None
        if usage is None:
            usage = (estimate_tokens(history_text + question), estimate_tokens(text))
        self.stats.record(
            task="rewrite",
            model=self.router.model_name("rewrite"),
            prompt_tokens=usage[0],
            completion_tokens=usage[1],
            price_input_per_m=self.settings.llm_price_input_per_m,
            price_output_per_m=self.settings.llm_price_output_per_m,
            estimated=estimated,
        )
        return (text or "").strip() or None

    async def _build_answer_messages(
        self, question: str, history_text: str, *, rewrite: bool = True
    ) -> tuple[list[dict], list[SourceRef], str | None]:
        """准备检索（含历史改写）→ 拼上下文 → 返回 (消息, 来源, 改写后问题)。

        拆成纯数据准备函数：不调用生成 LLM，方便 /api/debug/prompt 与单测。
        rewrite=False 用于"只想看检索结果"的调试场景：跳过问题改写，省一次 LLM 调用。
        """
        rewritten = await self._rewrite_question(question, history_text) if rewrite else None
        search_q = rewritten or question
        sources, ranked = await self._search_ranked(search_q)
        # 上下文用“完整分块文本”，sources 只放摘要（给前端展示用）
        context = format_context_block([r.chunk for r in ranked])
        system = ANSWER_SYSTEM + "\n\n" + format_history_block(history_text)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"问题：{search_q}\n\n【参考资料】\n{context}"},
        ]
        return messages, sources, rewritten

    @staticmethod
    def _as_langchain_messages(messages: list[dict]):
        """把已渲染好的 {role, content} 字典转成 LangChain 消息对象。

        注意（重要坑）：消息内容是“已经拼好的最终文本”（正文里可能含 {item_id}
        这类代码花括号），绝不能再放进 ChatPromptTemplate —— 模板会把它当作
        未提供值的变量并抛错（INVALID_PROMPT_INPUT）。所以这里直接以消息列表
        调用模型；只有变量受控的“问题改写”才使用模板 + LCEL（见 _rewrite_question）。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        out = []
        for m in messages:
            msg = SystemMessage(content=m["content"]) if m["role"] == "system" else HumanMessage(content=m["content"])
            out.append(msg)
        return out

    async def answer(
        self,
        question: str,
        session_id: str | None,
        use_history: bool = True,
    ) -> dict:
        """完整回答（非流式）。返回 dict：answer/sources/session_id/..."""
        started = time.perf_counter()
        sid = self.memory.get_or_create(session_id)
        history_text = (
            self.memory.format_history(sid, self.settings.history_max_turns)
            if use_history
            else ""
        )
        messages, sources, rewritten = await self._build_answer_messages(question, history_text)
        llm = self.router.get("answer")          # 模型路由：answer 档
        if llm is None:
            raise RuntimeError(
                "尚未配置 LLM API Key（.env 的 LLM_API_KEY）。"
                "请填写后重启；也可先调用 /api/search 或 /api/debug/prompt 查看检索链路。"
            )
        model_name = self.router.model_name("answer")
        # 已渲染消息直接调用模型（不再过模板解析，避免正文 {xxx} 触发模板变量报错）
        resp = await llm.ainvoke(self._as_langchain_messages(messages))
        answer = resp.content if isinstance(resp.content, str) else str(resp.content)
        # ---- Token 统计与成本（中台能力）：优先用接口返回的用量，拿不到则估算 ----
        usage = extract_usage(resp)
        estimated = usage is None
        if usage is None:
            prompt_text = "".join(m["content"] for m in messages)
            usage = (estimate_tokens(prompt_text), estimate_tokens(answer))
        rec = self.stats.record(
            task="answer", model=model_name,
            prompt_tokens=usage[0], completion_tokens=usage[1],
            price_input_per_m=self.settings.llm_price_input_per_m,
            price_output_per_m=self.settings.llm_price_output_per_m,
            session_id=sid, estimated=estimated,
        )
        self.memory.add_turn(
            sid,
            ChatTurn(
                question,
                answer,
                rewritten,
                [s.doc_title for s in sources],
            ),
        )
        return {
            "session_id": sid,
            "answer": answer,
            "sources": [s.model_dump() for s in sources],
            "used_history": bool(history_text),
            "rewritten_question": rewritten,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "model": model_name,
            "usage": {
                "prompt_tokens": rec.prompt_tokens,
                "completion_tokens": rec.completion_tokens,
                "total_tokens": rec.total_tokens,
                "cost": rec.cost,
                "estimated": rec.estimated,
            },
        }

    async def answer_stream(
        self, question: str, session_id: str | None, use_history: bool = True
    ):
        """流式回答：异步生成器，依次产出 dict 事件。

        事件：meta(含来源) → token × N → done | error。
        """
        started = time.perf_counter()
        sid = self.memory.get_or_create(session_id)
        history_text = (
            self.memory.format_history(sid, self.settings.history_max_turns)
            if use_history
            else ""
        )
        messages, sources, rewritten = await self._build_answer_messages(question, history_text)
        yield {
            "type": "meta",
            "data": {
                "session_id": sid,
                "source_count": len(sources),
                "rewritten_question": rewritten,
                "sources": [s.model_dump() for s in sources],
            },
        }
        llm = self.router.get("answer")
        model_name = self.router.model_name("answer")
        if llm is None:
            yield {
                "type": "error",
                "data": {
                    "message": "尚未配置 LLM API Key（.env 的 LLM_API_KEY）。"
                    "检索/重排链路已正常完成，请配置 key 后重试。"
                },
            }
            return
        parts: list[str] = []
        usage: tuple[int, int] | None = None
        async for chunk in llm.astream(self._as_langchain_messages(messages)):
            piece = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            u = extract_usage(chunk)          # 流式下由最后一个 chunk 带回用量（stream_usage=True）
            if u:
                usage = u
            if piece:
                parts.append(piece)
                yield {"type": "token", "data": {"text": piece}}

        answer = "".join(parts)
        estimated = usage is None
        if usage is None:
            prompt_text = "".join(m["content"] for m in messages)
            usage = (estimate_tokens(prompt_text), estimate_tokens(answer))
        rec = self.stats.record(
            task="answer", model=model_name,
            prompt_tokens=usage[0], completion_tokens=usage[1],
            price_input_per_m=self.settings.llm_price_input_per_m,
            price_output_per_m=self.settings.llm_price_output_per_m,
            session_id=sid, estimated=estimated,
        )
        self.memory.add_turn(
            sid,
            ChatTurn(question, answer, rewritten, [s.doc_title for s in sources]),
        )
        yield {
            "type": "done",
            "data": {
                "session_id": sid,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "used_history": bool(history_text),
                "model": model_name,
                "usage": {
                    "prompt_tokens": rec.prompt_tokens,
                    "completion_tokens": rec.completion_tokens,
                    "total_tokens": rec.total_tokens,
                    "cost": rec.cost,
                    "estimated": rec.estimated,
                },
            },
        }

    # ================================================================ Agentic RAG
    async def agent_answer(
        self,
        question: str,
        session_id: str | None = None,
        use_history: bool = True,
        *,
        max_rounds: int | None = None,
    ) -> dict:
        """Agentic RAG（非流式）：跑完整个 Agent 循环，返回最终结果。

        返回结构与 answer() **保持一致的字段**（answer/sources/usage/elapsed_ms...），
        额外多一个 agent 字段（计划、轨迹、证据、判定、校验结论）——
        这样前端与评测脚本可以只换端点、不改解析逻辑（接口兼容是工程底线）。
        """
        final: dict | None = None
        async for evt in self.agent.run(
            question, session_id, use_history, stream=False, max_rounds=max_rounds
        ):
            if evt["type"] == "final":
                final = evt["data"]
        if final is None:  # 理论上不会发生；兜底避免 None 穿透
            raise RuntimeError("Agent 未产出最终结果")
        return final

    async def agent_answer_stream(
        self,
        question: str,
        session_id: str | None = None,
        use_history: bool = True,
        *,
        max_rounds: int | None = None,
    ):
        """Agentic RAG（流式）：事件序列 = plan → tool/grade/reflect → answer_start
        → token × N → verify → final。

        注意：流式下"忠实度校验"发生在 token 已经推给前端之后，
        所以校验结论只能追加提示、无法撤回已输出的内容 ——
        这是流式的固有代价，也是"决定哪些能力只在非流式提供"的工程取舍。
        """
        async for evt in self.agent.run(
            question, session_id, use_history, stream=True, max_rounds=max_rounds
        ):
            yield evt
