"""AI 中台治理接口：Token 用量、成本与模型路由可视化。

对应 JD「AI 中台组件开发，包括模型路由、Token 统计等基础治理功能」：
    - GET /api/stats/summary  累计用量、按模型/按任务聚合、估算成本
    - GET /api/stats/recent   最近若干次调用明细（排查“谁在烧 token”）
    - GET /api/stats/routes   当前模型路由表（哪个任务走哪个模型）
    - DELETE /api/stats       清空统计（仅开发期使用）
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _engine(request: Request):
    return request.app.state.engine


@router.get("/summary")
async def summary(request: Request):
    engine = _engine(request)
    data = engine.stats.summary()
    data["vector_backend"] = engine.settings.vector_backend
    return data


@router.get("/recent")
async def recent(request: Request, limit: int = Query(default=20, ge=1, le=200)):
    return {"items": _engine(request).stats.recent(limit)}


@router.get("/routes")
async def routes(request: Request):
    """模型路由表：任务 → 模型档位（面试可直接展示“按任务选模型”）。"""
    return _engine(request).router.describe()


@router.delete("")
async def reset(request: Request):
    """清空内存聚合（JSONL 历史保留，便于审计）。"""
    _engine(request).stats.reset()
    return {"ok": True, "note": "内存统计已清空；data/usage_stats.jsonl 历史仍保留"}
