"""Part 3：代码知识点总结（按主题总表）。"""
from __future__ import annotations

import style as S


def add(doc):
    S.h1(doc, "第三部分 代码知识点总结")
    S.para(doc, "这一部分按“主题”把项目里出现过的知识点汇总成清单，配合代码快速回顾。"
                "建议面试前把每个格子都过成“一句话能讲清”。")
    S.h2(doc, "3.1 Python 语言层")
    S.table(doc,
            ["知识点", "出现在哪", "一句话要点"],
            [
                ["dataclass", "store.py / chunking.py / bm25.py", "轻量数据容器，asdict() 便于序列化；与 Pydantic 各司其职"],
                ["@property / lru_cache", "config.py", "派生路径不落字段；lru_cache 做单例"],
                ["typing 注解 + Literal", "全项目", "FastAPI/pydantic 靠注解自动校验与生成文档"],
                ["abc 抽象基类", "embeddings.py / rerank.py", "定义接口，多实现可替换（面向接口）"],
                ["context manager（with）", "api/documents.py", "文件/锁的获取与释放成对出现"],
                ["asyncio.to_thread", "engine.py", "把同步 CPU 任务丢线程池，不阻塞事件循环"],
                ["async generator（yield）", "engine.answer_stream", "惰性产出事件，支撑 SSE 流式"],
                ["uuid / datetime / time.perf_counter", "多处", "doc_id、时间戳、精确计时"],
                ["异常层级与统一处理", "parsing.py/API 层", "ParseError→400，RuntimeError→503，兜底 500"],
            ],
            widths=[4.2, 4.4, 6.8])
    S.h2(doc, "3.2 FastAPI 层")
    S.table(doc,
            ["知识点", "一句话要点"],
            [
                ["路由装饰器 + response_model", "返回结构即契约，自动过滤多余字段"],
                ["UploadFile + python-multipart", "multipart 上传必需依赖，缺失报错"],
                ["Depends / 依赖注入", "本项目用 request.app.state.engine 共享单例"],
                ["lifespan 上下文", "启动初始化 engine、关闭清理；替代模块级全局变量"],
                ["StreamingResponse + SSE", "text/event-stream 分帧推送，头加 X-Accel-Buffering:no"],
                ["CORSMiddleware", "前后端跨域；生产收窄域名"],
                ["HTTPException 与状态码语义", "400/404/413/500/503 各司其职"],
                ["静态文件 + FileResponse", "单进程同端口提供 UI 与 API"],
            ],
            widths=[5.4, 10.0])
    S.h2(doc, "3.3 LangChain 层")
    S.table(doc,
            ["知识点", "一句话要点"],
            [
                ["ChatOpenAI（OpenAI 兼容）", "base_url/api_key/model 三件套切厂商"],
                ["ChatPromptTemplate.from_messages", "(\"system\"/\"human\", content) 元组序列"],
                ["LCEL：prompt | llm | StrOutputParser", "组件化 Runnable，invoke/stream 同协议"],
                ["astream 流式", "逐 token 产出，SSE 推送前端"],
                ["RecursiveCharacterTextSplitter", "按分隔符优先级递归切；中文要加标点分隔符"],
                ["版本锁定 1.2.x", "1.x 为当前主线；0.3→1.x 迁移注意：text-splitters 等为独立卫星包、langchain_core 版本跟随 1.x（详见避坑清单）；先固定版本再升级"],
            ],
            widths=[5.6, 9.8])
    S.h2(doc, "3.4 检索/向量层")
    S.table(doc,
            ["知识点", "一句话要点"],
            [
                ["bi-encoder vs cross-encoder", "召回用 bi（快）、精排用 cross（准但慢）"],
                ["归一化 → 内积 = 余弦", "embeddings 输出 normalize，FAISS 用 IndexFlatIP"],
                ["FAISS 存向量，JSONL 存原文", "按“向量位置 = 记录下标”对齐"],
                ["BM25 公式与 k1/b", "词频饱和 + 文档长度归一化，优于 TF-IDF"],
                ["中文分词 jieba", "中文无空格，检索前先分词"],
                ["RRF 融合", "按名次给 1/(k+rank)，分数不可比时的工程解"],
                ["倒排 / 词频统计（df）", "idf 需要文档频率，每篇文档一个词只计一次"],
                ["持久化与重建", "write_index/read_index；删除文档→全量重建（演示策略）"],
            ],
            widths=[5.2, 10.2])
    S.h2(doc, "3.5 设计模式 / 架构层")
    S.table(doc,
            ["模式", "落地", "收益"],
            [
                ["分层架构", "api / core / static", "可测、可替换、职责清晰"],
                ["工厂模式", "create_embedder / create_reranker", "按配置选择实现，主流程零改动"],
                ["策略模式", "parse_file 按扩展名分发", "扩展新格式只加函数"],
                ["单例", "get_settings() / RAGEngine 挂 app.state", "全局唯一状态，避免重复加载模型"],
                ["懒加载", "LocalEmbedder/CrossEncoder 首次请求才 load", "启动快、省内存"],
                ["纯函数拆分", "_build_answer_messages 不调 LLM", "可单测、可 /debug/prompt 零成本调试"],
                ["DTO（schemas）", "请求/响应模型与内部 dataclass 分离", "API 契约稳定，内层可演进"],
            ],
            widths=[4.0, 5.6, 5.8])
    S.h2(doc, "3.6 工程 / 产品层")
    S.table(doc,
            ["知识点", "一句话要点"],
            [
                ["可观测性", "日志 + /health + 耗时统计（elapsed_ms 贯穿响应）"],
                ["引用来源 = 可信度", "回答可溯源、可验证；[n] 与 sources 一一对应"],
                ["体验细节", "meta 先推来源、token 逐字渲染、错误事件不裸奔"],
                ["安全基线", "扩展名/大小限制、异常不外泄堆栈、前端输出转义"],
                ["配置驱动", "所有超参/密钥进 .env，换环境不改代码"],
            ],
            widths=[4.0, 11.4])
