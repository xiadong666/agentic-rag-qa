"""Part 4：避坑清单（本项目实测 + RAG 常见）。"""
from __future__ import annotations

import style as S


def add(doc):
    S.h1(doc, "第四部分 避坑清单")
    S.para(doc, "以下每条都是“现象 → 原因 → 解法”，前几条是搭建本项目时真实踩过的，"
                "后几条是 RAG 项目里反复出现的经典坑。面试聊“你遇到过什么坑”时从这里挑 2~3 条讲，"
                "比背概念可信得多。")
    S.h2(doc, "4.1 本项目实测踩过的坑")
    S.table(doc,
            ["坑", "现象", "原因", "解法 / 预防"],
            [
                ["requirements 编码崩溃", "pip install -r 报 UnicodeDecodeError: gbk", "pip 在 Windows 用本地代码页(GBK)读文件；文件里有中文注释", "requirements.txt 保持纯 ASCII（已处理）"],
                ["jieba 无 wheel", "pip 下载源码包后联网装构建依赖超时", "jieba 0.42 只有 sdist", "先装 setuptools/wheel，再 --no-build-isolation 装（install 脚本已处理）"],
                ["控制台中文乱码", "PowerShell 打印中文变乱码", "控制台代码页与 UTF-8 不一致", "别慌：文件是对的；用 chcp 65001 或让日志写文件"],
                ["bge 不带指令掉点", "检索感觉“似懂非懂”", "bge-zh 训练定义 query 侧需指令前缀", "embed_query 里已加；换模型时注意其约定"],
                ["本地模型首次很慢", "第一次回答等很久", "在下载权重（~95MB + ~430MB）", "预热 + 缓存；国内配 HF_ENDPOINT=hf-mirror.com"],
                ["扫描版 PDF 静默空库", "上传成功但怎么问都答不出", "extract_text 返回空没人管", "解析层主动抛“需要 OCR”（已处理）"],
                [".env 找不到", "换目录启动配置全默认", "env_file 用了相对路径", "用绝对路径（config.py 已处理）"],
                ["overlap 过大拖慢", "分块数量暴增、上下文冗余", "overlap 也是成本", "overlap ≈ chunk_size 的 10%~20%"],
                ["Docker 构建找不到 requirements", "pip install -r 报 No such file", "COPY . . 放在了 RUN pip 之后", "先 COPY requirements.txt 再装依赖（Dockerfile 已修正）"],
                ["容器内 pip 装依赖超时", "从 pypi.org 下载卡住 ReadTimeout", "网络到 PyPI 慢/抖动", "pip 设 PIP_DEFAULT_TIMEOUT/RETRIES；国内可换镜像源"],
                ["PowerShell 调 curl 发中文 JSON 报 422", "JSON decode error", "PS5.1 会把引号/编码改坏", "用 python/httpx 发请求，或 --data-binary @file"],
                ["脚本 print 中文/emoji 崩", "UnicodeEncodeError: gbk", "控制台代码页 GBK，非 ASCII 输出", "设 PYTHONIOENCODING=utf-8 或只输出 ASCII"],
                ["设置了镜像仍直连 huggingface.co", "WinError 10051 反复重试", "transformers/huggingface_hub 在 import 瞬间读取环境变量并固化；langchain 导入链会连带 import 它们", "HF 环境必须在导入 langchain/transformers 之前设置（engine.py 顶部已处理）；或 HF_HUB_OFFLINE=1 纯离线"],
                ["网页问答一直“无输出”", "回答区空白，只有兜底提示", "检索正文里的 {item_id} 等花括号被 ChatPromptTemplate 当成缺失模板变量 → 报错被前端兜底文案盖掉", "预渲染消息直接 llm.ainvoke/astream，别再过模板（engine.py 已处理）；前端保留真实错误信息（app.js 已处理）"],
                ["升级 LangChain 0.3→1.2 后 import 报错", "找不到 langchain_text_splitters", "1.x 里 text-splitters 是独立卫星包，不会自动随 langchain 安装", "单独 pip 安装 langchain-text-splitters（>=1.0），导入名不变；core 版本跟随 1.x（本项目已升级验证）"],
            ],
            widths=[3.6, 5.0, 4.6, 6.0])
    S.h2(doc, "4.2 RAG 通用经典坑")
    S.table(doc,
            ["坑", "一句话本质", "对策"],
            [
                ["模型幻觉、答非所问", "资料没进上下文或提示词没约束", "先查检索是否命中（用 /api/search）；提示词写“只依据资料、不知道就说不知道”"],
                ["问题在于检索而不在生成", "生成看起来没问题但答案是错的", "逐段排查：召回→融合→重排每步打印看结果（本项目 /api/search、/api/debug/prompt 就是为此设计）"],
                ["chunk 切碎句子/切碎概念", "分隔符不含中文标点 / 块太小", "中文分隔符列表；按文档结构（标题/章节）切分"],
                ["top_k 太大噪声进上下文", "上下文全是无关片段", "重排后只留 3~5 块；块长≤500 字时尤其明显"],
                ["向量库和元数据错位", "检索到的文本张冠李戴", "永远用“位置=下标”或显式 id 对齐，删改后重建"],
                ["换了 embedding 模型不重建索引", "新旧向量空间不可比，检索全乱", "模型版本与索引强绑定：升级=全量重建"],
                ["多轮对话历史撑爆窗口", "越聊越慢、越贵、越乱", "限制轮数+截断（HISTORY_MAX_TURNS）；必要时做摘要"],
                ["引用编号是模型编的", "[3] 指向毫不相关的来源", "生成后校验引用：抽取编号与来源做一致性检查（进阶篇）"],
                ["单测缺失直接上线", "改了分块参数检索效果回归无感", "离线评测集 + RAGAS 指标（进阶篇）"],
                ["生产裸奔", "无日志无限流无密钥管理", "部署 checklist（Step 15.3）逐项过"],
            ],
            widths=[4.6, 6.2, 7.6])
    S.h2(doc, "4.3 一句话总结避坑心法")
    S.callout(doc, "tip", "RAG 调试顺序永远是：**先证明检索对，再怀疑生成**。"
                          "把检索结果打出来看（本项目专门留了 /api/search 与 /api/debug/prompt），"
                          "80% 的“模型不行”最后都发现是检索/分块的问题。")
