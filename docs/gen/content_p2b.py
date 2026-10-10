"""Part 2b：Step 5 向量化 / Step 6 向量库与稠密检索 / Step 7 BM25 / Step 8 混合检索+RRF。"""
from __future__ import annotations

import style as S


def add(doc):
    step5(doc)


def step5(doc):
    S.h2(doc, "Step 5　文本向量化（Embedding）")
    S.h3(doc, "5.1 一句话原理")
    S.para(doc, "Embedding 模型把“文本”映射成一个固定维度的向量（如 512 维浮点数组），"
                "语义相近的文本向量在空间里也相近。于是“找相关文档”变成“找最近邻向量”。")
    S.bullet(doc, "**bi-encoder**：query 和文档各自过一遍模型编码成向量，再算相似度 —— 快，"
                  "可把文档向量预计算好存库，适合召回阶段。")
    S.bullet(doc, "**cross-encoder**：query 和文档拼成一个序列一起过模型 —— 准但慢，只能在线对少量"
                  "候选打分（就是 Step 9 的重排模型）。召回用 bi、精排用 cross，是标准两段式。")
    S.h3(doc, "5.2 代码与知识点 —— app/core/embeddings.py")
    S.code_file(doc, "app/core/embeddings.py", start=30, end=60)
    S.bullet(doc, "**面向接口**：定义 `Embedder` 抽象，本地实现与 OpenAI 兼容 API 实现可替换，"
                  "上层 engine 只依赖接口 —— 换厂商零侵入。")
    S.bullet(doc, "**懒加载 + 线程锁**：模型几百 MB，第一请求才加载；`sentence-transformers` 推理"
                  "非线程安全，用 `threading.Lock` 串行化。")
    S.bullet(doc, "**归一化 `normalize_embeddings=True`**：向量归一化后“内积 = 余弦相似度”，"
                  "FAISS 才可以用最快的内积索引（下一步的关键前提）。")
    S.callout(doc, "warn", "**bge 系列要加 query 指令前缀**（“为这个句子生成表示以用于检索相关文章：”），"
                          "这是作者训练时定义的“非对称”用法：query 加、文档不加。漏掉会掉好几个点 —— "
                          "本地实现里 `embed_query()` 已处理。")
    S.callout(doc, "note", "中文 embedding 怎么选？轻量 `bge-small-zh-v1.5`（本项目默认，约 95MB，CPU 可跑）"
                          "→ 效果更好 `bge-m3`（多语言、约 1.2GB）→ 商业 API（硅基流动/百炼等，免部署）。"
                          "首次运行会下载模型，国内可配 `HF_ENDPOINT=https://hf-mirror.com`。")

    S.h2(doc, "Step 6　向量存储与稠密检索")
    S.h3(doc, "6.1 架构：向量库与元数据库分工")
    S.para(doc, "FAISS 只存**向量**，不知道向量代表什么；原文与出处（文档名/页码）放在 JSONL。"
                "两者靠 **“向量位置 = 记录数组下标”** 对齐 —— 这是理解一切向量检索系统的钥匙。")
    S.code_file(doc, "app/core/vector_store.py", start=25, end=61)
    S.bullet(doc, "**IndexFlatIP = 暴力全量内积**：精确、O(N)，小数据量完全够用且最好懂；"
                  "大数据量换 HNSW/IVF（近似索引，精度换速度，见进阶篇）。")
    S.bullet(doc, "**余弦怎么来的**：向量已 L2 归一化 → 内积 == cos(夹角)，score 越高越相似。")
    S.bullet(doc, "**持久化**：`faiss.write_index / read_index` 一行落盘。")
    S.h3(doc, "6.2 知识库持久层 —— app/core/store.py")
    S.code_file(doc, "app/core/store.py", start=98, end=121)
    S.bullet(doc, "**JSONL**：每行一个 JSON，追加写 O(1)、可用记事本查看、好调试；"
                  "中小规模知识库最朴实的方案。")
    S.bullet(doc, "`docs.jsonl` 管文档元信息、分块记录与 FAISS 位置天然对齐；删除文档 = 过滤重写 + 重建索引"
                  "（演示够用；生产用数据库 + 向量库事务，见进阶）。")
    S.callout(doc, "warn", "重建索引要**重算所有 embedding**（贵）。演示规模无所谓；"
                          "生产增量入库时别每次全量重建（进阶篇给出正确姿势）。")

    S.h2(doc, "Step 7　稀疏检索：自实现 BM25")
    S.h3(doc, "7.1 为什么有了向量还要关键词检索")
    S.para(doc, "向量擅长“语义相似”，但**精确词**（型号、人名、报错原文、专有名词如 `CHUNK_SIZE`）"
                "一旦没进语义邻居就漏召回；关键词检索对字面命中又稳又快。两路互补 → 混合检索。")
    S.h3(doc, "7.2 BM25 公式（面试手撕级）")
    S.code(doc, """score(q, d) = Σ_{t∈q}  idf(t) · f(t,d)·(k1+1) / ( f(t,d) + k1·(1 − b + b·|d|/avgdl) )
idf(t) = ln( 1 + (N − df(t) + 0.5) / (df(t) + 0.5) )     k1≈1.5，b≈0.75""")
    S.bullet(doc, "对比 TF-IDF 的两处升级：**词频饱和**（k1：词出现 5 次不必比 2 次强 2.5 倍）"
                  "与**文档长度归一化**（b：长文档里多出现几次是正常的，别吃亏）。")
    S.bullet(doc, "**中文要先分词**：中文没有空格。项目用 jieba 分词，中英混排正则兜底（见 `bm25.py` 的 tokenize）。")
    S.h3(doc, "7.3 代码结构")
    S.code_file(doc, "app/core/bm25.py", start=44, end=88)
    S.callout(doc, "tip", "自己实现 BM25 的目的不是“比 Elasticsearch 强”，而是**把公式和倒排思想吃透**："
                         "面试被问 BM25/TF-IDF/倒排索引时能直接默写推导。生产换 ES/OpenSearch 只改一层。")

    S.h2(doc, "Step 8　混合检索与 RRF 融合")
    S.h3(doc, "8.1 问题：两种分数不可比")
    S.para(doc, "向量相似度（余弦 ∈[-1,1]）与 BM25 分数（无上界）**量纲完全不同**，直接加权和没有意义。"
                "工程上最常用的解法是 **RRF（Reciprocal Rank Fusion）**：不看分数看名次。")
    S.h3(doc, "8.2 RRF 原理")
    S.code(doc, """score(item) = Σ_{每个检索器}  1 / (k + rank)      # 默认 k=60
例：某块在稠密结果排第1、在BM25排第5 → 1/(60+1) + 1/(60+5)""")
    S.bullet(doc, "只依赖**名次**，与各检索器分数尺度无关 → 加第 3、第 4 路召回零成本；")
    S.bullet(doc, "k 越大，融合结果越被“两个检索器都排前面”的文档主导，对单路尖子生越宽容。")
    S.code_file(doc, "app/core/retrieval.py", start=26, end=52)
    S.code_file(doc, "app/core/retrieval.py", start=54, end=90)
    S.callout(doc, "idea", "面试讲混合检索的推荐话术：**“召回要全、要互补，融合要稳、要可解释”**。"
                          "dense 管语义、sparse 管字面、RRF 管合并，再到精排统一把关 —— "
                          "这就是本项目检索部分的完整答案。")
    S.callout(doc, "warn", "混合检索候选池会引入噪声，**必须先重排再生成**，否则噪声片段直接进上下文，"
                          "既浪费 token 又拉低答案质量 —— 这正是 Step 9 重排存在的意义。")
