"""FAISS 稠密向量库封装。

为什么选 FAISS（而不是 Chroma/Pinecone/Qdrant）做教学：
1. 它是向量检索领域“教科书”级库：了解 IndexFlatIP / 内积 / 持久化，
   再去用任何云向量库都是一通百通；
2. 进程内、CPU 即可跑，无服务、无网络依赖，最适合讲原理和演示。

知识点：
1. IndexFlatIP = “暴力全量内积”：精确但 O(N)；大数据量换 HNSW/IVF（近似）。
   因为我们已把向量 L2 归一化，内积 == 余弦相似度。
2. faiss 索引只存向量与 id，不存原文 —— 原文(含出处元数据)放 JSONL，
   两边靠“向量位置 = 记录数组下标”对齐（经典架构：向量库 + 元数据库分离）。
3. 写盘 write_index / 读盘 read_index 即可持久化；删除文档采用“重建索引”
   策略（演示规模够用，真实项目用带删除标记的倒排或向量库的 delete 接口）。
"""
from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


class FaissVectorStore:
    def __init__(self) -> None:
        self._index: faiss.Index | None = None  # FAISS 索引
        self._dim: int | None = None  # 向量维度

    """FAISS 向量库。

    1. 向量归一化后内积 == 余弦相似度；
    2. 索引只存向量与 id，不存原文；
    3. 写盘 / 读盘即可持久化；删除文档采用“重建索引”策略。
    """

    # 属性：向量数量（即记录数组长度）
    @property
    def size(self) -> int:
        return int(self._index.ntotal) if self._index is not None else 0

    def _ensure(self, dim: int) -> None:
        if self._index is None:
            self._dim = dim
            # MetricType.METRIC_INNER_PRODUCT：内积（向量已归一化 → 等价余弦）
            self._index = faiss.IndexFlatIP(dim)

    def add(self, embeddings: np.ndarray) -> None:
        """追加向量；返回新向量的起始位置（位置即记录数组下标）。"""
        if embeddings.shape[0] == 0:
            return
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)  # 转 float32
        self._ensure(embeddings.shape[1])  # 确保索引维度与向量维度一致
        self._index.add(embeddings)  # faiss.add 内部会复制，无需担心引用问题

    # 搜索：返回 (positions, scores)，scores 越大越相似（cosine∈[-1,1]），top_k 最多返回 top_k 个
    def search(self, query_emb: np.ndarray, top_k: int) -> tuple[list[int], list[float]]:
        """返回 (positions, scores)，scores 越大越相似（cosine∈[-1,1]）。"""
        if self._index is None or self.size == 0:
            return [], []
        # np.ascontiguousarray(query_emb, dtype=np.float32) 确保 query_emb 是连续内存，避免 faiss 内部拷贝
        q = np.ascontiguousarray(query_emb, dtype=np.float32).reshape(1, -1)
        k = min(top_k, self.size)  # 最多返回 top_k 个
        scores, positions = self._index.search(q, k)  # 搜索 k 个最相似的向量
        return positions[0].tolist(), scores[0].tolist()  # 返回位置和分数

    def save(self, path: Path) -> None:
        if self._index is not None:
            # 确保目录存在
            path.parent.mkdir(parents=True, exist_ok=True)  # 确保目录存在
            faiss.write_index(self._index, str(path))

    def load(self, path: Path) -> bool:
        if path.exists():
            self._index = faiss.read_index(str(path))
            self._dim = self._index.d
            return True
        return False

    def clear(self) -> None:
        self._index = None
        self._dim = None
