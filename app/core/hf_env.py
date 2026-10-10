"""HF 环境变量统一入口。

sentence-transformers / huggingface_hub 在真正加载模型时才读取
HF_ENDPOINT（镜像站）与 HF_HOME（缓存目录），所以必须在 import
模型库之前把这些环境变量准备好 —— 否则在国内网络会直连 huggingface.co
而报 WinError 10051 / MaxRetryError。

本项目默认：
  HF_ENDPOINT = 配置里的 hf_endpoint（默认 https://hf-mirror.com，可改官方源）
  HF_HOME    = <data_dir>/hf（模型缓存进项目 data/，可离线复用、可随项目带走）

尊重用户显式设置：用户已在环境变量/系统中设置时，setdefault 不覆盖。
"""
from __future__ import annotations

import os

from ..config import Settings


def apply(settings: Settings) -> None:
    if settings.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)  # 默认 https://hf-mirror.com
    if settings.hf_home:
        os.environ.setdefault("HF_HOME", settings.hf_home)
    else:
        os.environ.setdefault("HF_HOME", str(settings.data_dir / "hf"))
    # 默认纯离线：模型从本地缓存加载，杜绝联网校验被墙导致的长时间卡死。
    # .env 设 HF_HUB_OFFLINE=false（且能连 hf_endpoint）后即可在线下载新模型。
    offline = "1" if settings.hf_hub_offline else "0"
    os.environ["HF_HUB_OFFLINE"] = offline
    os.environ["TRANSFORMERS_OFFLINE"] = offline
    # Windows 无开发者模式时的 symlink 告警太吵，直接关掉
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
