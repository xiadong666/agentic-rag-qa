"""FastAPI 应用入口：app 工厂 + 生命周期 + 静态页。

知识点：
1. lifespan 上下文：启动时初始化全局单例（engine）并重建索引；
   关闭时做清理 —— 比模块级全局变量更可控。
2. CORS：前后端分离/本地调试需要；上线时收紧为具体域名（见部署篇）。
3. 静态页 + / 路由：单进程同时提供 API 与网页，演示最省事。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import chat as chat_api
from .api import documents as documents_api
from .api import stats as stats_api
from .config import get_settings
from .core.agent_state import AgentState
from .core.agent_tools import build_registry
from .core.engine import RAGEngine

STATIC_DIR = Path(__file__).resolve().parent / "static"
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动 ----
    settings.ensure_dirs()
    # 统一在进程里准备好 HF 镜像 + 模型缓存目录（必须早于模型加载）
    from .core.hf_env import apply as apply_hf_env

    apply_hf_env(settings)
    engine = RAGEngine(settings)
    await engine.initialize()   # 加载/重建向量索引
    app.state.engine = engine
    logging.getLogger("uvicorn.error").info(
        "RAG engine ready: docs=%d chunks=%d rerank=%s",
        len(engine.store.docs),
        engine.store.total_chunks(),
        "on" if engine.reranker is not None else "off",
    )
    yield
    # ---- 关闭（如需释放模型显存可在此清理）----
    app.state.engine = None


def create_app() -> FastAPI:
    application = FastAPI(
        title="RAG 知识库问答系统",
        version="1.0.0",
        description="文档上传→解析→分块→向量化→混合检索→重排→生成回答（含引用与多轮历史）",
        lifespan=lifespan,
    )
    # CORS：演示放开；上线收紧（部署篇有说明）
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(documents_api.router)
    application.include_router(chat_api.router)
    application.include_router(stats_api.router)   # AI 中台：Token 统计 / 成本 / 路由
    # 静态资源与首页
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health", tags=["ops"])
    async def health():
        engine = application.state.engine
        return {
            "status": "ok",
            "llm_ready": engine.settings.llm_ready if engine else False,
            "docs": len(engine.store.docs) if engine else 0,
            "chunks": engine.store.total_chunks() if engine else 0,
            "vector_backend": engine.settings.vector_backend if engine else None,
            "llm_routes": engine.router.describe() if engine else None,
            # Agentic RAG 能力自述：前端据此决定开关默认值，验收脚本据此断言
            "agent": {
                "enabled": engine.settings.agent_enabled if engine else False,
                "max_retrieval_rounds": engine.settings.agent_max_retrieval_rounds if engine else 0,
                "verify_enabled": engine.settings.agent_verify_enabled if engine else False,
                "tools": [t["name"] for t in build_registry(
                    engine, AgentState(question="(health)")).describe()] if engine else [],
            },
        }

    return application


app = create_app()
