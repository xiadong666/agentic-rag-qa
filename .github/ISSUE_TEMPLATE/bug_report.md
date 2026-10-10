---
name: Bug 反馈
about: 报告一个可复现的问题（跑不通 / 结果不对 / 报错）
title: "[Bug] "
labels: bug
---

## 现象

<!-- 一句话说清楚：你做了什么，期望什么，实际发生了什么 -->

## 复现步骤

```powershell
# 1. 从干净环境开始（可选但强烈建议，能排除历史数据干扰）
#    注意：主数据在 data/，实验请用隔离目录，别把主库清掉
# 2.
```

## 实际输出 / 报错

```
粘贴完整报错（含 traceback 或接口返回体）
```

## 期望结果

<!-- 你认为正确的结果是什么，依据是什么（文档？常识？另一条链路？） -->

## 环境信息

请先跑这两条命令，把输出粘过来 —— 它能排除掉大部分"配置没生效 / 库是空的"类问题：

```powershell
.\.venv-rag\Scripts\python.exe scripts\check_env.py
.\.venv-rag\Scripts\python.exe scripts\check_syntax.py
```

| 项 | 值 |
| --- | --- |
| 操作系统 | <!-- Windows 11 / macOS 14 / Ubuntu 22.04 --> |
| Python 版本 | <!-- python -V --> |
| 安装方式 | <!-- venv / conda / Docker --> |
| 向量库后端 | <!-- faiss / qdrant --> |
| 是否开 Agent | <!-- AGENT_ENABLED=true/false --> |
| LLM 厂商与模型 | <!-- DeepSeek deepseek-chat / 其它 --> |

## 自查清单

- [ ] 我看过 README 的「常见问题」，并且**改完 `.env` 重启过服务**
- [ ] `scripts/check_env.py` 输出里没有"无法识别的配置项"
- [ ] 知识库不是空的（`check_env.py` 会显示文档/分块数）
- [ ] 我贴的日志里**没有**包含自己的 API Key
