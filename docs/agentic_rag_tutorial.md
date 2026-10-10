# Agentic RAG 企业级知识库问答与决策系统

## 改造全流程详解 · 每一步做什么 · 代码知识点巩固 · 指标前后对比 · 避坑与面试话术

> [star] 全文所有指标都来自项目内的自动评测脚本（scripts/eval_agentic.py），你可以用自己的知识库重跑一遍得到属于你自己的数字。本文档由 scripts/build_agentic_rag_doc.py 从评测报告自动生成，改代码后重新生成即可保持数据同步。

---

# 第一部分　为什么要从 RAG 升级到 Agentic RAG

## 1.1 先把朴素 RAG 说准确：它是一条写死的单向流水线

```
用户提问
  →（有历史则）用 LLM 把问题改写为独立问题
  → 向量检索 + BM25 稀疏检索
  → RRF 融合
  → cross-encoder 精排取 top-4
  → 拼进上下文（带编号 [n]）
  → 大模型生成带引用的回答
```

这条链路工程上非常稳、成本可控、容易验收，所以它是所有企业 RAG 的起点。但它有四道绕不过去的坎：

1. **检索只有一次机会。** 问法不好（口语化、用上位词、用英文简称）、分块粒度与问题不匹配、同一主题散落在多篇文档 —— 检索一次没命中，后面全是白搭。系统不会“再想想”，因为它没有“想”这个环节。

2. **检索结果不做质检。** top-4 里混进两条不相关的片段，模型照样把它们当资料用，甚至会给它们标上引用编号。这是“看起来在引用、其实在脑补”的典型幻觉来源。

3. **上下文照单全收。** 片段又长又多时会挤占窗口，既涨 token 成本，又让模型在无关内容上“分心”。

4. **生成后没有校验。** 答案是一次性吐出来的，它有没有超出资料范围、引用编号对不对，系统自己不知道。

> [key] 面试时把上面四句话讲出来，比背术语管用得多：它证明你知道 RAG 的**失效模式**（一次检索定生死 / 无质检 / 无预算 / 无校验），而 Agentic RAG 恰好就是围着这四个失效模式长出来的。

## 1.2 Agentic RAG 改的到底是什么

Agentic RAG 的本质不是“多加几个 Agent”，而是**把固定流水线换成带决策的闭环**：在关键节点上让系统自己判断，判断不了的再交给确定性代码兜底。

| 决策点 | 朴素 RAG 的做法 | Agentic RAG 的做法 | 对应失效模式 |
| --- | --- | --- | --- |
| 要不要规划 | 不规划，直接检索 | 先产出任务类型 + 执行计划 + 多条互补检索式 | 一次定生死 |
| 检索几轮 | 固定一轮 | 最多 N 轮：判定不足 → 改写检索式 → 再检 | 一次定生死 |
| 结果要不要 | 全要 | 逐条判定相关性，只让相关资料进上下文 | 无质检 |
| 上下文怎么装 | 有多少塞多少 | 按分数排序 + 字符预算裁剪 + 条件触发压缩 | 无预算 |
| 答完算不算完 | 算完 | 生成后做忠实度自检，发现无依据陈述就标注 | 无校验 |
| 能力从哪来 | 写死的函数调用 | 工具注册表（6 个正交工具，JSON Schema 契约） | 扩展性 |
| 过程看得见吗 | 只有最终答案 | 每步都是结构化事件，可推前端 / 可记账 / 可评测 | 可观测性 |

注意最后一列：**每一个改动都对应一个具体的失效模式**。这也是判断“要不要上 Agent”的标准 —— 如果你的系统不存在这些失效模式（比如知识库只有 3 篇干净文档、问题都是单跳事实题），硬上 Agent 只会换来几倍的延迟和成本。

## 1.3 企业级“决策系统”比“问答系统”多出来的那一层

“知识库问答”和“知识库决策”是两个不同的交付物：

- 问答要的是**答案**：一句准确的话，带引用，能核对。
- 决策要的是**可执行、可追责的结构化建议**：结论、依据、风险、行动项，而且每条依据都能追溯到原文。

所以本项目在问答之外多了一个 `decision_memo` 工具：当规划器把问题识别为 decision 类（“该怎么做 / 选哪个方案 / 给份建议”）时，先产出一份结构化备忘录，再据此组织自然语言回答。这就是“问答系统”和“决策系统”在工程上的分界线。

> [tip] 判断一个 Agent 是不是“企业级”，看三点：① 关键结论能不能追溯到原文（可审计）；② 每一步有没有计量（可核算成本）；③ 模型抽风时流程会不会崩（可兜底）。三点都答“能”，才谈得上企业级。

---

# 第二部分　改造后的系统长什么样

## 2.1 数据流全景

```
                    ┌──────────────────── 离线：知识沉淀 ────────────────────┐
 上传 PDF/docx/md ─▶ 解析(按页) ─▶ 中文分块(重叠) ─▶ Embedding ─▶ 向量库(FAISS/Qdrant)
                    │                                      + JSONL 原文与出处(下标对齐)
                    └───────────────────────────────────────────────────────┘

                    ┌──────────────────── 在线：Agent 编排 ──────────────────┐
 用户提问
   │
   ├─① 规划 Plan ─────── LLM：任务类型(qa/decision/stats/chitchat) + 计划 + 检索式
   │
   ├─② 检索 Act ──────── knowledge_search → 向量+BM25+RRF+cross-encoder → 证据池
   │
   ├─③ 判定 Grade ────── LLM：这些资料够不够？哪些相关？还缺什么？   ← 防幻觉闸门 1
   │        │
   │        ├─ 不够 → ④ 反思 Reframe：query_rewrite 换检索式 → 回到 ②
   │        └─ 够了 / 强证据提前收束 → 继续
   │
   ├─⑤ 压缩 Compress ─── 条件触发：去重去噪 + 字符预算裁剪（省 token）
   │
   ├─⑥ 成文 Memo ─────── decision 类问题：结论/依据/风险/行动项（决策交付物）
   │
   ├─⑦ 生成 Answer ───── 证据为空 → 直接拒答（不调模型）；否则流式生成带 [n] 引用
   │
   └─⑧ 校验 Verify ───── LLM：逐句检查是否忠于资料              ← 防幻觉闸门 2
            └─ 未通过 → 答案末尾追加“未找到依据”提示 + 返回 verdict
                    └───────────────────────────────────────────────────────┘
     全过程：SSE 事件流推前端 · 逐节点记账 token/成本 · 每步可单测
```

> [tip] 把这张图画在纸上，你就能回答八成 Agentic RAG 面试题：它在哪一步做了什么决策、为什么需要这个决策、不做会怎样。

## 2.2 新增与改动的文件清单

| 文件 | 类型 | 职责 | 关键设计 |
| --- | --- | --- | --- |
| app/core/agent_state.py | 新增 | 状态与结构化输出模型 | dataclass 存状态、Pydantic 校验 LLM 输出 |
| app/core/agent_tools.py | 新增 | 工具注册表 + 6 个工具 | 统一 JSON Schema 契约；工具失败不炸循环 |
| app/core/agent_nodes.py | 新增 | 7 个 LLM 决策节点 | 结构化输出 + 解析兜底 + 逐节点记账 |
| app/core/agent.py | 新增 | Agent 主循环（状态机） | 受控 Agent：决策点交给模型，控制流用代码 |
| app/core/prompts.py | 扩展 | 控制流提示词（规划/判定/校验/压缩/成文） | 全部强制 JSON 输出 |
| app/core/engine.py | 扩展 | agent_answer / agent_answer_stream | 组合而非继承，返回结构与老链路对齐 |
| app/core/llm_router.py | 扩展 | 三档模型路由 small/default/strong | 档位未配置向上回落，不报错 |
| app/core/token_stats.py | 复用 | 逐节点记账 | task=agent:grade 这样拆开，能算清贵在哪一步 |
| app/api/chat.py | 扩展 | /api/agent/query、/stream、/debug、/tools | 老接口保持兼容，新增 agent 开关 |
| app/static/app.js、index.html、style.css | 扩展 | Agent 轨迹时间线 + 模式开关 | 事件类型映射到图标与左侧色条 |
| scripts/eval_agentic.py | 新增 | 三层指标评测（检索 / 应答 / 幻觉） | 同一标注集跑两条链路做前后对比 |
| scripts/verify_agentic.py | 新增 | Agent 分层验收（A0~A9） | 退出码可直接接 CI |

> [warn] 改造期间最大的工程风险不是“模型不听话”，而是**把老链路改坏了**。所以新增能力全部走新类 / 新方法，老接口只在最外层加一个开关分支 —— 任何时候把 `agent=false` 就能退回原链路，这是能安心重构的前提。

---

# 第三部分　十步改造实录：每一步做什么

| 步骤 | 做什么 | 产出 | 为什么排在这个位置 |
| --- | --- | --- | --- |
| 第 1 步 | 建立评测标准与基线 | 评测集 + 基线报告 | 没有基线，后面所有“提升”都不可信 |
| 第 2 步 | 加可观测性（逐节点记账 + 状态显式化） | AgentState / AgentStep / by_step 用量 | Agent 是黑盒，得先能看见它 |
| 第 3 步 | 规划层与工具契约 | Plan 模型 + ToolRegistry + 6 个工具 | 先想清楚“能用什么工具” |
| 第 4 步 | 检索-判定-反思主循环 | AgentOrchestrator 状态机 | 核心决策闭环 |
| 第 5 步 | 证据过滤（防幻觉闸门 1） | relevant 标记与保守兜底 | 生成前把噪声挡在外面 |
| 第 6 步 | 生成层：短路拒答 + 预算 + 流式 | answer / answer_stream | 有了干净证据才谈生成 |
| 第 7 步 | 忠实度自检（防幻觉闸门 2） | VerifyOutcome + 显式提示 | 生成后再兜一次底 |
| 第 8 步 | 决策备忘录 + 压缩 + 安全计算 | DecisionMemo | 企业级交付物与成本控制 |
| 第 9 步 | API / 前端 / 事件流 | 4 个新接口 + 轨迹面板 | 能力要看得见才有人用 |
| 第 10 步 | 评测对比 + 分层验收 | 对比报告 + verify_agentic | 用数字证明改造有效 |

## 第 1 步｜先立标准：评测集与基线（最关键的一步）

### 做什么

- 建两份标注集：`data/eval_set_agentic.json`（简单集）与 `data/eval_set_hard.json`（困难集）。
- 每道题的字段：`question`、`answerable`（库里到底有没有答案）、`expect_docs`（期望命中的文档）、`ref_keywords`（回答必须覆盖的要点）、`type`、`pre_question`（多轮指代题的前置问题）。
- 写 `scripts/eval_agentic.py`：进程内直调 engine（不走 HTTP，跑得快、可复现），用 LLM 当判官给回答打四分类标签，最后聚合指标。

### 为什么这么做

评测集的设计比代码更难，它是整个改造的**标尺**。三个坑必须避开：

1. **不能全是“一篇文档一个主题”的简单题。** 那种题朴素 RAG 就能拿满分，改造前后没有差异，等于白测。
2. **必须包含“库里没有答案”的题**（本项目两份评测集各放了 5 道幻觉探针）。只测“能不能答对”，会漏掉最危险的一类错误：一本正经地编。
3. **期望文档只有一篇长文档时，“按文档算命中”会失去区分度**（恒为 100%）。必须下沉到内容层：看检索到的正文里有没有回答所需的要点（`evidence_kw_recall`）。

### 关键代码

```
# 四分类判定标签（LLM 判官输出）—— 注意“错误拒答”也要算进幻觉侧
correct        回答切题，且每条事实性陈述都能在资料中找到依据
fabricated     回答切题，但有资料里找不到依据的陈述，或引用了不存在的 [n]
false_refusal  资料本来够用，却回答“资料库中没有找到”（该答不答，也是答案与事实不符）
should_refuse  资料确实不够，回答正确地说明了无法作答（正确行为）

# 三层指标（口径必须写清楚，否则数字没有意义）
retrieval:      evidence_kw_recall / hit@1 / recall@k / MRR
correctness:    (答对 + 正确拒答) / 已判定
hallucination:  (编造 + 错误拒答 + 不该答乱答) / 已判定
```

> [warn] 两个必须写进文档的口径细节：① **错误拒答计入幻觉侧** —— 否则只要让系统“什么都说不知道”，就能把幻觉率刷成 0，指标立刻失去意义；② **判官提示词要强制 JSON 并做解析兜底** —— 判官自己输出格式错乱时返回 unknown，而不是把整场评测搞崩。

> [tip] 跑基线时至少记录五个数：检索指标、应答准确率、幻觉率、平均延迟、单问成本。这五个数是后面所有“提升”的对照物。

## 第 2 步｜加可观测性：让 Agent 的每一步都能被看见

### 做什么

- 定义三个纯数据模型：`AgentStep`（一步动作）、`AgentState`（一次运行的状态），以及面向 LLM 的结构化输出模型（`Plan` / `GradeOutcome` / `VerifyOutcome` / `DecisionMemo`）。
- 每次 LLM 调用都记账到 `UsageStats`，任务名写成 `agent:plan` / `agent:grade` / `agent:answer`……
- 每一步都追加到 `state.steps` 并 yield 成 SSE 事件。

### 关键代码

```
# app/core/agent_state.py（节选）
@dataclass
class AgentStep:                       # 飞行记录仪：一步动作一行记录
    index: int
    kind: Literal["plan", "act", "observe", "grade", "reflect", "verify", "answer", "error"]
    title: str
    detail: str = ""
    tool: str = ""
    args: dict = field(default_factory=dict)
    observation: dict = field(default_factory=dict)
    elapsed_ms: int = 0

@dataclass
class AgentState:                      # 纯数据 → 可序列化、可单测、可回放、可评测
    question: str
    task_type: TaskType = "qa"
    plan_steps: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)     # 每一轮真正用过的检索式
    evidence: list[GradedChunk] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)  # 逐节点用量
```

> [key] 为什么状态要显式建模？因为 Agent 和流水线最大的差别就是**它有多轮、有中间状态**。把状态做成纯数据，就同时拿到三样东西：可观测（能推前端）、可测试（喂状态断言决策）、可评测（指标直接从状态里取，不用重跑一遍检索）。

## 第 3 步｜规划层与工具契约：先想清楚“能用什么”

### 做什么

- 写 `ToolRegistry`：名字 → 描述 + JSON Schema 参数 + 异步实现，支持导出 OpenAI function calling 格式。
- 实现 6 个正交工具：`knowledge_search` / `query_rewrite` / `evidence_compress` / `decision_memo` / `kb_stats` / `calc`。
- 写规划提示词 `AGENT_PLAN_SYSTEM`，要求模型输出 `task_type + intent + steps + search_queries + answer_style`。

### 关键代码

```
# app/core/agent_tools.py（节选）：统一契约 + 失败不炸
class ToolRegistry:
    def register(self, spec: ToolSpec, impl): ...

    def schemas(self) -> list[dict]:                 # 直接喂给 function calling
        return [s.to_openai_schema() for s in self._specs.values()]

    async def call(self, name: str, **kwargs) -> dict:
        impl = self._impls.get(name)
        if impl is None:
            return {"error": f"未知工具：{name}", "available": self.names()}
        try:
            return await impl(**kwargs)
        except Exception as e:                       # 工具失败 → 交回循环决策，不中断
            return {"error": f"{type(e).__name__}: {e}"}
```

> [tip] **工具描述是写给模型看的说明书，不是注释。** 描述里要写清楚“什么时候该用它”（例如：任何需要事实依据的问题都必须先调用它）。工具选不对，九成是描述写得不清楚，而不是模型不行。

> [warn] **工具要窄，不要贪多。** 6 个正交工具比 20 个含糊工具好用得多：工具越多，模型选错的概率越高，schema 占的 token 也越多。真正提升效果的是检索质量与判定反思，不是工具数量。

> [key] 确定性的事不要交给 LLM：知识库统计（kb_stats）、四则运算（calc，白名单校验且不用 eval）、引用编号拼装，全部用代码做。只有需要语义理解的部分才调模型 —— 又稳又省。

## 第 4 步｜主循环：检索 → 判定 → 反思改写（Agent 的心脏）

### 做什么

- 写 `AgentOrchestrator.run()`：一个 async generator，边跑边 yield 事件（这样流式与非流式共用同一套逻辑，只是消费方式不同）。
- 首轮只打最可能命中的那条检索式（省一次检索、轨迹也更好读），后续轮次把多条改写检索式都打出去。
- 每次检索后把结果 merge 进证据池，并按 `chunk_id` 去重（同一片段被两路召回时只留最高分）。
- 判定不足 → `query_rewrite` 生成新检索式 → 下一轮；到达轮数上限时带着现有证据继续，而不是报错。

### 关键代码

```
# app/core/agent.py（主循环骨架）
state = AgentState(question=question, session_id=sid, history_text=history_text)
registry = build_registry(self.engine, state)

plan = await self.nodes.plan(state, question, registry.names())      # ① 规划
yield {"type": "plan", "data": ...}

if state.task_type == "chitchat":                                    # 闲聊直接收场，不烧 token
    ...
    return

for rnd in range(1, state.max_retrieval_rounds + 1):
    turn_queries = state.queries[:1] if rnd == 1 else self._pending_queries
    for q in turn_queries:                                           # ② 检索
        obs = await registry.call("knowledge_search", query=q)
        yield {"type": "tool", "data": ...}

    grade = await self.nodes.grade(state, question, state.evidence)   # ③ 判定（闸门 1）
    ...
    if enough and grade.confidence >= s.agent_grade_min_confidence:
        break
    if relevant and top_score >= s.agent_strong_score:                # 强证据提前收束
        break
    rw = await registry.call("query_rewrite", question=question, missing=grade.missing)  # ④ 反思
    self._pending_queries = rw["queries"]
```

> [key] **“受控 Agent”是这一节最重要的设计决策**：决策点（规划 / 判定 / 校验）交给模型，控制流（循环、上限、兜底、短路）全部用确定性代码。对比“裸 ReAct”（每一步都让模型决定下一步），它在可观测性、稳定性、可评测性、成本可控性上全面占优，代价是灵活性略低 —— 而企业场景要的恰恰是稳定与可控。

> [warn] **一定要有轮数上限。** 判定器偏严时，没有上限的循环会一直检索下去，延迟和成本直接失控。本项目默认 `agent_max_retrieval_rounds=3`。

> [tip] **强证据提前收束（agent_strong_score）是个很划算的小优化。** LLM 判定器天然保守（宁可说不足也不放过噪声），但精排分数已经很高时，再检一轮的边际收益极低。用一条确定性规则（`top_score ≥ 0.55`）提前停机，实测能省下两到四次模型调用。

## 第 5 步｜防幻觉闸门 1：检索结果的逐条相关性判定

### 做什么

- 写判定提示词：要求返回 `sufficient / confidence / missing / relevant_ids / reason`。
- 按 `relevant_ids` 给证据打标：只有 `relevant=True` 的证据才允许进入生成上下文。
- 对判定结果做**保守兜底**：说“够”但没给编号时全部保留；判定器不可用时按“不足”处理。

### 关键代码

```
# 相关性判定的兜底逻辑（宁可多留，不可错杀）
relevant_ids = {str(x).strip() for x in (grade.relevant_ids or [])}
for i, item in enumerate(state.evidence, start=1):
    if grade.sufficient and not relevant_ids:
        item.relevant, item.reason = True, "判定：资料足够（未给编号，保守全留）"
    elif str(i) in relevant_ids:
        item.relevant, item.reason = True, "判定：相关资料"
    else:
        item.relevant, item.reason = False, "判定：与问题不直接相关"
```

> [key] 这对应 CRAG（Corrective RAG）的核心思路：**检索之后先自评，再决定要不要用**。相比“检索完直接塞给模型”，多这一步就能把“话题相近但答不了问题”的噪声挡在上下文之外。

> [warn] 判定器要**严格但可兜底**：严格是指“只是话题相近 → 判不足”；可兜底是指它输出乱格式、超时、或说够却不给编号时，代码能给出保守决策。**LLM 是概率组件，控制流必须比它更确定** —— 这条原则贯穿整个 Agent 实现。

## 第 6 步｜生成层：证据为空就短路拒答 + 上下文预算 + 流式

### 做什么

- **证据为空时不调用模型**，直接返回确定性拒答模板（说明检索了什么、为什么答不了、建议怎么做）。
- 上下文预算：超过 `agent_context_max_chars` 时按分数从高到低裁剪，装不下的片段标记为不相关并记录原因（而不是把句子硬截断）。
- 流式生成（`astream`）逐 token 推送，同时用 `stream_usage` 拿回 token 用量（否则只能按字数估算）。

### 关键代码

```
async def answer(self, state, question, evidence, *, style="", extra="") -> str:
    if not evidence:
        return self._refusal_text(state)      # ★ 关键：证据为空 → 短路，绝不空转模型
    block = format_evidence_block(evidence)
    ...

@staticmethod
def _refusal_text(state) -> str:
    tried = "；".join(state.queries[:3]) if state.queries else "（未执行检索）"
    return (
        "资料库中没有找到相关信息。\n\n"
        f"- 已检索的内容：{tried}\n"
        "- 结论：现有知识库无法支撑该问题的回答，为避免编造，这里不做推测。\n"
        "- 建议：补充相关文档后重新上传入库，或换一种更具体的问法再试。"
    )
```

> [key] **在控制流上短路，比在提示词里写十句“不要编造”都有效。** 让模型在“没有任何资料”时空转，是幻觉率最高的场景；直接不让它开口，这类幻觉就归零了。这条经验可以直接搬到任何 RAG 系统。

> [warn] 流式有个**固有代价**：校验发生在 token 已经推给前端之后，所以校验发现的幻觉无法撤回。本项目的处理是“追加警示 + 返回 verdict”（诚实优于假装）。如果你要“先校验再输出”，就只能放弃流式 —— 这是必须显式做出的取舍。

## 第 7 步｜防幻觉闸门 2：生成后的忠实度自检

### 做什么

- 写校验提示词：给“问题 + 资料 + 回答”，逐句检查事实性陈述是否有资料依据，输出 `grounded / score / unsupported / reason`。
- 校验未通过时，在答案末尾追加“未找到依据”的显式提示，并把 `verdict` 与 `unsupported` 返回给调用方。
- 这一层只做**标注与暴露**，不强行改写答案 —— 因为校验器本身也可能误判。

### 关键代码

```
if s.agent_verify_enabled and state.answer.strip():
    verdict = await self.nodes.verify(state, question, state.answer, evidence)
    state.verdict = "grounded" if verdict.grounded else "ungrounded"
    state.unsupported = verdict.unsupported
    if not verdict.grounded:
        state.answer += self._verify_warning(verdict)
    yield {"type": "verify", "data": ...}          # 推给前端，让用户看得见
```

> [tip] **两把闸门的分工**：闸门 1（判定）管“进去的东西干不干净”，闸门 2（校验）管“出去的东西有没有超纲”。前者省 token、去噪声，后者保正确性。只做其中一个都不够：只做闸门 1，模型仍可能过度推断；只做闸门 2，噪声上下文会干扰生成质量。

> [warn] 校验器输出同样要兜底：本项目在**调用失败时默认放行**（`VerifyOutcome(grounded=True, score=0.5, reason=校验器不可用，放行)`）。为什么不是默认拦截？因为校验器一故障就把全部回答标成“不可信”，系统就完全不可用了 —— 可用性与严格性的取舍要显式写进代码，而不是碰运气。

## 第 8 步｜企业级能力：决策备忘录、证据压缩、安全计算

### 做什么

- `decision_memo`：把证据池变成 `{conclusion, rationale, risks, actions, citations}` 结构化备忘录。
- `evidence_compress`：长问题或方案类问题触发压缩，去重去噪、抽关键句；只改 `compressed` 字段、不改原文（引用仍可回溯）。
- `calc`：白名单四则运算（只允许数字与 `+ - * / ( )`，不使用 eval）。

### 关键代码

```
AGENT_MEMO_SYSTEM = '''你是企业决策支持助手。请依据【参考资料】输出一份结构化决策备忘录。只输出 JSON：
{"conclusion": "一句话结论（必须体现取舍）",
 "rationale": ["支撑结论的依据，2~5 条"],
 "risks": ["风险与不确定性，1~3 条"],
 "actions": ["下一步可执行动作，2~4 条，动词开头"],
 "citations": ["用到的资料编号"]}
硬性要求：
- 所有内容必须有资料依据，资料没提到的一律不写；
- 资料不足时 conclusion 写「资料库信息不足以支撑该决策」，其余字段留空数组。'''
```

> [key] **压缩只改 `compressed`、不改原文**，是为了同时拿到两个相互冲突的目标：省 token（压缩后进上下文）与可审计（引用仍能回溯原文）。凡是“既要又要”的地方，都要靠数据结构设计来解，而不是靠提示词求模型。

## 第 9 步｜接口、事件流与前端：让决策过程看得见

### 做什么

- 新增 `/api/agent/query`（非流式）、`/api/agent/stream`（SSE）、`/api/agent/debug`（只跑规划 + 检索 + 判定，不生成）、`/api/agent/tools`（工具清单）。
- 老接口 `/api/chat` 与 `/api/chat/stream` 增加 `agent` 开关：请求级参数优先于全局配置。
- 前端加 Agent 模式开关 + 推理轨迹时间线：plan / tool / grade / reflect / verify 用不同图标与左侧色条区分。

| SSE 事件 | 触发时机 | 前端怎么用 |
| --- | --- | --- |
| plan | 规划完成 | 渲染“要做什么”与检索式 |
| tool | 每次工具调用后 | 显示检索了什么、命中多少条 |
| grade | 相关性判定后 | 显示“资料够不够”、缺什么 |
| reflect | 改写检索式 / 提前收束 | 显示“为什么再检一轮” |
| answer_start | 开始生成答案 | 准备流式渲染 |
| token | 每个增量片段 | 边收边渲染正文 |
| verify | 忠实度自检后 | 校验未通过时追加警示 |
| final | 全部结束 | 回填来源、用量、Agent 摘要 |
| done / error | 流关闭 / 异常 | 收尾或报错提示 |

> [tip] **过程可见是 Agent 产品化的前提。** 用户看到“它检索了这 5 条、判定说缺 XX 所以又检了一轮”，才会信任最终答案；反之，一个只吐答案的 Agent 在出错时完全无法解释，也没法排查。

> [warn] 复用 `/api/chat` 时要注意**字段兼容**：`agent_answer()` 的返回结构与 `answer()` 保持一致（answer / sources / usage / elapsed_ms），只多一个 `agent` 字段。这样前端和评测脚本只换端点、不改解析逻辑 —— 接口兼容是改造时的工程底线。

## 第 10 步｜评测对比与分层验收：用数字证明改造有效

### 做什么

- 用同一套标注集跑两条链路：`--mode both` 自动输出对比表与 `eval_compare_*.json`。
- 写 `scripts/verify_agentic.py`：A0~A9 十层检查（服务 / 规划 / 检索 / 判定 / 决策 / 引用 / 拒答 / 流式 / 兼容 / 治理）。
- 把指标写进 README 与简历，并把“改了什么、指标怎么变”记成证据链。

### 命令

```
# 1) 前后对比评测（同一评测集跑两条链路，进程内直调，不依赖 HTTP）
.venv\Scripts\python scripts\eval_agentic.py --mode both --tag hard11 ^
    --set data/eval_set_hard.json --limit 11 --top-k 4

# 2) Agent 专项验收（先启动服务）
.venv\Scripts\python -m uvicorn app.main:app --port 8000
.venv\Scripts\python scripts\verify_agentic.py http://127.0.0.1:8000
```

> [key] **“能不能量化”是区分“做过项目”和“写过代码”的分水岭。** 面试时不要只说“我做了 Agentic RAG”，要说“改之前幻觉率 X%、改之后 Y%，同一套标注集、可复现脚本一键跑出来”。
