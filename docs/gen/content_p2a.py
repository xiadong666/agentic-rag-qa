"""Part 2a：Step 1 项目骨架 / Step 2 上传 / Step 3 解析 / Step 4 分块。"""
from __future__ import annotations

import style as S


def add(doc):
    step1(doc)


def step1(doc):
    S.h1(doc, "第二部分 分步实现详解")
    S.para(doc, "下面的每一步都会先讲**做什么、为什么**，再贴真实代码讲**知识点**，"
                "最后给**坑**与**面试问法**。请边读边打开对应文件。")

    S.h2(doc, "Step 1　项目骨架与配置中心")
    S.h3(doc, "1.1 做什么")
    S.para(doc, "搭一个分层清晰的项目：`app/` 里按 **api（路由） / core（业务）** 分层，"
                "配置全部集中到 `.env` + `app/config.py`，FastAPI 入口负责生命周期。")
    S.h3(doc, "1.2 为什么这样组织")
    S.bullet(doc, "**路由薄、业务厚**：api 只做“参数 ↔ 业务 ↔ HTTP”翻译，真正逻辑在 core，"
                  "可脱离 FastAPI 单独测试（面试点：关注点分离）。")
    S.bullet(doc, "**配置即代码**：密钥、路径、超参全部环境变量化（12-Factor 原则），"
                  "换环境（本机/服务器/Docker）不改代码。")
    S.h3(doc, "1.3 代码与知识点 —— app/config.py")
    S.code_file(doc, "app/config.py", start=1, end=52)
    S.bullet(doc, "**pydantic-settings**：字段声明即文档，读 `.env`/环境变量并自动做类型转换与校验"
                  "（`bool`、`int`、`Literal` 都能直接映射）。")
    S.bullet(doc, "**`env_file` 用绝对路径**（`ROOT_DIR / \".env\"`）：否则换个目录启动就找不到配置。")
    S.bullet(doc, "**`@lru_cache` 单例**：`get_settings()` 全局只有一份；测试时可 `cache_clear()` 重载。")
    S.bullet(doc, "**派生路径写成 `@property`** 而不是字段：避免字段之间互相依赖默认值的初始化顺序问题。")
    S.callout(doc, "note", "不要在代码里写 `api_key = \"sk-xxx\"` 这种硬编码。密钥进 `.env`，"
                          "且 `.env` 必须加进 `.gitignore`（本项目已配好）。")
    S.h3(doc, "1.4 面试问法")
    S.bullet(doc, "“为什么用 pydantic-settings 而不是 os.environ？” → 类型安全、可校验、集中管理、自动读 .env。")
    S.bullet(doc, "“如何保证多环境可切换？” → 所有差异项走环境变量，配置中心统一出口。")

    S.h2(doc, "Step 2　文档上传接口")
    S.h3(doc, "2.1 做什么 / 为什么")
    S.para(doc, "浏览器把文件以 `multipart/form-data` 发上来，后端边收边落盘、做**格式与大小校验**。"
                "不能直接把整个文件读进内存 —— 几十 MB 文件会轻易打爆服务器内存。")
    S.h3(doc, "2.2 代码与知识点 —— app/api/documents.py")
    S.code_file(doc, "app/api/documents.py", start=25, end=64)
    S.bullet(doc, "**UploadFile + File(...)**：FastAPI 处理 multipart 的标准姿势；"
                  "缺了 `python-multipart` 依赖会直接报错（还记得吗？requirements 里有它）。")
    S.bullet(doc, "**流式落盘**：`await file.read(1MB)` 循环写盘，边读边统计字节数，超 `MAX_UPLOAD_MB` "
                  "立刻中断并清理临时文件 —— 这叫**流式上传 + 软限额**。")
    S.bullet(doc, "**扩展名白名单**是校验第一道门；上传文件先落临时目录，入库成功与否都有明确 HTTP 状态码"
                  "（400 类型不对 / 413 太大 / 400 解析失败 / 500 兜底）。")
    S.callout(doc, "warn", "扩展名可伪造（改后缀即可）。真实生产要校验文件头魔数（magic bytes），"
                          "例如 PDF 以 `%PDF` 开头。教学版把内容解析失败作为第二道防线。")
    S.callout(doc, "tip", "上传接口必须 try/except 兜底并统一转 HTTPException：**绝不能让堆栈直接返回给前端**"
                         "（信息泄露 + 体验差）。")

    S.h2(doc, "Step 3　文档解析")
    S.h3(doc, "3.1 做什么 / 为什么")
    S.para(doc, "把 PDF / Word / Markdown / TXT 变成**带页码的纯文本**。"
                "保留页码是本项目“引用来源可以精确到第几页”的前提。")
    S.h3(doc, "3.2 三种格式的解析姿势")
    S.table(doc,
            ["格式", "工具", "要点"],
            [
                ["PDF", "pypdf 的 PdfReader", "按页 extract_text；扫描件抽不出文字要提示 OCR"],
                ["Word .docx", "python-docx", "docx 本质是 zip+XML；document.paragraphs 拿正文段落"],
                ["txt / md 等", "内置 open + 编码探测", "utf-8-sig（吃 BOM）→ utf-8 → gbk 依次尝试"],
            ],
            widths=[2.6, 3.6, 9.2])
    S.code_file(doc, "app/core/parsing.py", start=34, end=59)
    S.bullet(doc, "**策略模式**：一个 `parse_file()` 按扩展名分发到具体解析器，"
                  "以后加 pptx/html/OCR 只加一个函数，不动调用方。")
    S.bullet(doc, "**编码是中文 Windows 的头号坑**：老文档常用 GBK；Python 默认 UTF-8 直接读会抛 "
                  "`UnicodeDecodeError`。先 `utf-8-sig`（兼容记事本 BOM）再 `gbk` 是稳妥顺序。")
    S.callout(doc, "warn", "扫描版 PDF `extract_text()` 返回空 → 项目会明确报“需要 OCR”，"
                          "而不是静默建一个空知识库。真实项目可接 PaddleOCR / 阿里云 OCR 等。"
                          "能主动发现并说清“这个环节为什么需要 OCR”，本身就是面试加分项。")

    S.h2(doc, "Step 4　文本分块（chunking）")
    S.h3(doc, "4.1 为什么必须分块")
    S.bullet(doc, "检索粒度：模型只能把“一小段上下文”和问题比相似度，整篇文档没法按“哪句相关”命中。")
    S.bullet(doc, "窗口限制：LLM 上下文有限，塞整篇会爆；分块后只把最相关的几块喂给模型。")
    S.callout(doc, "tip", "面试常问“分块多大合适？”——没有标准答案：结构清晰的技术文档 300~800 字符常见，"
                         "chunk_size 与 overlap 是 RAG 里**最该先调的超参**，效果差先怀疑它。")
    S.h3(doc, "4.2 代码与知识点 —— app/core/chunking.py")
    S.code_file(doc, "app/core/chunking.py", start=24, end=60)
    S.bullet(doc, "**RecursiveCharacterTextSplitter**：按“分隔符优先级”递归切：先按段落 `\\n\\n` 切，"
                  "块仍太大再按 `\\n`、再按句末标点……尽量保住语义完整的小节。")
    S.bullet(doc, "**中文必须自定义分隔符**：英文靠空格分词，中文没有空格 —— 分隔符列表里必须加 "
                  "`。！？；` 等标点，否则会把句子拦腰截断（本项目在 `ZH_SEPARATORS` 里做了适配）。")
    S.bullet(doc, "**overlap 的意义**：切在边界的一句话，可能前半在块 A、后半在块 B；"
                  "overlap 让边界内容在相邻块里也出现，避免“检索时那句话永远不完整”。")
    S.bullet(doc, "**按页先拆再分块**：让每个 chunk 都能准确记录页码 → 引用来源可溯源到页。")
    S.callout(doc, "warn", "chunk_size 的单位这里按“字符数”（`length_function=len`）。"
                          "如果按 token 计，中文约 1 字 ≈ 0.6~1 token，需要换算；"
                          "把“计长方式”讲清楚也是面试细节分。")
