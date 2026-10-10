"""问答 / 检索 / 调试 接口。

知识点：
1. /api/chat/stream 用 StreamingResponse + text/event-stream 推送 SSE：
   - 前端用 fetch + ReadableStream 边收边渲染，体验最好；
   - 每个事件一行 JSON（data: {...}\n\n），与语言无关、便于扩展。
2. 业务异常（未配 key、空库）映射成清晰的 HTTP 状态码/错误事件，
   而不是让 500 裸奔 —— 可观测性从接口层就开始。
3. /api/debug/prompt 是“教学彩蛋”：不发任何生成请求，
   就能看到“检索+重排之后到底给 LLM 发了什么” —— 排查 RAG 问题的第一站。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..core.agent_state import AgentState, AgentStep
from ..core.agent_tools import build_registry
from ..schemas import (
    AgentDebugResponse,
    AgentRequest,
    AgentResponse,
    AnswerResponse,
    ChatRequest,
    PromptDebugResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)

router = APIRouter(prefix="/api", tags=["chat"])


def _engine(request):
    return request.app.state.engine


def _use_agent(engine, body) -> bool:
    """决定这次请求走哪条链路：请求级开关 > 全局配置。

    为什么要留这个开关（面试可讲）：Agentic RAG 更准但更慢更贵；
    真实系统里需要按场景路由（简单问答走朴素链路、复杂决策走 Agent），
    也需要能对同一问题做灰度与 A/B —— 所以链路选择必须是显式参数，而不是写死。
    """
    if getattr(body, "agent", None) is not None:
        return bool(body.agent)
    return bool(engine.settings.agent_enabled)


def _sse(obj: dict) -> str:
    """把事件对象编码成一行 SSE。ensure_ascii=False 保留中文可读性。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@router.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """只检索不生成 —— 调试混合检索/重排效果用。"""
    hits = await _engine(request).search(body.question, body.top_k)
    return SearchResponse(
        question=body.question,
        hits=[SearchHit(**h.model_dump()) for h in hits],
    )


@router.post("/chat", response_model=AnswerResponse)
async def chat(request: Request, body: ChatRequest) -> AnswerResponse:
    """统一问答入口：默认走 Agentic RAG，可用 agent=false 回落到朴素 RAG。"""
    engine = _engine(request)
    try:
        if _use_agent(engine, body):
            result = await engine.agent_answer(
                body.question, body.session_id, body.use_history
            )
        else:
            result = await engine.answer(
                body.question, body.session_id, body.use_history
            )
    except RuntimeError as e:
        # 未配置 LLM key 等“业务性”错误
        raise HTTPException(status_code=503, detail=str(e)) from e
    return AnswerResponse(**result)


@router.post("/chat/stream")
async def chat_stream(request: Request, body: ChatRequest):
    engine = _engine(request)
    use_agent = _use_agent(engine, body)

    async def event_stream():
        # 先做“准备阶段”（检索/重排可能在 meta 事件后还需要时间，
        # 但我们把 meta 前置：前端能立刻展示来源，用户感知更快）
        try:
            if use_agent:
                # Agent 链路事件更丰富：plan → tool/grade/reflect → token → verify → final
                async for event in engine.agent_answer_stream(
                    body.question, body.session_id, body.use_history
                ):
                    yield _sse(event)
            else:
                async for event in engine.answer_stream(
                    body.question, body.session_id, body.use_history
                ):
                    yield _sse(event)
        except Exception as e:  # 生成阶段任何异常 → 错误事件（不要断流无提示）
            yield _sse({"type": "error", "data": {"message": str(e)}})
        finally:
            yield _sse({"type": "done", "data": {"closed": True}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 关掉 nginx 等代理的缓冲（部署要点）
        },
    )


# ============================================================ Agentic RAG 接口
@router.post("/agent/query", response_model=AgentResponse, tags=["agent"])
async def agent_query(request: Request, body: AgentRequest) -> AgentResponse:
    """Agentic RAG 问答（非流式）：返回答案 + 来源 + 完整推理轨迹 + 逐节点用量。"""
    engine = _engine(request)
    try:
        result = await engine.agent_answer(
            body.question, body.session_id, body.use_history, max_rounds=body.max_rounds
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return AgentResponse(**result)


@router.post("/agent/stream", tags=["agent"])
async def agent_stream(request: Request, body: AgentRequest):
    """Agentic RAG 问答（SSE 流式）：过程事件 + 逐 token 输出。

    事件类型：plan / tool / grade / reflect / answer_start / token / verify / final / error。
    """
    engine = _engine(request)

    async def event_stream():
        try:
            async for event in engine.agent_answer_stream(
                body.question, body.session_id, body.use_history, max_rounds=body.max_rounds
            ):
                yield _sse(event)
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "data": {"message": str(e)}})
        finally:
            yield _sse({"type": "done", "data": {"closed": True}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/debug", response_model=AgentDebugResponse, tags=["agent"])
async def agent_debug(request: Request, body: AgentRequest) -> AgentDebugResponse:
    """Agent 调试接口：只跑「规划 → 检索 → 判定/反思」，**不生成答案**。

    排查 Agent 问题的正确顺序（和朴素 RAG 一样，第一站永远不是生成）：
        ① 计划对不对（检索式是否覆盖了问题要的信息）
        ② 检索命中了什么（top 分数、来源文档）
        ③ 判定器为什么说不够（missing 字段直接告诉你缺什么）
    把这三步看一遍，90% 的“Agent 答不好”在花钱生成之前就能定位。
    """
    engine = _engine(request)
    hist = (
        engine.memory.format_history(body.session_id or "", engine.settings.history_max_turns)
        if body.use_history
        else ""
    )
    state = AgentState(question=body.question, session_id=body.session_id or "(new)",
                       history_text=hist)
    registry = build_registry(engine, state)
    plan = await engine.agent_nodes.plan(state, body.question, registry.names())
    state.task_type = plan.task_type
    state.intent = plan.intent or body.question
    state.plan_steps = plan.steps
    state.queries = [q.strip() for q in plan.search_queries if q and q.strip()] or [body.question]

    if state.task_type == "stats":
        obs = await registry.call("kb_stats")
        state.add_step(AgentStep(
            index=0, kind="act", title="读取知识库统计", tool="kb_stats", observation=obs))
        return AgentDebugResponse(
            session_id=state.session_id, question=body.question, task_type=state.task_type,
            intent=state.intent, plan=state.plan_steps, queries=state.queries,
            sufficient=True, confidence=1.0, evidence=[], steps=state.trace(),
            tools=registry.describe(),
        )

    if state.task_type != "chitchat":
        for q in state.queries[:2]:
            obs = await registry.call("knowledge_search", query=q)
            state.add_step(AgentStep(
                index=0, kind="act", title=f"检索：{q}", tool="knowledge_search",
                args={"query": q}, observation=obs))
        grade = await engine.agent_nodes.grade(state, body.question, state.evidence)
        state.add_step(AgentStep(
            index=0, kind="grade", title=f"判定：{'资料充分' if grade.sufficient else '资料不足'}",
            detail=grade.reason,
            observation={"sufficient": grade.sufficient, "confidence": grade.confidence,
                         "missing": grade.missing, "relevant_ids": grade.relevant_ids}))
        return AgentDebugResponse(
            session_id=state.session_id, question=body.question, task_type=state.task_type,
            intent=state.intent, plan=state.plan_steps, queries=state.queries,
            sufficient=grade.sufficient, confidence=grade.confidence, missing=grade.missing,
            evidence=[e.to_evidence(i) for i, e in enumerate(state.evidence, start=1)],
            steps=state.trace(), tools=registry.describe(),
        )

    return AgentDebugResponse(
        session_id=state.session_id, question=body.question, task_type=state.task_type,
        intent=state.intent, plan=state.plan_steps, queries=state.queries,
        sufficient=False, confidence=0.0, missing="与知识库无关的闲聊，不检索",
        steps=state.trace(), tools=registry.describe(),
    )


@router.get("/agent/tools", tags=["agent"])
async def agent_tools(request: Request):
    """列出 Agent 可用的工具（写给面试官/前端看的"能力清单"）。"""
    engine = _engine(request)
    state = AgentState(question="(tools)")
    return {
        "tools": build_registry(engine, state).describe(),
        "routes": engine.router.describe(),
        "settings": {
            "agent_enabled": engine.settings.agent_enabled,
            "max_retrieval_rounds": engine.settings.agent_max_retrieval_rounds,
            "verify_enabled": engine.settings.agent_verify_enabled,
            "context_max_chars": engine.settings.agent_context_max_chars,
        },
    }


@router.post("/debug/prompt", response_model=PromptDebugResponse)
async def debug_prompt(request: Request, body: ChatRequest) -> PromptDebugResponse:
    """把将发给 LLM 的完整消息（system+user）原样返回，不调用生成接口。"""
    engine = _engine(request)
    history_text = (
        engine.memory.format_history(
            body.session_id or "", engine.settings.history_max_turns
        )
        if body.use_history
        else ""
    )
    # 调试彩蛋：agent=false 时顺带展示"不做问题改写"的检索上下文，
    # 方便对比"改写前/改写后"到底影响了哪些召回结果。
    messages, sources, rewritten = await engine._build_answer_messages(
        body.question, history_text
    )
    return PromptDebugResponse(
        session_id=body.session_id or "(new)",
        rewritten_question=rewritten,
        messages=messages,
        sources=sources,
    )
