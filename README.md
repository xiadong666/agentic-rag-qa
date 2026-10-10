# Agentic RAG 企业级知识库问答与决策系统（FastAPI + LangChain）

[![ci](https://github.com/xiadong666/agentic-rag-qa/actions/workflows/ci.yml/badge.svg)](https://github.com/xiadong666/agentic-rag-qa/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.10%20~%203.12-blue)](https://www.python.org/)
[![fastapi](https://img.shields.io/badge/FastAPI-0.141-009688)](https://fastapi.tiangolo.com/)
[![langchain](https://img.shields.io/badge/LangChain-1.2-1C3C3C)](https://python.langchain.com/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

> CI 徽章指向 `xiadong666/agentic-rag-qa`。若你的仓库名或用户名不同，
> 把徽章里的两处路径换成实际地址即可（推送到 GitHub 后徽章才会显示状态）。

面向**找 AI 应用开发实习/工作**的完整教学项目，现在是 **Agentic RAG** 形态：

> 朴素 RAG 是一条写死的流水线（检索一次 → 重排 → 生成）；本项目把它升级成**带决策的闭环**：
> **规划 → 多轮检索 → 相关性判定 → 反思改写 → 生成 → 忠实度自检**，并在此基础上交付
> **企业级决策能力**（结构化决策备忘录）与**治理能力**（逐节点 token/成本记账、推理轨迹可视化）。

数据底座仍是完整的 RAG 链路：文档上传 → 解析 → 分块 → 向量化 → 混合检索（BM25 + 向量 + RRF）
→ cross-encoder 重排 → 带引用与多轮历史的生成，以 Web 服务 + Docker 方式部署。
配套 Word 教程：《Agentic RAG 改造全流程 + 知识点巩固》与《RAG 系统验收方法》。

## ✨ 亮点

| 亮点 | 说明 | 主要代码 |
| --- | --- | --- |
| **Agent 编排** | 受控状态机：规划 → 多轮检索 → 判定 → 反思改写 → 生成 → 自检；决策点交给模型，控制流由代码兜底 | `app/core/agent.py` |
| **检索自评（CRAG 思路）** | 检索后逐条判定相关性，只让相关资料进上下文；分数下限保护防 LLM 误杀高分证据 | `app/core/agent_nodes.py` |
| **防幻觉双闸门** | 闸门 1：生成前过滤证据、无证据直接短路拒答；闸门 2：生成后忠实度自检并标注无依据陈述 | `app/core/agent.py`、`prompts.py` |
| **工具化能力** | 6 个正交工具（检索 / 改写 / 压缩 / 决策备忘录 / 库统计 / 安全计算），统一 JSON Schema 契约 | `app/core/agent_tools.py` |
| **决策交付物** | decision 类问题自动产出「结论-依据-风险-行动项」结构化备忘录 | `app/core/agent_nodes.py` |
| **混合检索** | BM25（自实现，中文分词）+ 稠密向量 + RRF 融合 | `app/core/bm25.py`、`retrieval.py` |
| **重排序** | 召回后 cross-encoder 精排（bce-reranker-base） | `app/core/rerank.py` |
| **引用来源** | 分块记页码 → 命中带出处 → 回答按 [n] 引用 → sources 结构化返回 | `app/core/engine.py`、`prompts.py` |
| **推理轨迹** | 每一步（规划/检索/判定/反思/自检）都是 SSE 事件，前端时间线实时渲染 | `app/api/chat.py`、`static/app.js` |
| **流式输出** | SSE 逐 token 推送 + 前端边收边渲染 | `app/api/chat.py`、`static/app.js` |
| **部署** | uvicorn / Docker / docker-compose | `Dockerfile`、`docker-compose.yml` |

## 🧱 技术栈

FastAPI · Pydantic v2 · LangChain 1.2（langchain-core 1.6 / ChatOpenAI / text-splitters 1.1）·
sentence-transformers（本地中文 bge embedding + 重排模型）· FAISS · pypdf / python-docx / jieba

模型默认：**对话 = DeepSeek（deepseek-chat，OpenAI 兼容）**，**embedding = 本地 BAAI/bge-small-zh-v1.5**（免费、无需 key、可离线），全部可在 `.env` 切换为任意 OpenAI 兼容厂商。

## 📐 架构（数据流）

```
                    ┌──────────────────────── 离线：知识沉淀 ────────────────────────┐
 上传 PDF/docx/md ──▶ 解析(按页) ─▶ 分块(重叠) ─▶ Embedding ──▶ 向量库       离线知识沉淀
                    │                              (FAISS / Qdrant 可切换)   │
                    │                 │                │              ▲      │
                    │                 ▼                ▼              │      │
                    │           JSONL 原文+出处(point id 对齐)         │      │
                    └──────────────────────────────────────────────┘
                                        │
                    ┌──────────────────── 在线：Agent 编排 ─────────────────────┐
 用户提问
   ├─① 规划 Plan ───── LLM：任务类型 + 执行计划 + 多条检索式
   ├─② 检索 Act ────── knowledge_search：向量 + BM25 + RRF + cross-encoder → 证据池
   ├─③ 判定 Grade ──── LLM：资料够不够？哪些相关？还缺什么？   ← 防幻觉闸门 1
   │      ├─ 不足 / 置信度低 → ④ 反思：query_rewrite 换检索式 → 回到 ②（最多 N 轮）
   │      └─ 充分 / 强证据提前收束 → 继续
   ├─⑤ 压缩 Compress ─ 条件触发：去重去噪 + 字符预算裁剪（省 token）
   ├─⑥ 成文 Memo ───── decision 类问题：结论/依据/风险/行动项
   ├─⑦ 生成 Answer ─── 证据为空 → 确定性拒答（不调模型）；否则流式生成带 [n] 引用
   └─⑧ 校验 Verify ─── LLM：逐句检查是否忠于资料           ← 防幻觉闸门 2
                    └───────────────────────────────────────────────────────┘
     事件流：plan → tool → grade → reflect → answer_start → token×N → verify → final
```

### 📊 改造前后实测（同一标注集、两条链路，`scripts/eval_agentic.py --mode both`）

**两套难度不同的评测集**（都含"库里没有答案"的幻觉探针），每套都跑朴素链路与 Agent 链路各一遍：

| 指标 | 简单集：朴素 RAG | 简单集：Agentic | 困难集：朴素 RAG | 困难集：Agentic |
| --- | --- | --- | --- | --- |
| 检索 Hit@1 / Recall@k | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| 证据要点覆盖率 | 70.8% | 67.5% | 95.5% | 93.6% |
| 应答准确率 | 100% | **100%** | 100% | **100%** |
| 生成层准确率 | 60.0% | **64.3%** | 66.7% | **77.8%** |
| 幻觉率 | 0% | **0%** | 0% | **0%** |
| 库外探针误答率 | 0% | **0%** | 0% | 20%（1 例） |
| 平均延迟 | 5.4 s | 26.6 s | 14.2 s | 65.0 s |
| 单问成本 | 0.0018 元 | 0.0098 元 | 0.0023 元 | 0.0171 元 |
| 平均模型调用 | 1~2 次 | 7.7 次 | 1~2 次 | 7.9 次 |

> ⚠️ **诚实结论（重要）**：在小而干净的语料上，朴素 RAG 的单轮检索已经足够好，
> **Agentic RAG 并不会把端到端准确率做得更高**（两边都是 100%、幻觉率都是 0%）。
> 它的收益是：① **生成层质量更高**（+4.3 / +11.1 个百分点，因为证据经过筛选、答案经过忠实度自检）；
> ② **朴素链路结构上不具备的能力**（结构化决策备忘录、推理轨迹、逐节点成本归因、确定性拒答模板）；
> ③ **可定位性**：出错时能看出是哪一层错了，而不是只能重跑。
> 代价是延迟与成本上升数倍 —— 所以接口保留了 `agent` 开关，**按场景路由**：
> 简单事实问答走朴素链路，复杂综合与决策类问题才走 Agent。
>
> 困难集那 1 例"库外探针作答"，是探针题"DeepSeek 接口每百万 token 报价"——
> Agent 先明确写了"资料库中没有找到具体报价数字，因此无法回答"，随后补充了资料里与成本相关的线索，
> 被判官归为 correct。**工程上算合格拒答，但确实比基线啰嗦** —— 这也提醒我们：
> 拒答就该干脆短促，拒答之后不要长篇补充。

**改造过程中被指标抓出的三个真实缺陷**（已修复，详见教程第六部分 6.2）：

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | 库外探针题"QPS 峰值是多少"被答成"知识库有 4 篇文档" | 规划器误判为 `stats` 类，走了确定性统计分支（连模型都没调） | 加**确定性口径守卫**：必须是"问知识库清单/数量"才放行走统计 |
| 2 | 判定器把含关键词的高分证据误杀（1921 字 → 459 字），回答缺要点 | LLM 按"单条能否回答"裁，多跳问题需多条拼起来 | **分数下限保护 + 分情况下限**（判定"不足"时更宽松） |
| 3 | 压缩节点连续两次 `输出不是合法 JSON`，静默降级 | 该返回对象却返回了数组 | 解析器兼容数组 + 提示词写死输出形状；兜底保证流程不崩 |

> 💡 完整方法论（十步改造实录、指标口径、避坑清单、面试话术）见
> `docs/Agentic_RAG_企业级知识库问答与决策系统_改造全流程教程.docx`，
> 一页纸版见 `docs/Agentic_RAG_改造指标速记卡.docx`。

### 🧠 AI 中台能力（JD 高频考点，本项目已实现）

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| **模型路由** | 三档路由：`small`（规划/判定/改写/压缩，省钱）、`default`（生成答案）、`strong`（决策备忘录）；档位未配置自动向上回落 | `GET /api/stats/routes` |
| **Token 统计与成本** | 统一记录任务/模型/输入输出 token/成本/会话；**Agent 逐节点记账**（`agent:plan`、`agent:grade`…），能算清贵在哪一步 | `GET /api/stats/summary` |
| **向量库双后端** | 同一 `VectorStore` 契约：FAISS（进程内）与 Qdrant（本地/服务模式）配置切换，自动降级 | `VECTOR_BACKEND=faiss\|qdrant` |
| **验收与评测** | 朴素链路分层验收 21 项 + **Agent 专项验收 22 项（A0~A9）** + 检索指标评测 + 双后端验收 + **前后对比评测** | `scripts/verify_all.py`、`verify_agentic.py`、`eval_retrieval.py`、`eval_agentic.py` |

```bash
# 启用 Qdrant 本地模式（无需 Docker）或服务模式
VECTOR_BACKEND=qdrant QDRANT_PATH=./data/qdrant  .venv/Scripts/python -m uvicorn app.main:app --port 8000
docker run -d -p 6333:6333 qdrant/qdrant   # 服务模式：再设 QDRANT_URL=http://localhost:6333
```


## 🧪 困难语料：用来测"检索准不准、回答相不相关"

`sample_docs/` 下那 3 篇速查文档（每篇 2 个分块、一篇一个主题）太干净，**测不出短板**。
因此额外提供一批**故意做难**的企业内部语料 `sample_docs/hard/`（7 篇 / 32 个分块），
每篇主打一类真实检索难点：

| 文件 | 难在哪 |
| --- | --- |
| 01_网关与鉴权接入说明.md | 同一参数出现 5000/3000/800，只有 800 是默认值；术语有历史改名 |
| 02_API变更记录.md | 分页参数跨 7 个版本改名 3 次（page→offset→cursor），必须"以最新为准" |
| 03_数据平台运维手册.md | 关键阈值埋在第 6 节中部；三条告警的处置动作容易互相混淆 |
| 04_支付服务接口规范.md | 金额单位是"分"；状态机 7 个状态；签名 4 步含 3 个常见错误 |
| 05_部署与发布SOP.md | 与 01/06 都讲"上线"，但只有本文有回滚判据 → 考语义干扰下的路由 |
| 06_Nexus_Gateway_Integration_Guide_EN.md | 与 01 同主题的中英两份，配额/有效期表述有差异 |
| 07_线上问题登记表.csv | 答案要按"服务名+可重试+时间最新"三个条件筛出来，不是语义匹配能解决 |

配套 `sample_docs/hard/test_cases.json`：**14 道带预期答案的题**（含 3 道"库里确实没答案"的幻觉探针），
每题写明期望命中的文档与回答必须覆盖的要点 —— 这样"回答是否相关"就是可判定的，而不是凭感觉。

```bash
# 灌困难语料并逐题验收（检索命中 + 要点覆盖 + 探针拒答）
.venv\Scripts\python scripts\seed_hard_corpus.py --base http://127.0.0.1:8000 --purge

# 连"回答是否相关"一起验收（会调用 LLM；先用 --limit 3 或 --only E12,E13,E14 小范围试）
.venv\Scripts\python scripts\seed_hard_corpus.py --base http://127.0.0.1:8000 --skip-upload --ask

# 生成 PDF 版语料（需 reportlab），其中 99_扫描件_无文本层.pdf 应触发 OCR 报错，属预期
.venv\Scripts\python scripts\seed_hard_corpus.py --make-pdf

# 接进评测框架，做"朴素 RAG vs Agentic RAG"对比
.venv\Scripts\python scripts\make_hard_eval_set.py
.venv\Scripts\python scripts\eval_agentic.py --mode both --tag hardcorpus ^
    --set data/eval_set_hardcorpus.json --top-k 4
```

> 💡 为什么"难"要刻意设计：**精确标识符**（错误码/字段名）考 BM25 是否真的生效；
> **版本冲突**考会不会用旧值；**长文埋点**考单轮 top-4 是否漏证据；
> **口语 vs 术语**考查询改写；**语义干扰**考重排是否能选出真正相关的那篇；
> **中英混排**考跨语言召回；**探针题**考会不会一本正经地编。
> 换句话说，这批语料本身就是一份"检索失效模式清单"。

**要求**：Python 3.10 ~ 3.12（本项目验证于 3.10 与 3.11）

```bash
# 1. 准备环境
cp .env.example .env            # 修改 LLM_API_KEY=sk-xxx（DeepSeek 等任意 OpenAI 兼容）
powershell -ExecutionPolicy Bypass -File scripts/install.ps1   # Windows
# bash scripts/install.sh                                       # Linux/macOS

# 2.（可选）灌入 3 篇内置示例文档，离线即可体验检索/重排
.venv\Scripts\python scripts\seed_demo.py

# 3. 启动 Web 服务
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 4.（可选）端到端冒烟：检索→重排→上传→删除（无需 LLM key）
.venv\Scripts\python scripts\smoke_api.py http://127.0.0.1:8000
```

打开 http://127.0.0.1:8000 —— 三栏界面：左上传/管理知识库，中问答（流式），右引用来源。

> 模型默认**纯离线加载**（`HF_HUB_OFFLINE=1`），只读项目 `data/hf/` 缓存（首次使用会自动下载
> embedding ~95MB + 重排 ~430MB 到该目录，下载后即可断网使用，`data/` 可随项目整体拷贝复用）。
> 模型下载/更换走国内镜像 `https://hf-mirror.com`（避免直连 huggingface.co 被墙）。
> 如需联网下载新模型（如换成 bge-m3）：在 `.env` 设 `HF_HUB_OFFLINE=false` 后重启；也可用
> `HF_ENDPOINT` / `HF_HOME` 覆盖镜像与缓存目录。
> 已处理：启动时在导入任何 langchain/transformers 之前写好 HF 环境变量（`app/core/engine.py` 顶部），
> 不会因“联网常量固化”而在启动/提问时报 WinError 10051。

### Docker 部署

```bash
cp .env.example .env
docker compose up -d --build      # http://127.0.0.1:8000
```

## ✅ 如何验证系统是对的

RAG“能回答”不等于“对”，Agent“会思考”更不等于“思考对了”。本项目按
**数据 / 检索 / 组装 / 生成 / 工程 / 决策** 六层验收，并附带可运行脚本：

```bash
# 分层一键验收（L0~L7：健康、数据一致、入库、检索、上下文、生成、多轮、鲁棒性）
.venv\Scripts\python scripts\verify_all.py http://127.0.0.1:8000

# Agent 专项验收（A0~A9：服务/规划/检索/判定/决策轨迹/引用/拒答/流式/兼容/治理）
.venv\Scripts\python scripts\verify_agentic.py http://127.0.0.1:8000

# 检索质量量化：小标注集 → Recall@1 / Recall@3 / MRR
.venv\Scripts\python scripts\eval_retrieval.py http://127.0.0.1:8000 --k 3

# Agentic RAG 前后对比：检索准确率 / 应答准确率 / 幻觉率 / 成本延迟
.venv\Scripts\python scripts\eval_agentic.py --mode both --tag easy
.venv\Scripts\python scripts\eval_agentic.py --mode both --tag hard ^
    --set data/eval_set_hard.json --top-k 4

# 轻量冒烟：上传→检索→删除
.venv\Scripts\python scripts\smoke_api.py http://127.0.0.1:8000
```

- 两个验收脚本退出码 **0 = 无 FAIL**（未配 LLM key 时生成层自动 SKIP），可直接接 CI；
- 详细方法论、失败症状对照表、可打印验收清单、面试话术见 `docs/` 下的 Word 教程。

## 🔌 API 一览（启动后 http://127.0.0.1:8000/docs 有交互文档）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/documents/upload` | 上传文档并入库（multipart） |
| GET | `/api/documents` | 文档列表 |
| DELETE | `/api/documents/{doc_id}` | 删除文档（自动重建索引） |
| POST | `/api/search` | 只检索（混合检索 + 重排），调试用 |
| POST | `/api/chat` | 统一问答入口（`agent=true/false` 切换链路，默认跟随配置） |
| POST | `/api/chat/stream` | 统一问答（SSE 流式，两种链路的事件都兼容） |
| POST | `/api/agent/query` | **Agentic RAG 问答**（非流式，返回轨迹 + 逐节点用量 + 决策备忘录） |
| POST | `/api/agent/stream` | **Agentic RAG 问答**（SSE：plan/tool/grade/reflect/verify/final） |
| POST | `/api/agent/debug` | Agent 调试：只跑规划 + 检索 + 判定，**不生成**（排查第一站） |
| GET | `/api/agent/tools` | Agent 工具清单 + 模型路由表 + 关键开关 |
| POST | `/api/debug/prompt` | 调试彩蛋：不花钱查看“将发给 LLM 的消息” |
| GET | `/api/stats/summary` | Token/成本聚合（含 `agent:*` 逐节点明细） |
| GET | `/health` | 健康检查（含 Agent 能力自述） |

## 🗂 目录结构（对应教程章节）

```
rag-qa-system/
├─ app/
│  ├─ main.py            # FastAPI 入口/生命周期/CORS/静态页
│  ├─ config.py          # pydantic-settings 配置中心（含 Agent 轮数/阈值/预算）
│  ├─ schemas.py         # Pydantic 请求/响应模型（含 Agent 轨迹与证据模型）
│  ├─ api/               # 路由层（薄）：documents.py / chat.py / stats.py
│  ├─ core/              # 业务核心（纯逻辑，可单测）
│  │  ├─ parsing.py      # PDF/docx/txt/md 解析
│  │  ├─ chunking.py     # 中文友好分块（重叠 + 页码溯源）
│  │  ├─ embeddings.py   # 本地 bge / OpenAI 兼容 双实现
│  │  ├─ vector_store.py # FAISS 封装（内积=余弦）
│  │  ├─ qdrant_store.py # Qdrant 后端（同接口，可配置切换）
│  │  ├─ bm25.py         # BM25 稀疏检索（自实现）
│  │  ├─ retrieval.py    # 混合检索 + RRF 融合
│  │  ├─ rerank.py       # cross-encoder 精排
│  │  ├─ memory.py       # 会话/多轮历史
│  │  ├─ prompts.py      # 提示词集中管理（回答提示词 + 控制流提示词）
│  │  ├─ llm.py          # ChatOpenAI 装配
│  │  ├─ llm_router.py   # 模型路由（small/default/strong 三档）
│  │  ├─ token_stats.py  # Token 统计与成本核算（逐节点）
│  │  ├─ store.py        # JSONL 知识库持久层
│  │  ├─ engine.py       # RAG 编排（朴素链路）+ Agent 入口
│  │  ├─ agent_state.py  # ★ Agent 状态与结构化输出模型
│  │  ├─ agent_tools.py  # ★ 工具注册表 + 6 个工具
│  │  ├─ agent_nodes.py  # ★ LLM 决策节点（规划/判定/校验/压缩/成文）
│  │  └─ agent.py        # ★ Agent 主循环（受控状态机）
│  └─ static/            # 原生三栏前端（含 Agent 推理轨迹时间线）
├─ sample_docs/          # 内置示例文档（离线演示）
├─ scripts/
│  ├─ install / seed_demo / smoke_api            # 安装、灌库、冒烟
│  ├─ verify_all.py / verify_agentic.py          # 分层验收（朴素 / Agent）
│  ├─ eval_retrieval.py / eval_agentic.py        # 检索指标 / 前后对比评测
│  ├─ gen_eval_candidates.py                     # 从真实语料自动出评测候选题
│  ├─ docx_builder.py / md_to_docx.py            # Word 排版引擎（Markdown → docx）
│  └─ build_agentic_rag_doc.py                   # 生成《改造全流程教程》Word
├─ requirements.txt / .env.example / Dockerfile / docker-compose.yml
└─ docs/                 # Word 教程 + 评测数据集说明
```

## ⚠️ 常见问题

- **上传扫描版 PDF 报“未解析出文本”**：图片型 PDF 需要 OCR（教程 Step2 有说明）。
- **上传 CSV / JSON 被 400 拦掉**：`ALLOWED_EXTENSIONS` 里没放开（解析器本身支持 csv/json）。
  ⚠️ 这里有一个**真实踩过的坑**：pydantic-settings 是**按字段名**映射环境变量的，
  字段名与 `.env` 变量名必须**逐字一致**。曾因为字段叫 `allowed_extensions_raw`
  而 `.env` 写 `ALLOWED_EXTENSIONS`，导致这一行**静默失效**（不报错、不警告），
  一直使用代码默认值 —— 直到需要 csv 时才暴露。现在两者一致
  （`allowed_extensions` ↔ `ALLOWED_EXTENSIONS`）。排查同类问题可用一键自检：

  ```powershell
  .venv-rag\Scripts\python.exe scripts\check_env.py
  ```
- **首次回答很慢**：本地 embedding/重排模型首次加载需下载权重；之后会缓存。
- **Windows 下 pip 装 requirements 报编码错**：requirements.txt 必须保持 ASCII（不要写中文注释）。
- **想换模型厂商**：embedding 改 `EMBEDDING_PROVIDER=openai` + base_url/api_key/model；
  对话改 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 三件套即可。
  Agent 的三档路由用 `LLM_SMALL_MODEL / LLM_STRONG_MODEL` 配置，留空即回落到主模型。
- **Agent 太慢/太贵**：① 配 `LLM_SMALL_MODEL`（判定/改写/压缩走小模型，省最多）；
  ② 调低 `AGENT_MAX_RETRIEVAL_ROUNDS`；③ 调高 `AGENT_STRONG_SCORE`（更早收束）；
  ④ 简单场景直接 `agent=false` 走朴素链路。用 `GET /api/stats/summary` 看 `agent:*` 分节点明细定位开销。
- **Agent 把有用的资料过滤掉了**：这是判定器（LLM）误杀，已内置**分数下限保护**
  （`AGENT_SCORE_FLOOR_RATIO`，默认 0.55：分数接近本批最高分的片段即使被判"不相关"也保留）。
  仍嫌保守就把该系数调大。
- **Agent 说"资料不足"但库里其实有**：用 `POST /api/agent/debug` 看判定器的 `missing` 字段，
  它会直接告诉你缺什么；再据此改判定提示词或调整分块粒度。
- **没有 LLM key 也能玩**：`/api/search` 与 `/api/debug/prompt` 覆盖“检索→重排→拼上下文”
  全程；配置 key 后 `/api/chat` 才真正生成回答（Agent 链路同样需要 key）。
- **网页问答“无输出”/空回答**：多半是检索正文里的 `{item_id}` 这类花括号被
  `ChatPromptTemplate` 误当模板变量导致报错（本项目已修复：预渲染消息直接 `ainvoke/astream`）。
  若仍复现，把后端终端日志贴出来即可定位。

## 📖 配套教程

`docs/` 下有四份 Word：

1. **《Agentic RAG 企业级知识库问答与决策系统 —— 改造全流程 + 知识点巩固》**（本项目的核心文档）：
   十步改造实录（每步：做什么/为什么/关键代码/注意点）、代码知识点全盘点、
   指标口径与前后对比实测、避坑清单、面试话术与高频追问。
2. **《RAG 知识库问答系统——从零到可部署的学习巩固教程》**（朴素链路的完整实现讲解）。
3. **《如何验证 RAG 知识库问答系统是正确的》**（分层验收方法论 + 实测指标 + 验收清单）。
4. **《AI 应用开发（Agent）面试题库》**（170 题：RAG 项目深挖 / RAG 通用知识 / Agent / 手撕与软性题）。

> 第 1 份是**数据驱动**生成的：指标直接从 `data/eval_compare_*.json` 读取，
> 重新跑评测后执行 `python scripts/build_agentic_rag_doc.py` 即可让文档与实测数据保持同步。
