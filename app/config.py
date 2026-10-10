"""配置中心。

知识点：
1. pydantic-settings：从环境变量 / .env 读取配置，字段声明即文档；
   比 os.environ.get(...) 散落各处更规范、可校验、可提示。
2. 单例模式（模块级 get_settings + lru_cache）：全局只有一份配置。
3. Path 统一用绝对路径（相对 cwd 的路径在换目录启动时会踩坑）。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 = rag-qa-system/（本文件位于 rag-qa-system/app/config.py）
ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """应用配置。字段名与环境变量同名（大写即可，pydantic 自动映射）。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),  # 显式绝对路径，避免依赖启动目录
        env_file_encoding="utf-8",
        extra="ignore",  # 容忍 .env 里多出的无关变量
    )

    # ---------- 服务 ----------
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # ---------- 数据目录 ----------
    data_dir: Path = ROOT_DIR / "data"

    # ---------- 上传限制 ----------
    max_upload_mb: float = 50.0  # 最大上传文件大小（MB）
    # ⚠️ 命名坑（真实踩过，值得记一笔）：pydantic-settings 是**按字段名**映射环境变量的。
    #    若字段名叫 allowed_extensions_raw，则 .env 里必须写 ALLOWED_EXTENSIONS_RAW；
    #    写成 ALLOWED_EXTENSIONS 会被**静默忽略**、一直用代码默认值 —— 不报错、极难发现
    #    （本项目就这么踩过一次：CSV 上传被 400 拦掉，查了半天以为是解析器不支持）。
    #    所以字段名与环境变量**逐字一致**，不留 _raw / _str 这类后缀：
    #      allowed_extensions  →  .env 写 ALLOWED_EXTENSIONS
    #      llm_task_routes_raw →  .env 写 LLM_TASK_ROUTES_RAW（这一项保留了后缀，因为 .env 里也是这么写的）
    allowed_extensions: str = "pdf,docx,txt,md,csv"  # 逗号分隔；扩展名与解析器能力对齐

    # ---------- 分块 ----------
    chunk_size: int = 500
    chunk_overlap: int = 50

    # ---------- Embedding ----------
    embedding_provider: Literal["local", "openai"] = "local"  # local | openai
    embedding_model_local: str = "BAAI/bge-small-zh-v1.5"  # local 模式下模型
    embedding_device: str = "auto"  # auto | cpu | cuda
    embedding_batch_size: int = 32  # openai 模式下批量大小
    embedding_base_url: str | None = None  # openai 模式下 base_url
    embedding_api_key: str | None = None  # openai 模式下 api_key
    embedding_model: str | None = None  # openai 模式下 model

    # ---------- 检索 ----------
    retrieve_dense_k: int = 12
    retrieve_sparse_k: int = 12  # 稀疏检索结果数量
    rrf_constant: int = 60  # RRF 融合常数 k
    rerank_enabled: bool = True  # 是否开启重排
    rerank_model: str = "maidalun1020/bce-reranker-base_v1"  # 重排模型
    rerank_top_k: int = 4  # 重排结果数量

    # ---------- LLM（OpenAI 兼容协议，默认 DeepSeek）----------
    # ⚠️ 密钥只从 .env / 环境变量读取，**绝不写进代码**：
    #    一旦硬编码默认值，文件被提交/打包/发给别人就等于泄露（而且 GitHub 会扫出来）。
    #    这里保持空字符串：未配置时 llm_ready=False，路由层返回 None，
    #    接口给出 "未配置 LLM_API_KEY" 的友好提示（而不是让代码报错）。
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1500

    # ---------- 模型路由（AI 中台能力 1/2）----------
    # 轻量模型：用于改写、分类、摘要等低成本任务；留空=与主模型相同
    llm_small_model: str = ""
    # 强力模型：用于决策备忘录这类高价值输出；留空=与主模型相同
    llm_strong_model: str = ""
    # 任务 → 模型档位（small | default | strong），逗号分隔
    # Agentic RAG 又拆出两档，体现"不同任务用不同模型"的治理思路：
    #   rewrite/grade/compress → small（高频、低价值，用小模型省钱）
    #   answer/memo            → default（最终交付物，用主模型保质量）
    llm_task_routes_raw: str = "rewrite:small,answer:default,grade:small,verify:small,compress:small,memo:strong,agent:default"

    # ---------- Token 统计与成本（AI 中台能力 2/2）----------
    # 单价：元 / 百万 token（按各厂商官网价格填写，仅用于成本估算）
    llm_price_input_per_m: float = 1.0
    llm_price_output_per_m: float = 2.0

    # ---------- 向量库后端（FAISS / Qdrant 双实现）----------
    vector_backend: Literal["faiss", "qdrant"] = "faiss"
    qdrant_url: str = ""            # 服务模式，如 http://localhost:6333
    qdrant_path: str = ""           # 本地模式目录；留空= <data_dir>/qdrant
    qdrant_collection: str = "dsh_rag"

    # ---------- 对话历史 ----------
    history_max_turns: int = 6
    query_rewrite: bool = True  # 历史改写为独立问题再检索

    # ---------- Agentic RAG（Agent 编排）----------
    # 总开关：关闭时 /api/chat 走原朴素 RAG 链路（向后兼容、可做 A/B 对比）
    agent_enabled: bool = True
    agent_max_retrieval_rounds: int = 3   # 最多几轮"检索→判定→改写"
    agent_retrieve_top_k: int = 5         # 单次检索召回条数（进证据池）
    agent_grade_min_confidence: int = 1   # 判定置信度门槛（0~1；越高越容易再检一轮）
    agent_verify_enabled: bool = True     # 生成后做忠实度自检（第二道防幻觉闸门）
    # 预留：自检未通过时的重生成次数。当前实现是"标注式"处理（追加未找到依据的提示 + 返回
    # verdict），不自动重写答案 —— 因为重写会把已推给前端的流式内容作废；保留字段便于后续
    # 在非流式链路上开启"校验→重生成"闭环。
    agent_verify_retry: int = 0
    agent_rewrite_n: int = 2              # 每次反思生成几条新检索式
    # 强证据阈值：精排最高分 ≥ 它时提前收束（不再多检一轮）。
    # 判定器（LLM）天然偏严，纯靠它决定"要不要再检"会白烧 2~3 轮 token。
    agent_strong_score: float = 0.55
    # 分数下限保护系数：分数 ≥ 本批最高分 × 该系数的片段，即使判定器说"不相关"也保留。
    # 这是防"LLM 误杀高分证据"的安全网（实测确有用例被误杀并导致回答缺要点）。
    # 两个值分开：判定"资料充分"时可以收紧（放心裁剪），判定"不足"时要更宽松
    # （本就缺信息，再裁只会更缺）。
    agent_score_floor_ratio: float = 0.55
    agent_score_floor_ratio_loose: float = 0.25
    agent_context_max_chars: int = 6000   # 证据池进上下文的字符预算（超出按分数裁剪）
    agent_compress_min_question_chars: int = 30  # 问题多长才触发证据压缩（短问题不值得多调模型）

    # ---------- HuggingFace 镜像与模型缓存 ----------
    # 默认走国内镜像站，避免直连 huggingface.co 被墙（WinError 10051 等）。
    # 若你网络可直连且想用官方源，把它改为 https://huggingface.co。
    hf_endpoint: str = "https://hf-mirror.com"
    hf_home: str = ""  # 留空 = 使用 <data_dir>/hf（项目内，离线可用）
    # 默认纯离线模式：模型只从本地缓存加载（data/hf），绝不联网，避免被墙卡死。
    # 需要下载/更换新模型时，在 .env 设 HF_HUB_OFFLINE=false（需能连 hf_endpoint）。
    hf_hub_offline: bool = True

    # ---------- 派生路径（写 property 而非字段，避免依赖其它字段默认值）----------
    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def kb_json_path(self) -> Path:
        """知识库主数据（JSONL：文档 + 分块记录）。"""
        return self.data_dir / "kb.jsonl"

    @property
    def faiss_index_path(self) -> Path:
        """FAISS 向量索引持久化文件。"""
        return self.data_dir / "vectors.index"

    @property
    def sessions_path(self) -> Path:
        """会话历史持久化文件（演示用 JSONL）。"""
        return self.data_dir / "sessions.jsonl"

    @property
    def stats_path(self) -> Path:
        """Token 用量与成本统计（JSONL 追加）。"""
        return self.data_dir / "usage_stats.jsonl"

    @property
    def qdrant_local_path(self) -> Path:
        """Qdrant 本地模式目录（未配置 qdrant_path 时落在 data/qdrant）。"""
        return Path(self.qdrant_path) if self.qdrant_path else (self.data_dir / "qdrant")

    @property
    def llm_task_routes(self) -> dict[str, str]:
        """解析 'rewrite:small,answer:default' → {task: tier}。"""
        routes: dict[str, str] = {}
        for item in self.llm_task_routes_raw.split(","):
            if ":" in item:
                task, tier = item.split(":", 1)
                routes[task.strip()] = tier.strip()
        return routes

    # @property 由 pydantic 的 computed field 机制暴露（只读，不参与环境变量映射）
    @property
    def allowed_extension_set(self) -> set[str]:
        """把逗号分隔的字符串解析成集合，供上传校验使用（大小写不敏感）。"""
        return {s.strip().lower() for s in self.allowed_extensions.split(",") if s.strip()}

    @property
    def llm_ready(self) -> bool:
        """是否具备调用真实 LLM 的条件（有 key 且不是占位符）。"""
        key = (self.llm_api_key or "").strip()
        return bool(key) and "请填入" not in key

    def ensure_dirs(self) -> None:
        """启动时确保数据目录存在（幂等）。"""
        for p in (self.upload_dir, self.data_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """模块级单例：所有地方 import 后调用 get_settings() 拿到同一份配置。

    知识点：lru_cache 是 Python 里最轻量的“单例”实现方式；
    测试时可调用 get_settings.cache_clear() 重新加载。
    """
    return Settings()
