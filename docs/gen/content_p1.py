"""Part 0/1：使用说明、学习地图、项目总览。"""
from __future__ import annotations

import style as S


def add(doc):
    add_part0(doc)
    add_part1(doc)


def add_part0(doc):
    S.h1(doc, "使用说明：这份文档怎么帮你", page_break_before=False)
    S.para(doc, "你好！这份文档配套一个**完整可运行**的 RAG 知识库问答系统项目"
                "（FastAPI + LangChain），围绕你要求的完整链路展开："
                "文档上传 → 解析 → 向量化 → 检索 → 生成回答，并加入四个加分亮点："
                "**混合检索、重排序、引用来源、对话历史**，最后把它**部署成 Web 服务**。")
    S.para(doc, "它的用法不只是“读”：每一章都对应项目里的真实代码文件，建议"
                "边看文档边打开代码对照。项目在你机器上跑起来之后，把每一步亲手点一遍，"
                "再回来读“代码知识点”与“避坑清单”，最后用“面试与简历”部分自测。")
    S.h2(doc, "0.1 学习地图：阶段 → 产出 → 对应代码")
    S.table(doc,
            ["阶段", "你做完后能说出/做到", "对应代码"],
            [
                ["① 项目骨架与配置", "12-Factor 配置、目录分层、为什么这样组织", "app/config.py、app/main.py"],
                ["② 上传与解析", "UploadFile 流式上传、多格式解析、编码坑", "app/api/documents.py、app/core/parsing.py"],
                ["③ 分块", "为什么要分块、重叠的作用、中文分隔符", "app/core/chunking.py"],
                ["④ 向量化", "bi-encoder、bge、归一化、本地 vs API", "app/core/embeddings.py"],
                ["⑤ 向量库 + 稠密检索", "FAISS 内积索引、向量库与元数据库分工", "app/core/vector_store.py、store.py"],
                ["⑥ 稀疏检索 BM25", "BM25 公式、中文分词、为什么仍需关键词", "app/core/bm25.py"],
                ["⑦ 混合检索 + RRF", "两路召回、RRF 融合原理与直觉", "app/core/retrieval.py"],
                ["⑧ 重排序", "bi-encoder vs cross-encoder、召回-精排两段式", "app/core/rerank.py"],
                ["⑨ 引用来源", "出处贯穿全链路、提示词约束、结构化返回", "app/core/engine.py、prompts.py"],
                ["⑩ 对话历史", "会话管理、问题改写、窗口取舍", "app/core/memory.py"],
                ["⑪ 生成回答与流式", "LCEL、ChatPromptTemplate | llm | parser、SSE", "app/core/engine.py、app/api/chat.py"],
                ["⑫ 前端", "无框架原生交互、边收边渲染", "app/static/*"],
                ["⑬ 部署 Web 服务", "uvicorn / Docker / Compose、生产注意", "Dockerfile、docker-compose.yml"],
            ],
            widths=[3.6, 6.2, 5.6])
    S.h2(doc, "0.2 读文档的建议节奏")
    S.bullet(doc, "第一遍（0.5 天）：只读「分步实现详解」每步开头“做什么、为什么”，"
                  "把项目跑起来，界面点一遍。")
    S.bullet(doc, "第二遍（1~2 天）：对照代码精读每步的知识点与代码片段，动手改参数"
                  "（chunk_size、top_k、RRF 常数）观察检索结果变化。")
    S.bullet(doc, "第三遍（面试前）：只看「代码知识点总结」「避坑清单」「面试 20 问」快速回顾。")
    S.callout(doc, "tip", "文档里的代码块与项目源码一一对应；路径以项目根目录 "
                         "`rag-qa-system/` 为基准。")


def add_part1(doc):
    S.h1(doc, "第一部分 项目总览")
    S.h2(doc, "1.1 为什么这个项目能帮你拿到 AI 应用开发实习")
    S.para(doc, "大四找“AI 应用开发”类实习，面试官最在意三件事：你**真的动手写过完整链路**、"
                "你知道**每个环节为什么这么设计**、你能**讲清楚工程上的取舍**。这个项目恰好覆盖：")
    S.table(doc,
            ["面试官想看的能力", "本项目给出的证据"],
            [
                ["会用 LangChain 而非只会调 API", "LCEL 链式组合、ChatPromptTemplate、ChatOpenAI、text-splitters 全部真实使用"],
                ["有工程素养", "配置中心化、分层架构、异常处理、日志、类型注解、目录规范"],
                ["懂 RAG 原理而非背概念", "BM25 是自己实现的；RRF、cross-encoder 都讲了原理并落地"],
                ["有产品 sense", "引用来源让回答可验证；流式输出提升体验；三栏 Web UI"],
                ["能部署", "uvicorn + Docker + docker-compose + 环境变量化"],
                ["有持续学习意愿", "文档含进阶路线：RAGAS 评估、LangGraph、语义缓存等"],
            ],
            widths=[5.6, 9.8])
    S.h2(doc, "1.2 总体架构与数据流")
    S.para(doc, "系统分两条线：**离线入库线**（文档 → 分块 → 向量化 → 索引）与"
                "**在线问答线**（问题 → 检索 → 融合 → 重排 → 拼上下文 → 生成）。")
    S.code(doc, """                ┌────────────────────────────────────────────────┐
 上传PDF/docx/md ─▶ 解析(按页) ─▶ 分块(重叠) ─▶ Embedding ──▶ FAISS索引   离线：知识沉淀
                │                    │             │               ▲
                │                    ▼             ▼               │
                │              JSONL 原文+出处（下标与向量一一对齐）  │
                └────────────────────────────────────────────────┘
                                     │
 用户提问 ──▶ (LLM改写为独立问题?) ──┤
                                     ├─▶ 稠密检索(向量)   ┐
                                     ├─▶ 稀疏检索(BM25)   ┴─▶ RRF融合 ─▶ cross-encoder重排
                                     ▼
                   拼上下文(编号[1][2]…+出处页码) ─▶ DeepSeek ─▶ 带引用回答 + sources 元数据""")
    S.h2(doc, "1.3 技术选型与理由")
    S.table(doc,
            ["组件", "本项目选型", "为什么", "备选（面试可聊）"],
            [
                ["Web 框架", "FastAPI", "类型提示自动校验与文档；原生 async；社区大", "Flask/Django/Spring"],
                ["LLM 封装", "LangChain 1.2 + langchain-openai", "LCEL 好讲、与 1.x 官方文档对齐；OpenAI 兼容协议通吃各厂商", "LlamaIndex"],
                ["对话模型", "DeepSeek deepseek-chat", "便宜、国内直连、OpenAI 兼容", "Kimi/千问/智谱/Ollama"],
                ["Embedding", "本地 bge-small-zh-v1.5", "免费、可离线、中文好；演示稳定", "bge-m3/千问/硅基流动 API"],
                ["向量库", "FAISS（进程内）", "教科书级、无服务、适合讲原理", "Chroma/Qdrant/Milvus"],
                ["稀疏检索", "自实现 BM25 + jieba", "零依赖且能讲清公式", "Elasticsearch/OpenSearch"],
                ["重排", "本地 cross-encoder（bce-reranker-base）", "中文场景效果好、体积适中", "Cohere/SiliconFlow rerank API"],
                ["存储", "JSONL 双文件 + FAISS 索引", "可读、可 diff、结构透明", "SQLite/PostgreSQL+pgvector"],
                ["部署", "uvicorn + Docker", "本地开发简单、生产可迁移", "Nginx + gunicorn、K8s"],
            ],
            widths=[2.6, 4.0, 5.4, 3.6])
    S.h2(doc, "1.4 目录结构（每个文件一句话职责）")
    S.code(doc, """rag-qa-system/
├─ app/
│  ├─ main.py            # FastAPI 入口：lifespan 生命周期、CORS、静态页、健康检查
│  ├─ config.py          # pydantic-settings 配置中心（.env → 类型安全配置对象）
│  ├─ schemas.py         # Pydantic 请求/响应模型（自动校验 + OpenAPI）
│  ├─ api/               # 路由层（薄）：只做参数/HTTP ↔ 业务 的转换
│  │  ├─ documents.py    # 上传/列表/删除 文档
│  │  └─ chat.py         # /search /chat /chat/stream /debug/prompt
│  ├─ core/              # 业务核心（与 FastAPI 无关 → 可独立单测）
│  │  ├─ parsing.py      # PDF/docx/txt/md 解析（按页保留页码）
│  │  ├─ chunking.py     # 中文友好递归分块（重叠、按页）
│  │  ├─ embeddings.py   # Embedder 抽象 + 本地bge / OpenAI兼容 双实现
│  │  ├─ vector_store.py # FAISS IndexFlatIP 封装（内积=余弦）
│  │  ├─ store.py        # KnowledgeStore：JSONL 持久层（doc + chunk 记录）
│  │  ├─ bm25.py         # BM25 稀疏检索（自实现，含 jieba 分词）
│  │  ├─ retrieval.py    # HybridRetriever + RRF 融合
│  │  ├─ rerank.py       # cross-encoder 精排（懒加载）
│  │  ├─ memory.py       # 会话表 + 多轮历史（LRU、JSONL 持久化）
│  │  ├─ prompts.py      # 提示词集中管理（回答/改写）
│  │  ├─ llm.py          # ChatOpenAI 装配
│  │  └─ engine.py       # RAGEngine：全链路编排（最关键）
│  └─ static/            # 原生三栏 Web UI（index.html / style.css / app.js）
├─ sample_docs/          # 3 篇内置示例文档（离线演示用）
├─ scripts/              # install.ps1/sh、seed_demo.py（灌示例数据）
├─ requirements.txt      # 依赖（务必保持 ASCII，Windows pip 兼容）
├─ .env.example          # 配置模板（复制为 .env 使用）
├─ Dockerfile / docker-compose.yml
└─ docs/                 # 本教程（Word）与生成器""")
    S.h2(doc, "1.5 运行三步走")
    S.callout(doc, "note", "以下在项目根目录 `rag-qa-system/` 执行。Windows 用 PowerShell，"
                          "macOS/Linux 用 bash（scripts/install.sh）。")
    S.code(doc, """# ① 准备 .env（填入你的 LLM API Key，默认接 DeepSeek）
cp .env.example .env

# ② 安装依赖（自动建 .venv、装 CPU 版 torch、装其余依赖）
powershell -ExecutionPolicy Bypass -File scripts/install.ps1

# ③ 可选：灌入 3 篇内置示例文档（离线就能验证检索/重排）
.venv\\Scripts\\python scripts/seed_demo.py

# ④ 启动（带热重载，改代码自动生效）
.venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000""")
    S.para(doc, "打开 http://127.0.0.1:8000 —— 左侧上传/管理文档，中间提问（逐字流式返回），"
                "右侧展示被引用的来源。接口文档在 http://127.0.0.1:8000/docs （Swagger UI，"
                "FastAPI 自动生成，面试时顺手演示非常加分）。")
    S.h2(doc, "1.6 关键配置项说明（.env）")
    S.table(doc,
            ["配置", "默认值", "含义 / 常见调整"],
            [
                ["LLM_API_KEY", "（空）", "DeepSeek 等厂商密钥；不填则 /api/chat 返回 503，检索链路仍可用"],
                ["LLM_MODEL", "deepseek-chat", "对话模型名（OpenAI 兼容厂商通用）"],
                ["EMBEDDING_PROVIDER", "local", "local=本地 bge；openai=走兼容 API（需配 EMBEDDING_* 三项）"],
                ["EMBEDDING_MODEL_LOCAL", "BAAI/bge-small-zh-v1.5", "换 bge-m3 效果更好但更慢"],
                ["CHUNK_SIZE / CHUNK_OVERLAP", "500 / 50", "最影响检索效果的旋钮之一，按文档语言/粒度调整"],
                ["RERANK_ENABLED / RERANK_TOP_K", "true / 4", "精排开关；top_k 是最终喂给 LLM 的片段数"],
                ["RETRIEVE_DENSE_K / SPARSE_K", "12 / 12", "两路召回各自取回数（候选池越大越全、越慢）"],
                ["RRF_CONSTANT", "60", "RRF 的 k：越大越倾向“稳定前排”的检索器"],
                ["HISTORY_MAX_TURNS / QUERY_REWRITE", "6 / true", "保留最近几轮 / 是否用 LLM 改写问题"],
            ],
            widths=[5.0, 3.0, 7.4])
