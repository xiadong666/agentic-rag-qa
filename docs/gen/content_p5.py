"""Part 5：面试与简历；Part 6：进阶路线；附录。"""
from __future__ import annotations

import style as S


def add(doc):
    part5(doc)
    part6(doc)
    appendix(doc)


def part5(doc):
    S.h1(doc, "第五部分 面试与简历：把项目讲成你的加分项")
    S.h2(doc, "5.1 一分钟介绍词（背熟）")
    S.para(doc, "“我做过一个基于 FastAPI 和 LangChain 的 RAG 知识库问答系统。它支持上传 PDF、Word 等文档，"
                "自动解析、按语义分块后向量化入库；用户提问时，系统先用**稠密向量 + BM25 混合检索**召回，"
                "用 RRF 做结果融合，再用 cross-encoder **重排**选出最相关的片段，最后交给大模型生成**带编号引用**"
                "的回答，并且支持**多轮对话**和**流式输出**。整体用 Docker 部署成 Web 服务。"
                "我在里面自己实现了 BM25 和 RRF，也踩过编码、模型兼容之类的坑。")
    S.h2(doc, "5.2 简历写法（可直接抄，按 3 条 bullet 组织）")
    S.table(doc,
            ["模块", "示例文字"],
            [
                ["项目名", "RAG 知识库问答系统（FastAPI + LangChain）｜个人项目"],
                ["职责 1", "设计并实现文档入库全链路：PDF/Word/Markdown 解析、中文分块（重叠+按页溯源）、bge 中文向量化、FAISS 索引、JSONL 元数据持久化"],
                ["职责 2", "实现混合检索：自实现 BM25 稀疏检索 + 稠密向量召回，RRF 名次融合，cross-encoder（bce-reranker）精排，检索命中率显著优于单一向量召回"],
                ["职责 3", "基于 LangChain LCEL 搭建生成链路：对话历史问题改写、引用来源结构化返回、SSE 流式输出；三栏 Web UI 展示问答与引用"],
                ["职责 4", "工程化：配置中心（pydantic-settings）、分层架构、异常与日志、接口文档（Swagger）、Docker/docker-compose 部署"],
                ["技术栈", "FastAPI · LangChain 1.2（core 1.6）· sentence-transformers · FAISS · jieba · Docker"],
            ],
            widths=[2.2, 13.2])
    S.h2(doc, "5.3 高频面试问答 TOP 20（先自答再对照）")
    qa = [
        ("讲一下 RAG 的整体流程？", "离线：文档→解析→分块→向量化→索引；在线：问题→（改写）→检索→融合→重排→拼上下文→生成。关键是把“检索到的资料”作为事实来源。"),
        ("为什么需要分块？块多大合适？", "检索粒度和窗口限制。大小因文档/语言而异：结构化技术文档 300~800 字符常见；overlap 取 10~20%。"),
        ("向量检索和关键词检索各自的优劣？", "向量懂语义但漏精确词；BM25 字面稳但不懂同义改写；混合互补。"),
        ("RRF 融合的原理？为什么不用加权和？", "各检索器分数不可比；RRF 只看名次给 1/(k+rank)，稳定可解释，加路零成本。"),
        ("bi-encoder 和 cross-encoder 区别？", "bi 各自编码算相似度，可预计算、快，用于召回；cross 拼接共编码，准但慢，用于精排。"),
        ("为什么重排能提升效果？", "召回是粗筛，排序不准；cross-encoder 让问题与文档 token 交互，相关性判断更细。"),
        ("如何做引用来源？", "分块记文档名/页码→上下文编号→提示词要求 [n] 标注→响应结构化返回 sources；前端展示。"),
        ("多轮对话怎么和 RAG 结合？", "两种：历史原文拼接（占窗口）或 LLM 把问题改写成独立问题再检索（本项目，结合两者）。"),
        ("大模型幻觉怎么缓解？", "检索质量（资料真在上下文）、提示词约束（只依据资料/不知道就说）、引用校验、必要时给模型“拒绝回答”的出口。"),
        ("如何评估一个 RAG 系统好不好？", "拆开评估：检索看召回/命中（Recall@k），生成看忠实度与有用性，可用 RAGAS；先离线评测再上线。"),
        ("embedding 模型怎么选？", "看语言（中文用 bge 系）、维度/成本、是否可本地部署；注意 query 指令与归一化约定；换模型必须重建索引。"),
        ("向量库 FAISS/Chroma/Milvus 怎么选？", "小项目进程内 FAISS/Chroma；大数据、多副本、过滤查询用 Milvus/Qdrant 服务化；云上可用 pgvector 省组件。"),
        ("langchain 0.3 和 1.x 区别？", "1.x 是当前主线：合并/理顺了包结构，langchain-text-splitters 等成为独立卫星包（langchain_text_splitters 导入名不变，但需随 1.x 单独安装并锁版本）。本项目已从 0.3 升级到 1.2（core 1.6）并实测全链路通过：本项目用到的 ChatOpenAI / ChatPromptTemplate / StrOutputParser / 直接 ainvoke/astream 的写法在 1.x 保持兼容；生产务必固定版本。"),
        ("如何做流式输出？", "LCEL astream 逐 token；后端 SSE（text/event-stream）；前端 fetch+ReadableStream；注意关代理缓冲。"),
        ("异步服务里遇到 CPU 密集代码怎么办？", "asyncio.to_thread 丢线程池；共享状态（索引、模型）加锁；避免阻塞事件循环。"),
        ("服务多进程部署有什么坑？", "每进程各加载一份模型/索引（内存翻倍）；会话状态不进进程内；可外置向量库与 Redis。"),
        ("上传文件要注意什么？", "流式落盘防内存打爆、大小与类型校验（魔数）、临时文件清理、错误统一转 HTTP 状态码。"),
        ("提示词里为什么要限制“只依据资料”？", "把 LLM 从“知识回忆模式”切到“资料阅读模式”，从源头压幻觉；配合引用让回答可审计。"),
        ("如果知识库很大（百万级 chunk）怎么办？", "近似索引 HNSW/IVF；倒排外置 ES；分布式向量库；分片/多租户隔离。"),
        ("有没有想过这个项目怎么进一步产品化？", "（开放题）加权限与多租户、审计日志、引用校验、RAGAS 自动评估、LangGraph 做 Agent 化、语义缓存降本。"),
    ]
    for i, (q, a) in enumerate(qa, start=1):
        S.h3(doc, f"Q{i}　{q}")
        S.para(doc, f"**要点答案：**{a}")

    S.h2(doc, "5.4 被追问“为什么不用 XXX”时的通用答法")
    S.para(doc, "先承认该技术更优的场景，再讲清本项目为何够用，最后给升级路径。"
                "例：“为什么用 FAISS 不用 Milvus？—— 教学/演示规模 FAISS 进程内足够且能讲清原理；"
                "数据量到百万级、需要多副本与复杂过滤时，我会把向量层换成 Milvus/Qdrant，接口设计上"
                "（Embedder/VectorStore 抽象）已经为替换留好了口子。”")


def part6(doc):
    S.h1(doc, "第六部分 进阶路线")
    S.para(doc, "实习/正式项目里，RAG 通常不是“能跑”就够。下面按性价比排序，标了每个方向解决什么问题。")
    S.h2(doc, "6.1 检索质量的进阶")
    S.bullet(doc, "**离线评测先于调参**：建 30~50 条 (问题, 期望文档/片段) 的评测集，量化 Recall@k、MRR —— 没评测的调参都是玄学。")
    S.bullet(doc, "**RAGAS**：对生成结果自动打分（忠实度/相关性/上下文精度），纳入 CI。")
    S.bullet(doc, "**分块升级**：按文档结构（标题树/表格/代码块）切分；Markdown 头信息解析（本项目 parsing 留有 meta 扩展位）。")
    S.bullet(doc, "**查询增强**：HyDE（先让 LLM 生成假答案再检索）、Multi-Query（一个问句拆多个子查询）、query 路由（结构化问题走 SQL/API）。")
    S.bullet(doc, "**GraphRAG**：用知识图谱表达实体关系，回答“跨多文档的关系型问题”（如对比/归纳）。")
    S.bullet(doc, "**向量库选型**：百万级切 HNSW/IVF；服务化选 Qdrant/Milvus/pgvector。")
    S.h2(doc, "6.2 生成质量的进阶")
    S.bullet(doc, "**引用校验**：解析 [n]，用重排/相似度确认该编号确实支撑该句，不支撑就删掉引用或补搜。")
    S.bullet(doc, "**Agentic RAG**（LangGraph）：让模型决定“要不要检索、检索什么、不够再搜”，多跳复杂问题效果更好。")
    S.bullet(doc, "**结构化输出**：用 with_structured_output 逼模型输出 JSON，便于引用/状态机处理。")
    S.h2(doc, "6.3 工程化的进阶")
    S.bullet(doc, "**可观测**：接 LangSmith / 自建 trace：记录 query→改写→召回→重排→生成全链路耗时与分数。")
    S.bullet(doc, "**语义缓存**：相同/相似问题直接命中历史答案，省 token 降延迟（向量相似度查缓存）。")
    S.bullet(doc, "**增量更新与一致性**：文档变更走“新增/删除/重解析”而非全量重建；embedding 模型版本与索引绑定。")
    S.bullet(doc, "**成本与限流**：token 用量统计、按用户配额、模型路由（简单问题用小模型）。")
    S.h2(doc, "6.4 推荐学习顺序")
    S.para(doc, "① 离线评测集 + RAGAS → ② Multi-Query / HyDE → ③ 引用校验 → ④ LangGraph Agentic RAG → ⑤ 向量库服务化。"
                "每个都对应面试官“你还能怎么做”的追问，做过 ①② 就足以在实习生里拉开差距。")


def appendix(doc):
    S.h1(doc, "附录")
    S.h2(doc, "A. 本项目环境与依赖版本（验证于本机）")
    S.table(doc,
            ["组件", "版本/说明"],
            [
                ["Python", "3.10.4 / 3.11.7（均已实测）；建议 3.10 ~ 3.12；3.13+ 部分库可能缺 wheel"],
                ["fastapi / uvicorn", "0.111+ / 0.30+（<1.0 锁大版本）"],
                ["langchain", "1.2.18（langchain-core 1.6.2，本项目已升级并实测）"],
                ["langchain-openai", "1.6.x（OpenAI 兼容接入 DeepSeek 等）"],
                ["langchain-text-splitters", "1.1.x（1.x 的独立卫星包，需单独安装）"],
                ["torch", "2.14.0+cpu（CPU 源安装，勿装 CUDA 版）"],
                ["sentence-transformers", "4.x（本地 embedding + rerank）"],
                ["faiss-cpu / numpy", "1.15 / 2.x"],
                ["pypdf / python-docx / jieba", "6.x / 1.2 / 0.42.1"],
            ],
            widths=[5.0, 10.4])
    S.h2(doc, "B. 术语速查")
    S.table(doc,
            ["术语", "一句话解释"],
            [
                ["RAG", "检索增强生成：先检索相关资料，再让模型基于资料生成"],
                ["Embedding / 向量化", "把文本映射成高维向量，语义近则向量近"],
                ["bi-encoder", "查询/文档各自编码再比相似度（召回用）"],
                ["cross-encoder", "查询+文档拼接共同编码打分（精排用）"],
                ["BM25", "关键词排序算法：词频饱和 + 长度归一化"],
                ["RRF", "按名次融合多路检索结果的算法"],
                ["chunk / overlap", "知识块 / 相邻块重叠长度"],
                ["FAISS", "Facebook 的向量相似度检索库"],
                ["HNSW / IVF", "近似最近邻索引：用精度换速度"],
                ["SSE", "服务器单向推送事件的 HTTP 流式协议"],
                ["LCEL", "LangChain 表达式语言：用 | 组合组件"],
                ["RAGAS", "RAG 自动评估框架（忠实度等指标）"],
                ["HyDE / Multi-Query", "查询增强手段（假答案检索 / 多子查询）"],
                ["LangGraph", "用图编排 Agent/RAG 流程的库"],
            ],
            widths=[3.8, 11.6])
    S.h2(doc, "C. 常用资料")
    S.bullet(doc, "DeepSeek API 文档：platform.deepseek.com（OpenAI 兼容说明）")
    S.bullet(doc, "LangChain 文档（1.x 主线）：python.langchain.com（右上角可切版本）")
    S.bullet(doc, "FAISS 官方 wiki：github.com/facebookresearch/faiss")
    S.bullet(doc, "sentence-transformers 模型库：huggingface.co（bge 系、bce-reranker）")
    S.bullet(doc, "RAGAS：docs.ragas.io；LangGraph：langchain-ai.github.io/langgraph")
    S.h2(doc, "写在最后")
    S.para(doc, "这份文档的目的是让你**带着理解去面试**，而不是背答案。"
                "把项目跑起来、亲手改几个参数、故意弄坏它再看日志 —— "
                "那些“啊，原来如此”的瞬间，才是面试时最值钱的谈资。祝你顺利拿到心仪的实习 offer！")
