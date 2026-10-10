"""模型路由（AI 中台能力之一）。

要解决的问题：**不是所有任务都值得用最贵的模型。**
    改写问题、分类意图、压缩上下文这类任务用轻量模型即可；
    只有最终答案生成才需要主模型（更强的推理与表达）。

设计（面试可讲的三点）：
1. **按任务路由**：配置 `LLM_TASK_ROUTES=rewrite:small,answer:default`，
   业务代码只说“我要做 rewrite”，不关心具体模型；
2. **模型实例缓存**：同一模型只创建一次（LangChain 客户端可复用，省连接与初始化开销）；
3. **可降级**：轻量模型没配置时自动回落到主模型，而不是报错。
"""
from __future__ import annotations

import logging

from ..config import Settings
from .llm import create_chat_model

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, object] = {}

    def model_name(self, task: str) -> str:
        """任务 → 模型名。支持三档：small（省钱）/ default（主模型）/ strong（最强）。

        档位未配置时**向上回落**而不是报错：
        strong 没配就用 default，small 没配也用 default —— 降级可用性优先。
        """
        tier = self.settings.llm_task_routes.get(task, "default")
        if tier == "small":
            return self.settings.llm_small_model or self.settings.llm_model
        if tier == "strong":
            return self.settings.llm_strong_model or self.settings.llm_model
        return self.settings.llm_model

    def get(self, task: str):
        """按任务取模型客户端；未配置 key 时返回 None（由上层给出友好提示）。"""
        if not self.settings.llm_ready:
            return None
        name = self.model_name(task)
        if name not in self._cache:
            self._cache[name] = create_chat_model(self.settings, model=name)
            logger.info("LLM 路由：任务 %s → 模型 %s", task, name)
        return self._cache[name]

    def describe(self) -> dict:
        """给 /health 或调试接口看的路由表。"""
        return {
            "default_model": self.settings.llm_model,
            "small_model": self.settings.llm_small_model or self.settings.llm_model,
            "strong_model": self.settings.llm_strong_model or self.settings.llm_model,
            "routes": self.settings.llm_task_routes,
            "cached_clients": list(self._cache),
        }
