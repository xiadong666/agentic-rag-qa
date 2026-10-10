"""重排序 Rerank。

为什么要“重排”（面试高频）：
1. 混合检索的候选来自两路、且只用了“粗粒度”的向量相似度/词频，
   相关文档可能排在 10 名开外、无关文档混进来；
2. 精排用 cross-encoder：把 (query, 文档) 拼成一个序列一起过模型，
   让两者 token 互相“看到”对方，比 bi-encoder 的“各自编码再算相似度”
   精细得多 —— 代价是慢（每对都要过一遍模型），所以只能对少量候选做。

经典三段式：召回(粗，快，全) → 融合 → 精排(细，慢，准) → 生成。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from ..config import Settings
from .retrieval import RankedChunk


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[RankedChunk], top_k: int) -> list[RankedChunk]:
        """输入排序候选，返回重排后 top_k。"""


class LocalCrossEncoderReranker(Reranker):
    """本地 cross-encoder 精排。

    中文场景推荐 bce-reranker-base_v1（对 bge/中文检索友好、体积小）。
    与 bge 不同，cross-encoder 不需要 query 指令：它看到的是完整 (query, 文档) 对。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model_name = settings.rerank_model
        self._device = settings.embedding_device  # 复用 embedding 的 device 配置
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        # 加载前先把 HF 镜像/缓存环境变量准备好（同 embeddings，见 hf_env.py）
        from .hf_env import apply as apply_hf_env

        apply_hf_env(self._settings)
        from sentence_transformers import CrossEncoder

        device = self._device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self._model = CrossEncoder(self._model_name, device=device)

    def rerank(self, query: str, candidates: list[RankedChunk], top_k: int) -> list[RankedChunk]:
        if not candidates:
            return []
        with self._lock:
            if self._model is None:
                self._load()
            pairs = [[query, c.chunk.text[:2000]] for c in candidates]
            scores = self._model.predict(
                pairs,
                batch_size=min(len(pairs), 16),
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        # cross-encoder 的 logits 越高越相关（可正可负），降序取前 top_k
        order = sorted(range(len(candidates)), key=lambda i: float(scores[i]), reverse=True)
        return [
            RankedChunk(candidates[i].chunk, float(scores[i]), "rerank")
            for i in order[:top_k]
        ]


def create_reranker(settings: Settings) -> Reranker | None:
    if not settings.rerank_enabled:
        return None
    return LocalCrossEncoderReranker(settings)
