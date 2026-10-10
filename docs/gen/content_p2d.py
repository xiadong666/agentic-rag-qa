"""Part 2d：Step 13 RAG 编排 / Step 14 前端 / Step 15 部署。"""
from __future__ import annotations

import style as S


def add(doc):
    step13(doc)


def step13(doc):
    S.h2(doc, "Step 13　RAG 编排层 engine.py（全项目最关键）")
    S.h3(doc, "13.1 它的职责")
    S.para(doc, "engine 把各 core 模块“串”成对外可用的方法：`ingest_file`（入库线）、"
                "`search`（检索线）、`answer / answer_stream`（问答线）。API 层只调用它，"
                "不碰任何细节 —— 于是你可以用 pytest 直接测 engine，不启动服务器。")
    S.h3(doc, "13.2 并发模型：to_thread + asyncio.Lock")
    S.code_file(doc, "app/core/engine.py", start=155, end=174)
    S.bullet(doc, "embedding/FAISS/BM25 都是**同步 CPU 密集**代码，直接跑会卡死事件循环 → "
                  "统一 `asyncio.to_thread(...)` 丢线程池；")
    S.bullet(doc, "但“入库 → 改索引”是**写操作**，检索是**读操作**，两者并发会读到中间状态 → "
                  "一把 `asyncio.Lock` 把“写 + 所有搜索”串行化，**用简单换正确**；")
    S.bullet(doc, "local embedder/reranker 内部再用 `threading.Lock` 保护模型推理（模型非线程安全）。")
    S.callout(doc, "idea", "面试聊并发是加分项：能说出“IO 走 async、CPU 走线程池、共享状态上锁”三层，"
                          "说明你有真实的服务端工程经验。")
    S.h3(doc, "13.3 入库管线")
    S.code_file(doc, "app/core/engine.py", start=88, end=133)
    S.bullet(doc, "顺序：解析 → 分块 → 向量化 → 写 JSONL → 写 FAISS → 增量更新 BM25 → 存盘；")
    S.bullet(doc, "**先写记录后写向量**、两边同序追加，是“下标对齐”成立的保证（回顾 Step 6）。")
    S.callout(doc, "warn", "入库中途失败要保证一致性：本项目先 `async with self._lock` 再整段执行，"
                          "异常会回滚到锁外（演示级）。生产可把“记录+向量”放进同一事务/补偿删除。")

    S.h2(doc, "Step 14　前端：无框架也能做完整的交互")
    S.h3(doc, "14.1 结构")
    S.code(doc, """index.html  三栏布局：知识库(左) / 对话(中) / 引用来源(右)
style.css   样式（浅色、卡片、消息气泡）
app.js      全部逻辑：上传、文档列表、SSE 流式渲染、来源卡片""")
    S.h3(doc, "14.2 关键点")
    S.bullet(doc, "**fetch + ReadableStream** 读 `/api/chat/stream`：按 `\\n\\n` 切帧、`data:` 前缀解 JSON，"
                  "token 到达即追加渲染 —— 首字延迟≈模型首 token 延迟，体验远好于转圈等待；")
    S.bullet(doc, "**meta 事件先于正文**到达 → 用户还没看完字，右侧“引用来源”已就位（感知性能设计）；")
    S.bullet(doc, "回答里的 `[n]` 用正则包一层可点击样式，与 `sources[].cite_index` 对应。")
    S.callout(doc, "tip", "故意不用 React/Vue，是想让你看懂**浏览器原生能力**；"
                         "上生产换框架时，接口协议（SSE 事件类型）完全不用动。")
    S.callout(doc, "warn", "前端渲染用 `innerHTML` 前必须转义（`esc()`）。直接把模型输出拼进 HTML "
                          "会有 XSS 风险 —— 面试若被问安全，这是现成答案。")

    S.h2(doc, "Step 15　部署成 Web 服务")
    S.h3(doc, "15.1 本地 / 服务器直跑")
    S.code(doc, """# 开发（热重载，单进程）
.venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000

# 生产（多进程：4 worker × 8 线程；注意每进程会各自加载一遍模型）
.venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4""")
    S.callout(doc, "warn", "多 worker 时每个进程独立持有一份模型 + 内存索引 —— 内存按进程翻倍。"
                          "小内存机器要么单进程，要么把索引/状态外置（向量库 + Redis），这正是进阶方向。")
    S.h3(doc, "15.2 Docker")
    S.code_file(doc, "Dockerfile", start=1, end=20)
    S.bullet(doc, "`python:3.12-slim` 打底，torch 用 CPU 源安装避免拖入几个 GB 的 CUDA 依赖；")
    S.bullet(doc, "`DATA_DIR`/`HF_HOME` 指向 `/app/data`，用 **volume 持久化**（知识库、向量索引、模型缓存都不丢）。")
    S.code(doc, """docker compose up -d --build     # 前台 http://127.0.0.1:8000""")
    S.h3(doc, "15.3 上线 checklist（简历/面试常聊）")
    S.table(doc,
            ["项", "做法"],
            [
                ["密钥", "只走环境变量/密钥管理服务；.env 不入库、容器不写死"],
                ["CORS", "生产收窄为真实前端域名（演示是 *）"],
                ["限流", "登录/限流中间件，防刷接口烧 token（slowapi 等）"],
                ["首字延迟", "模型预热（启动时 warmup 一次），SSE 关代理缓冲（已加 X-Accel-Buffering）"],
                ["可观测", "结构化日志 + /health + 请求耗时指标；RAG 可接 LangSmith 追踪"],
                ["模型与索引", "embedding 维度/模型变更 = 全量重建索引；模型版本要记录在知识库元数据里"],
                ["安全", "上传文件类型魔数校验、大小限制、输出转义、回环/内网部署防滥用"],
            ],
            widths=[3.2, 12.2])
    S.callout(doc, "idea", "部署篇的价值不在“敲几条命令”，而在你**说得出每一层的风险**："
                          "多进程内存翻倍、密钥管理、模型预热、代理缓冲 —— 这些才是面试官想听的话。")
