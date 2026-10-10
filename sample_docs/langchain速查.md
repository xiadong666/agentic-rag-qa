# LangChain 与 LCEL 速查（示例知识库）

LangChain 是构建大模型应用的框架。LCEL（LangChain Expression Language）用管道符 `|` 把组件串成可组合、可流式的链。

## 核心组件

- ChatPromptTemplate：把消息模板和占位符变成真正的消息列表。
- ChatOpenAI：OpenAI 兼容的对话模型封装，换 DeepSeek、千问、智谱只需改 base_url、api_key、model。
- StrOutputParser：把模型的输出对象解析成纯文本字符串。

## LCEL 组合

例如 `chain = prompt | llm | StrOutputParser()`，调用 `chain.invoke({})` 得到最终文本，调用 `chain.astream({})` 逐 token 流式输出，非常适合 SSE 推送前端。

## 文本分割器

RecursiveCharacterTextSplitter 按分隔符优先级递归切分文本。中文场景必须在分隔符列表中加入句末标点（。！？；），否则会把句子拦腰切断。chunk_overlap 让切边界的上下文在下一块保留，提升召回质量。

## 记忆与多轮

做多轮 RAG 有两种路线：把最近几轮原文拼进提示词（简单但占窗口），或先把问题结合历史改写成独立问题再检索（本项目采用，检索词始终完整可检索）。

## 嵌入模型注意点

使用 bge 中文向量模型时，查询语句需要加指令前缀“为这个句子生成表示以用于检索相关文章：”，这是作者训练时定义的非对称用法；文档侧不需要加。
