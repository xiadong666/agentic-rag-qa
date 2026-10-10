"""接口数据模型（Pydantic v2）。

知识点：
1. 请求/响应模型统一由 Pydantic 定义 → FastAPI 自动完成：
   参数校验、类型转换、OpenAPI 文档生成、响应序列化。
2. field_validator / model_validator 用于自定义校验与后处理。
3. 加 "sources" 到响应里 = 把“引用来源”做成 API 一等公民，前端可直接渲染。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceRef(BaseModel):
    """一条被模型引用的来源片段（用于“引用来源”亮点）。"""

    chunk_id: str
    doc_id: str
    doc_title: str
    page: int | None = None
    score: float = 0.0
    snippet: str = ""
    cite_index: int = 0            # 对应回答文本里的 [n] 编号


class UploadResponse(BaseModel):
    doc_id: str
    title: str
    filename: str
    char_count: int
    chunk_count: int
    elapsed_ms: int

# 文档信息
class DocInfo(BaseModel):
    doc_id: str
    title: str
    filename: str
    char_count: int
    chunk_count: int
    uploaded_at: str


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class SearchHit(SourceRef):
    """检索命中片段 = 来源 + 相似度 + 出处。"""

    retriever: Literal["dense", "sparse", "hybrid", "rerank"] = "hybrid"


class SearchResponse(BaseModel):
    question: str
    hits: list[SearchHit] = []


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    use_history: bool = True
    # 是否用 Agentic RAG 链路（None = 跟随后端 AGENT_ENABLED 配置）。
    # 保留这个开关是为了能对同一问题做"朴素 RAG vs Agentic RAG"的在线对比。
    agent: bool | None = None

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip()


class AnswerResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[SourceRef] = []
    used_history: bool = False
    rewritten_question: str | None = None
    elapsed_ms: int = 0
    model: str | None = None          # 模型路由实际选中的模型
    usage: dict | None = None         # Token 用量与成本（prompt/completion/total/cost/estimated）
    agent: dict | None = None         # Agentic RAG 专属：计划/轨迹/证据/判定/校验（朴素链路为 None）


# --------------------------------------------------------------- Agentic RAG
class AgentRequest(BaseModel):
    """Agent 问答请求。字段与 ChatRequest 对齐，额外暴露 Agent 的两个旋钮。"""

    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    use_history: bool = True
    max_rounds: int | None = Field(default=None, ge=1, le=5, description="覆盖最大检索轮数（1~5）")

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip()


class AgentStepInfo(BaseModel):
    """一步推理轨迹（前端时间线渲染用）。"""

    index: int = 0
    kind: str = ""
    title: str = ""
    detail: str = ""
    tool: str = ""
    args: dict = {}
    observation: dict = {}
    elapsed_ms: int = 0


class AgentEvidence(BaseModel):
    """一条进入答案的证据（与回答里的 [n] 严格对齐）。"""

    cite_index: int = 0
    chunk_id: str = ""
    doc_id: str = ""
    doc_title: str = ""
    page: int | None = None
    score: float = 0.0
    stage: str = ""
    relevant: bool = True
    reason: str = ""
    text: str = ""
    snippet: str = ""


class AgentInfo(BaseModel):
    """Agent 运行摘要：讲清楚"它想了什么、走了几步、为什么停"。"""

    task_type: Literal["qa", "decision", "stats", "chitchat"] = "qa"
    intent: str = ""
    plan: list[str] = []
    queries: list[str] = []
    rounds: int = 0
    stop_reason: str = ""
    verdict: str = ""
    verify_reason: str = ""
    grounded_score: float = 0.0
    unsupported: list[str] = []
    reflections: list[str] = []
    evidence: list[AgentEvidence] = []
    memo: dict | None = None
    steps: list[AgentStepInfo] = []


class AgentResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[SourceRef] = []
    used_history: bool = False
    elapsed_ms: int = 0
    model: str | None = None
    usage: dict | None = None
    agent: AgentInfo | None = None


class AgentDebugResponse(BaseModel):
    """不花钱看链路：规划 + 检索 + 判定结果（不调用生成）。"""

    session_id: str
    question: str
    task_type: str = "qa"
    intent: str = ""
    plan: list[str] = []
    queries: list[str] = []
    sufficient: bool = False
    confidence: float = 0.0
    missing: str = ""
    evidence: list[AgentEvidence] = []
    steps: list[AgentStepInfo] = []
    tools: list[dict] = []


class PromptDebugResponse(BaseModel):
    """调试接口：把将要发给 LLM 的消息原样返回，方便不花钱也能看链路。"""

    session_id: str
    rewritten_question: str | None
    messages: list[dict]
    sources: list[SourceRef] = []


class Message(BaseModel):
    """通用消息（用于 SSE 流式协议的 JSON 载荷）。"""

    type: Literal["token", "sources", "error", "done"] = "token"
    data: dict = {}
