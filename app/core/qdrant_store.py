"""Qdrant 向量库实现（与 FaissVectorStore 同接口，可配置切换）。

为什么提供第二种后端（设计要点）：
    FAISS 是**进程内库**：快、零部署，但没有多副本、没有元数据过滤、删除要重建；
    线上业务（多租户、按部门/密级过滤、在线增删、水平扩容）通常需要**向量数据库服务**，
    Qdrant 是其中轻量且易上手的一种。

两种运行模式（本实现都支持）：
    - 服务模式：设 QDRANT_URL=http://localhost:6333（生产用法，可多副本/持久化）
    - 本地模式：设 QDRANT_PATH=./data/qdrant（Docker/服务器都不需要，适合开发与演示）

与 FAISS 实现的关键一致性：**point id 就是记录下标**，所以 engine 里
“命中结果 → 原文/出处”的下标对齐逻辑无需改动。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Qdrant 后端：接口与 FaissVectorStore 保持一致（add/search/clear/save/load/size）。"""

    def __init__(self, *, url: str = "", path: str | Path | None = None, collection: str = "dsh_rag") -> None:
        from qdrant_client import QdrantClient

        self._collection = collection
        self._dim: int | None = None
        self._lock = threading.Lock()
        if url:
            self._client = QdrantClient(url=url, timeout=30)
            self._mode = f"server:{url}"
        else:
            local = Path(path or "./data/qdrant")
            local.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(local))
            self._mode = f"local:{local}"
        logger.info("Qdrant 后端就绪（%s，collection=%s）", self._mode, collection)

    # ---------- 内部工具 ----------
    def _exists(self) -> bool:
        try:
            names = [c.name for c in self._client.get_collections().collections]
        except Exception as e:  # noqa: BLE001
            logger.warning("Qdrant 获取集合列表失败：%s", e)
            return False
        return self._collection in names

    def _ensure_collection(self, dim: int) -> None:
        from qdrant_client.http import models as qm

        if not self._exists():
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )
            logger.info("已创建 Qdrant 集合 %s（dim=%d）", self._collection, dim)
        self._dim = dim

    # ---------- 与 FAISS 对齐的接口 ----------
    @property
    def size(self) -> int:
        if not self._exists():
            return 0
        try:
            return int(self._client.count(collection_name=self._collection, exact=True).count)
        except Exception:  # noqa: BLE001
            return 0

    def add(self, embeddings: np.ndarray) -> None:
        if embeddings.shape[0] == 0:
            return
        from qdrant_client.http import models as qm

        embeddings = np.asarray(embeddings, dtype=np.float32)
        with self._lock:
            self._ensure_collection(embeddings.shape[1])
            start = self.size  # 追加：新 point id 从当前数量继续 → 与记录下标对齐
            points = [
                qm.PointStruct(id=start + i, vector=vec.tolist(), payload={})
                for i, vec in enumerate(embeddings)
            ]
            self._client.upsert(collection_name=self._collection, points=points, wait=True)

    def search(self, query_emb: np.ndarray, top_k: int) -> tuple[list[int], list[float]]:
        if self.size == 0:
            return [], []
        q = np.ascontiguousarray(query_emb, dtype=np.float32).reshape(-1).tolist()
        limit = max(1, min(top_k, self.size))
        with self._lock:
            # 新版客户端用 query_points；老版本用 search（这里兼容两者）
            if hasattr(self._client, "query_points"):
                res = self._client.query_points(
                    collection_name=self._collection, query=q, limit=limit, with_payload=False
                ).points
            else:  # pragma: no cover - 兼容旧客户端
                res = self._client.search(collection_name=self._collection, query_vector=q, limit=limit)
        return [int(p.id) for p in res], [float(p.score) for p in res]

    def clear(self) -> None:
        with self._lock:
            if self._exists():
                self._client.delete_collection(collection_name=self._collection)

    def save(self, path: Path) -> None:
        """Qdrant 由客户端自身持久化（服务模式在服务端，本地模式在磁盘），无需额外落盘。"""
        return None

    def load(self, path: Path) -> bool:
        """返回“是否已有一份可用的集合”，engine 会据此决定加载还是重建。"""
        return self._exists() and self.size > 0
