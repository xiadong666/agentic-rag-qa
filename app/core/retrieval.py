"""混合检索：稠密(向量) + 稀疏(BM25) + RRF 融合 + 可选重排。

为什么“混合检索”是亮点（面试高频）：
- 只靠向量：语义 OK，但精确词（型号/人名/报错原文）召回弱；
- 只靠 BM25：精确词强，但同义改写（"怎么部署" vs "如何上线"）召回差；
- RRF(Reciprocal Rank Fusion)：不比较两种异构分数，只按“排名”融合，
  每个检索器给分 = Σ 1/(k + rank)。简单、无需调权重、对分数尺度不敏感，
  是工程上最常用的融合方案（还有加权和、Convex Combination 等变体）。

知识点：
1. 两个检索器各自取回 K 个候选 → 合并去重 → RRF 打分排序。
2. 候选集扩大后必须“重排”（rerank），否则噪声会进入生成阶段 ——
   这就是下一步 rerank.py 的动机：初筛要全，精排要准。
"""
from __future__ import annotations

from dataclasses import dataclass

from .bm25 import BM25Index
from .store import ChunkRecord
from .vector_store import FaissVectorStore


@dataclass
class RankedChunk:
    """检索/重排后的一段知识。score 含义随阶段变化，只用于排序展示。"""

    chunk: ChunkRecord
    score: float
    stage: str = "hybrid"   # dense | sparse | hybrid | rerank

def rrf_merge(
    ranked_a: list[RankedChunk],
    ranked_b: list[RankedChunk],
    k: int = 60,
) -> list[RankedChunk]:
    """Reciprocal Rank Fusion：按名次给分 1/(k+rank)，同 id 累加后降序。"""
    acc: dict[str, float] = {}
    holder: dict[str, RankedChunk] = {}
    for ranked, stage in ((ranked_a, "dense"), (ranked_b, "sparse")):
        for rank, item in enumerate(ranked, start=1):
            cid = item.chunk.chunk_id
            acc[cid] = acc.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in holder:
                holder[cid] = RankedChunk(item.chunk, 0.0, stage)
    merged = []
    for cid, score in sorted(acc.items(), key=lambda kv: kv[1], reverse=True):
        merged.append(RankedChunk(holder[cid].chunk, score, "hybrid"))
    return merged


class HybridRetriever:
    """把 向量库 + BM25 + 分块记录 串成一条检索链路。"""

    def __init__(
        self,
        vectors: FaissVectorStore,
        bm25: BM25Index,
        store,  # KnowledgeStore
    ) -> None:
        self.vectors = vectors
        self.bm25 = bm25
        self.store = store

    def dense_retrieve(self, query_emb, k: int) -> list[RankedChunk]:
        """向量检索：给定 query 向量，取回 k 个最相似的分块。"""
        positions, scores = self.vectors.search(query_emb, k) # 向量检索
        out: list[RankedChunk] = [] # 初始化空列表
        for pos, score in zip(positions, scores):  # 遍历位置和分数
            chunk = self.store.get_chunk(pos)  # 获取分块记录
            if chunk is not None:  # 确保分块存在
                out.append(RankedChunk(chunk, score, "dense"))  # 添加到输出列表
        return out # 返回输出列表

    """BM25 检索：给定查询文本，取回 k 个最相关的分块。"""  # BM25 检索
    def sparse_retrieve(self, query: str, k: int) -> list[RankedChunk]:
        """BM25 检索：给定查询文本，取回 k 个最相关的分块。"""
        out: list[RankedChunk] = [] # 初始化空列表
        for chunk_id, score in self.bm25.search(query, k): # BM25检索
            # chunk_id → 需要反查记录：demo 规模直接线性找（可用 dict 缓存优化）
            for c in self.store.chunks: # 遍历所有分块记录
                if c.chunk_id == chunk_id: # 匹配分块记录
                    out.append(RankedChunk(c, score, "sparse"))
                    break
        return out

    def hybrid_search(
        self,
        query: str,
        query_emb,
        *,
        dense_k: int = 12,
        sparse_k: int = 12,
        rrf_k: int = 60,
    ) -> list[RankedChunk]:
        """完整融合流程：两路召回 → RRF。"""
        dense = self.dense_retrieve(query_emb, dense_k)
        sparse = self.sparse_retrieve(query, sparse_k)
        return rrf_merge(dense, sparse, k=rrf_k)
