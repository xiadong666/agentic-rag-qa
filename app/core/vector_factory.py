"""向量库工厂：按配置返回 FAISS 或 Qdrant 实现（策略模式 + 优雅降级）。

设计要点：
1. **面向接口编程**：engine 只依赖 add/search/clear/save/load/size 这套契约，
   换后端不用改业务代码；
2. **降级策略**：Qdrant 依赖缺失或连不上时，自动回退 FAISS 并打警告 ——
   生产里“能降级”比“直接挂掉”重要。
"""
from __future__ import annotations

import logging

from ..config import Settings
from .vector_store import FaissVectorStore

logger = logging.getLogger(__name__)


def create_vector_store(settings: Settings):
    if settings.vector_backend == "qdrant":
        try:
            from .qdrant_store import QdrantVectorStore

            return QdrantVectorStore(
                url=settings.qdrant_url,
                path=settings.qdrant_local_path,
                collection=settings.qdrant_collection,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Qdrant 后端不可用（%s），已自动降级为 FAISS", e)
    return FaissVectorStore()
