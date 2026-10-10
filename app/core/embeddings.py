"""Embedding（文本向量化）层。

设计：抽象 Embedder 接口 + 两个实现（本地 sentence-transformers / OpenAI 兼容 API）。
上层代码只依赖接口 —— 换模型、换厂商不用改业务逻辑（面向接口编程）。

知识点：
1. bi-encoder：query 和文档各自过同一个模型变成向量，用向量相似度代替“关键词重合”。
2. 中文首选 bge 系列：BAAI/bge-small-zh-v1.5 轻量（~95MB，CPU 可跑）。
   用 bge 时 query 侧要加指令前缀 "为这个句子生成表示以用于检索相关文章："，
   这是作者在训练时定义的“不对称用法”，不加会掉点（后面 rerank 篇会再谈对称性）。
3. 归一化：embedding 归一化后，内积 == 余弦相似度，FAISS 可用内积索引加速。
4. 线程安全：模型加载/推理不是线程安全的，全局加锁；本地模型懒加载（首请求才下载/加载）。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

import numpy as np

from ..config import Settings

# bge-zh 系列检索指令（作者官方推荐）
BGE_ZH_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class Embedder(ABC):  # Embedder 是一个抽象类，用于定义向量化器的接口ABC 是抽象基类，用于定义接口，不实现具体逻辑
    """向量化器接口：任何实现都要能批量编码文本。"""

    @abstractmethod  # abstractmethod 装饰器用于定义抽象方法，抽象方法是只声明不实现的方法，必须在子类中实现
    def encode(self, texts: list[str]) -> np.ndarray:  # encode 方法用于批量编码文本，返回 float32 矩阵 (n, dim)，已 L2 归一化
        """输入文本列表，输出 float32 矩阵 (n, dim)，已 L2 归一化。np.ndarray是 numpy 数组，用于存储向量表示"""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """编码单条查询（局部实现可加 query 指令）。返回 (dim,) 向量。"""


class LocalEmbedder(Embedder):  # LocalEmbedder 是一个具体实现类，用于本地模型的向量化
    """基于 sentence-transformers 的本地模型实现（默认，免 API key）。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model_name = settings.embedding_model_local
        self._device = settings.embedding_device
        self._batch_size = settings.embedding_batch_size
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        # 懒加载：首次真正用到时才加载，避免启动即占用几百 MB 内存。
        # 关键：加载前先把 HF 镜像/缓存目录环境变量准备好（见 hf_env.py），
        # 否则直连 huggingface.co 在国内会报 WinError 10051。
        from .hf_env import apply as apply_hf_env

        apply_hf_env(self._settings)
        from sentence_transformers import SentenceTransformer

        device = self._device
        if device == "auto":
            try:
                import torch  # 导入 torch 库，用于检查是否有可用的 CUDA 设备
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        self._model = SentenceTransformer(self._model_name, device=device)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with self._lock:  # 同一时刻只允许一个推理
            if self._model is None:
                self._load()
            vecs = self._model.encode(
                texts,  # 输入 输入文本列表
                batch_size=self._batch_size,  # 批处理大小
                normalize_embeddings=True,  # 关键：输出归一化向量
                show_progress_bar=False,  # 显示进度条
                convert_to_numpy=True,  # 转换为 numpy 数组
            )
        return np.asarray(vecs, dtype=np.float32)  # 返回 numpy 数组，类型为 float32，np.asarray 是 numpy 数组的构造函数

    def embed_query(self, text: str) -> np.ndarray:
        # bge-zh 需要 query 指令；文档侧 encode 时不需要
        return self.encode([BGE_ZH_QUERY_INSTRUCTION + text])[0]


class OpenAICompatEmbedder(Embedder):
    """OpenAI 兼容 /embeddings 接口实现（硅基流动/阿里百炼/智谱等）。

    演示 httpx 直接调接口的做法；生产可换成 SDK。注意很多 API 对 batch 有限制。
    """

    def __init__(self, settings: Settings):
        # 配置检查：确保 base_url/api_key/model 都配置了
        if not settings.embedding_base_url or not settings.embedding_api_key or not settings.embedding_model:
            raise RuntimeError("EMBEDDING_PROVIDER=openai 时需配置 base_url/api_key/model")
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._api_key = settings.embedding_api_key
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size
        self._dim: int | None = None

    def _call(self, texts: list[str]) -> np.ndarray:
        import httpx

        resp = httpx.post(
            f"{self._base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "input": texts},
            timeout=60.0,
        )
        resp.raise_for_status() # 抛出异常，表示请求失败
        data = resp.json()["data"] # 解析 JSON 数据
        data.sort(key=lambda d: d["index"])  # 个别网关不保证顺序
        arr = np.array([d["embedding"] for d in data], dtype=np.float32)  # 创建 numpy 数组，类型为 float32
        # 归一化（很多 API 已归一化，这里幂等处理）
        norms = np.linalg.norm(arr, axis=1, keepdims=True)  # 计算向量的范数
        return arr / np.maximum(norms, 1e-9)  # 归一化处理，避免除以零

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        out: list[np.ndarray] = []
        for i in range(0, len(texts), self._batch_size):# 分批次调用 API,batch_size 批处理大小
            out.append(self._call(texts[i: i + self._batch_size]))
        return np.vstack(out) if out else np.zeros((0, 0), dtype=np.float32)#np.vstack 是 numpy 数组的垂直函数，用于将多个 numpy 数组垂直堆叠

    def embed_query(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def create_embedder(settings: Settings) -> Embedder:
    """简单工厂：按配置返回对应实现。"""
    if settings.embedding_provider == "openai":
        return OpenAICompatEmbedder(settings)
    return LocalEmbedder(settings)
