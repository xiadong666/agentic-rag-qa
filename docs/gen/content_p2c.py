"""Part 2c：Step 9 重排 / Step 10 引用来源 / Step 11 对话历史 / Step 12 生成与流式。"""
from __future__ import annotations

import style as S


def add(doc):
    step9(doc)


def step9(doc):
    S.h2(doc, "Step 9　重排序（Rerank）")
    S.h3(doc, "9.1 为什么要精排")
    S.para(doc, "召回阶段的向量/BM25 都是“粗筛”：快、全，但顺序不够准。"
                "cross-encoder 把 `(问题, 文档)` 拼在一起过一遍模型，两个文本的 token **互相 attend**，"
                "能捕捉 bi-encoder 丢失的精细交互 —— 精度高一个档次，代价是慢（逐对推理）。"
                "所以只在**少量候选**（本项目 12+12 路 RRF 后取前若干）上精排，取 top 4 进上下文。")
    S.callout(doc, "idea", "“召回快而全，精排慢而准”—— 这种 **漏斗式两段检索**是搜索/RAG 的通用架构，"
                          "讲项目时主动说出这套取舍，比背概念强太多。")
    S.h3(doc, "9.2 代码与知识点 —— app/core/rerank.py")
    S.code_file(doc, "app/core/rerank.py", start=34, end=67)
    S.bullet(doc, "与 embedding 复用 `device` 配置；同样懒加载 + 锁；")
    S.bullet(doc, "分数是 cross-encoder 的 logit（可正可负），**降序**取 top_k；")
    S.bullet(doc, "本地中文模型选 `bce-reranker-base_v1`（对 bge/中文检索友好、约 400MB）；"
                  "也可换成硅基流动等 rerank API（改一个实现即可）。")
    S.callout(doc, "warn", "cross-encoder 的输入有长度上限（一般 512 token），文档太长要先截断"
                          "（代码里 `text[:2000]` 只是保守演示；严谨做法是按 token 截断）。")
    S.callout(doc, "note", "重排模型也常常“对检索器偏心”：bce-reranker 配 bge 系效果稳。"
                          "换模型后记得回归测试（进阶篇：用 RAGAS 做离线评估）。")

    S.h2(doc, "Step 10　引用来源（全链路溯源）")
    S.h3(doc, "10.1 设计：出处从分块一直带到回答")
    S.table(doc,
            ["环节", "做了什么", "代码"],
            [
                ["分块", "每个 chunk 记录 doc_title / page", "chunking.py"],
                ["入库", "元数据写进 JSONL 记录", "store.py"],
                ["检索", "命中的 chunk 带出处与分数返回", "retrieval.py / engine._ranked_to_sources"],
                ["拼上下文", "资料编号 [1][2]…并注明《文档》第几页", "prompts.format_context_block"],
                ["生成", "提示词强制“用了哪条资料就在句末标 [n]”", "prompts.ANSWER_SYSTEM"],
                ["响应", "answer + sources（结构化）一起返回前端", "schemas.AnswerResponse"],
            ],
            widths=[2.4, 9.0, 4.0])
    S.code_file(doc, "app/core/prompts.py", start=15, end=31)
    S.bullet(doc, "提示词里写死三条铁律：**只依据资料 / 引用带编号 / 不知道就说不知道** —— "
                  "这是对抗幻觉的第一道闸门。")
    S.bullet(doc, "引用编号与 `sources[].cite_index` 一一对应 → 前端把 [1] 渲染成可点来源卡片。")
    S.callout(doc, "warn", "LLM 偶尔会编造不存在的编号或张冠李戴。真实系统要做**引用校验**："
                          "解析回答中的 [n]，用重排模型/相似度核对 n 是否真的支持该句（进阶篇）。")
    S.callout(doc, "idea", "把 sources 放进 API 响应模型（`AnswerResponse.sources`）是**产品思维**："
                          "回答可验证、可审计、可追责 —— 企业级 RAG 的必备项，也是简历上能写的亮点。")

    S.h2(doc, "Step 11　对话历史与会话管理")
    S.h3(doc, "11.1 多轮 RAG 的两条路线")
    S.table(doc,
            ["路线", "做法", "优点 / 缺点"],
            [
                ["A. 历史原文拼接", "把最近几轮问答原文塞进提示词", "简单；但占用窗口，且“它呢？”这种指代问题无法检索"],
                ["B. 独立问题改写（本项目）", "先让 LLM 结合历史把问题改写成不依赖上下文的问句，再检索", "检索词永远完整可检索；代价是多次 LLM 调用"],
            ],
            widths=[3.6, 6.6, 5.2])
    S.para(doc, "本项目走 B 路线但保留 A 的“历史原文”放在 system 里让模型理解上下文 —— "
                "两者结合，这正是能讲出彩的设计。")
    S.code_file(doc, "app/core/memory.py", start=34, end=63)
    S.bullet(doc, "**会话表 + LRU**：`OrderedDict` 天然有序，超上限淘汰最旧会话（`popitem(last=False)`）。")
    S.bullet(doc, "**JSONL 追加持久化**：重启不丢历史；写放大可接受（演示）。")
    S.callout(doc, "tip", "改写提示词要求“只输出独立问题本身”，并用 `StrOutputParser` 拿纯文本 —— "
                         "注意别让模型输出解释文字污染检索词。")
    S.callout(doc, "note", "窗口管理是工程细节：保留轮数（`HISTORY_MAX_TURNS`）与每条历史截断长度都要限，"
                          "否则多轮后 system 被历史撑爆（代码里历史回答截 300 字）。")

    S.h2(doc, "Step 12　生成回答：消息组装 + 流式")
    S.h3(doc, "12.1 组装“已渲染好的消息”，再直接调用模型")
    S.para(doc, "本项目的检索结果可能包含任意正文（代码、公式里的 `{item_id}` 这类花括号）。"
                "**关键坑**：绝不能把这种已经拼好的正文再丢进 `ChatPromptTemplate` —— LangChain "
                "模板会把 `{...}` 当成模板变量，正文里出现 `{item_id}` 就报 "
                "`missing variables {item_id}` 导致整条链路 500/无输出。"
                "所以：预渲染完成后**以消息列表直接调用模型**（`ainvoke / astream`），"
                "只有变量受控的“问题改写”（Step 11）才使用模板 + LCEL。")
    S.code_file(doc, "app/core/engine.py", start=242, end=280)
    S.code_file(doc, "app/core/engine.py", start=300, end=345)
    S.bullet(doc, "`llm.ainvoke(messages)` → 返回 AIMessage，取 `.content` 得到完整回答；")
    S.bullet(doc, "`llm.astream(messages)` → 逐 token 产出，配合 SSE 推给前端（流式不依赖 LCEL，"
                  "LangChain 聊天模型原生支持）。")
    S.callout(doc, "warn", "LangChain 模板变量坑（本项目实测踩过）：`ChatPromptTemplate.from_messages` "
                          "会把消息里的 `{xxx}` 当占位符。凡是“内容来自用户/文档/检索结果”的动态正文，"
                          "一律先渲染好再直传模型；模板只用于变量完全可控的内部提示词。")
    S.h3(doc, "12.2 SSE 流式协议")
    S.para(doc, "HTTP 无法“半截返回”，SSE（Server-Sent Events）用 `text/event-stream` 分帧推送："
                "每个事件一行 `data: {json}\\n\\n`。前端 fetch + `ReadableStream` 边收边渲染。")
    S.code_file(doc, "app/api/chat.py", start=54, end=77)
    S.bullet(doc, "事件类型：`meta`（先推来源，用户马上看到引用）→ `token`（逐字正文）→ `done`/`error`；")
    S.bullet(doc, "生成阶段任何异常都转成 `error` 事件，**不要断流无提示**；前端要保留错误信息，"
                  "不能拿“无输出”兜底文案把它盖掉（已修复）；")
    S.bullet(doc, "头里加 `X-Accel-Buffering: no`：避免 Nginx 等反向代理缓冲导致前端“半天不出字”。")
    S.callout(doc, "warn", "教学里 SSE 用 POST（携带 body），浏览器原生 EventSource 只支持 GET —— "
                          "所以前端用 fetch 流式读 body，这也是生产常见做法。")
    S.callout(doc, "tip", "没配 LLM key 时，`/api/debug/prompt` 能返回“将发给 LLM 的完整消息”，"
                         "零成本检查检索→重排→拼上下文是否正常 —— 排查 RAG 问题先看它。")
