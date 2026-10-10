"""Agentic RAG 的状态与结构化输出模型。

为什么要把"状态"显式建模（面试要点）：
    朴素 RAG 是一条写死的流水线（函数调用链），中间结果只存在于局部变量里；
    Agent 必须在**多轮自主决策**中带着状态往前走，所以要把
    「计划 / 已执行的步骤 / 证据 / 反思结论」都变成一等公民：
      1. 可观测：每一步都能作为事件推给前端（推理轨迹）；
      2. 可测试：状态是纯数据，单测可以只喂状态、断言决策；
      3. 可评测：检索准确率、幻觉率都从状态里取证据，而不是重新跑一遍检索。

分层：
    - 领域数据（GradedChunk/EvidenceItem）用 dataclass：轻、好构造；
    - 面向 LLM 的结构化输出（Plan/Grade/Judge）用 Pydantic：带校验与默认值，
      解析失败即视为"该节点失败"，触发保守降级（这是 Agent 稳定性的关键）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
# --------------------------------------------------------------- 领域数据
TaskType = Literal["qa", "decision", "stats", "chitchat"]


@dataclass
class GradedChunk:
    """一条候选证据 + 相关性判定结果。

    检索层与生成层之间的"质检记录"：只有 relevant=True 的证据才允许进入答案，
    这是幻觉率下降的**第一道闸门**（检索后自评），对应 CRAG 论文的思路。
    """

    chunk_id: str
    doc_id: str
    doc_title: str
    page: int | None
    text: str
    score: float = 0.0
    stage: str = "hybrid"
    relevant: bool = True
    reason: str = ""
    compressed: str = ""

    @property
    def body(self) -> str:
        """给生成用的正文：压缩过就用压缩版，否则用原文。"""
        return self.compressed or self.text

    def to_evidence(self, cite_index: int) -> dict:
        """转成对外返回的证据项（含引用编号，与回答里的 [n] 对齐）。"""
        return {
            "cite_index": cite_index,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "page": self.page,
            "score": round(float(self.score), 4),
            "stage": self.stage,
            "relevant": self.relevant,
            "reason": self.reason,
            "text": self.body,
            "snippet": (self.body[:200] + "…") if len(self.body) > 200 else self.body,
        }


@dataclass
class AgentStep:
    """一步动作记录：Agent 的"飞行记录仪"，也是前端推理轨迹的数据源。"""

    index: int
    kind: Literal["plan", "act", "observe", "grade", "reflect", "verify", "answer", "error"]
    title: str
    detail: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    observation: dict = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "tool": self.tool,
            "args": self.args,
            "observation": self.observation,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class AgentState:
    """一次 Agent 运行的完整状态（纯数据，可序列化）。"""

    question: str
    session_id: str = ""
    history_text: str = ""

    # 计划
    task_type: TaskType = "qa"
    intent: str = ""
    plan_steps: list[str] = field(default_factory=list)
    max_retrieval_rounds: int = 3

    # 执行
    round: int = 0
    queries: list[str] = field(default_factory=list)      # 每一轮实际用的检索式
    evidence: list[GradedChunk] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)

    # 反思与校验
    reflections: list[str] = field(default_factory=list)
    answer: str = ""
    verdict: str = ""
    verify_reason: str = ""
    unsupported: list[str] = field(default_factory=list)
    grounded: float = 0.0
    memo: "DecisionMemo | None" = None

    # 计量
    llm_calls: list[dict] = field(default_factory=list)   # 每次 LLM 调用的用量（含 step 名）
    stop_reason: str = ""

    # ---- 便捷操作 ----
    def add_step(self, step: AgentStep) -> AgentStep:
        step.index = len(self.steps) + 1
        self.steps.append(step)
        return step

    def add_evidence(self, items: list[GradedChunk]) -> int:
        """去重合并证据（同一 chunk 只保留分数最高的一条）。"""
        seen = {e.chunk_id: i for i, e in enumerate(self.evidence)}
        added = 0
        for it in items:
            if it.chunk_id in seen:
                idx = seen[it.chunk_id]
                if it.score > self.evidence[idx].score:
                    self.evidence[idx] = it
            else:
                seen[it.chunk_id] = len(self.evidence)
                self.evidence.append(it)
                added += 1
        return added

    def relevant_evidence(self) -> list[GradedChunk]:
        return [e for e in self.evidence if e.relevant]

    def trace(self) -> list[dict]:
        return [s.to_dict() for s in self.steps]

    def usage_total(self) -> dict:
        pt = sum(c.get("prompt_tokens", 0) for c in self.llm_calls)
        ct = sum(c.get("completion_tokens", 0) for c in self.llm_calls)
        cost = sum(c.get("cost", 0.0) for c in self.llm_calls)
        return {
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            "cost": round(cost, 6),
            "llm_calls": len(self.llm_calls),
            "estimated": any(c.get("estimated") for c in self.llm_calls),
            "by_step": self._by_step(),
        }

    def _by_step(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for c in self.llm_calls:
            key = c.get("step", "unknown")
            item = out.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
            item["calls"] += 1
            item["prompt_tokens"] += c.get("prompt_tokens", 0)
            item["completion_tokens"] += c.get("completion_tokens", 0)
            item["cost"] = round(item["cost"] + c.get("cost", 0.0), 6)
        return out


# --------------------------------------------------------------- LLM 结构化输出
class Plan(BaseModel):
    """规划节点输出：先想清楚"这是什么问题、要几步、每步用什么工具"。"""

    task_type: TaskType = "qa"
    intent: str = Field(default="", description="一句话复述用户真实意图")
    steps: list[str] = Field(default_factory=list, description="2~4 步的自然语言计划")
    search_queries: list[str] = Field(default_factory=list, description="1~3 条互补的检索式")
    answer_style: str = Field(default="", description="回答风格/结构要求")


class GradeOutcome(BaseModel):
    """相关性判定输出：检索结果够不够回答这个问题。"""

    sufficient: bool = False
    confidence: float = 0.0
    missing: str = ""
    relevant_ids: list[str] = Field(default_factory=list, description="判定为相关的资料编号，如 ['1','3']")
    reason: str = ""


class VerifyOutcome(BaseModel):
    """忠实度自检输出：答案是否每一句都有资料依据。"""

    grounded: bool = False
    score: float = 0.0
    unsupported: list[str] = Field(default_factory=list)
    reason: str = ""


class DecisionMemo(BaseModel):
    """决策备忘录：让"决策类问题"的输出结构化（企业级决策系统的交付物）。"""

    conclusion: str = ""
    rationale: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """工具描述（OpenAI function calling 兼容）。"""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
