"""LLM 客户端装配。

本项目所有 LLM 走 OpenAI 兼容协议（langchain-openai 的 ChatOpenAI），
因此 DeepSeek / 智谱 / 千问 / Kimi / SiliconFlow / Ollama(本地) 都能用，
只差 base_url、api_key、model 三个配置 —— 这也是把模型供应商
“抽象成配置而不是写死在代码里”的工程实践。
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from ..config import Settings


def create_chat_model(settings: Settings, model: str | None = None) -> ChatOpenAI:
    """构建对话模型。settings.llm_ready 为 False 时不应调用本函数。

    model 为空时用主模型；由 LLMRouter 按任务传入轻量模型名。
    stream_usage=True：让流式响应的最后一个 chunk 也带回 token 用量，
    这样 Token 统计在流式接口下依然准确（否则只能按字数估算）。
    """
    return ChatOpenAI(
        model=model or settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=90,
        streaming=True,     # 让底层 SDK 走流式通道（astream 才真正流式）
        stream_usage=True,  # 流式也返回 usage，用于 Token 统计
    )
