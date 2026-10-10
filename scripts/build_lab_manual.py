"""生成《Agentic RAG 项目实操手册：跑起来 · 改参数 · 弄坏它》。

定位：面向"想亲手把系统跑一遍、并通过破坏它来理解它"的实操手册。
    与其它文档的分工：
      《改造全流程教程》—— 讲**怎么改**（设计决策与知识点）
      《验收方法》      —— 讲**怎么验**（分层清单与指标口径）
      《本手册》        —— 讲**怎么动手**（精确命令、预期输出、故障现象与恢复）

设计原则：
    1. 每个实验都写成"四段式"卡片：改什么 → 怎么执行 → 看什么 → 结论/考点；
    2. 所有命令都是可直接粘贴的 PowerShell（含预期输出，便于对照）；
    3. 全程使用**独立实验目录**，不污染主数据；每个故障实验都给出恢复步骤。

用法：
    .venv-rag\\Scripts\\python scripts\\build_lab_manual.py
    # 受限环境可先输出到有权限的目录：--out D:\\...\\xxx.docx
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.docx_builder import C_MUTED, C_PRIMARY, Doc  # noqa: E402

OUT = ROOT / "docs" / "Agentic_RAG_项目实操手册_跑起来改参数弄坏它.docx"


def exp_card(d: Doc, no: str, title: str, rows: list[tuple[str, str]]) -> None:
    """一个实验卡片：标题 + 四段式（改什么/怎么做/看什么/结论）。"""
    d.h2(f"{no}　{title}")
    for label, body in rows:
        if label in ("结论", "考点"):
            d.box("key", f"**{label}：**{body}")
        elif label == "坑":
            d.box("warn", body)
        else:
            d.para(f"**{label}：**{body}", indent=0.2, after=2, md=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    d = Doc(title="Agentic RAG 项目实操手册",
            subtitle="跑起来 · 亲手改参数 · 故意弄坏它看日志 —— 精确到可直接粘贴的实验步骤",
            margin_cm=1.8)
    d.footer_page_number("Agentic RAG 项目实操手册 · 跑起来 / 改参数 / 弄坏它")

    # ============================================================ 使用说明
    d.h2("这份手册怎么用")
    d.para("它是一份**动手实验手册**：不解释设计原理（那部分在《改造全流程教程》里），"
           "只回答三个问题 —— 怎么把它跑起来、改哪个参数会看到什么变化、故意弄坏它时它会怎么反应。")
    d.table(
        ["章节", "内容", "适合什么时候看", "预计用时"],
        [
            ["第零章", "环境准备 + 三条验证路径 + 看事件流", "第一次跑这个项目", "20 分钟"],
            ["第一章", "8 组参数实验（分块 / 重排 / RRF / 轮数 / 闸门 / A/B）", "想建立参数体感", "40 分钟"],
            ["第二章", "7 个故障注入实验（含恢复步骤）", "想理解异常路径与兜底", "40 分钟"],
            ["第三章", "日志症状 → 病因速查表 + 三个第一站", "真正遇到问题时", "随时查"],
            ["第四章", "配置项速查 + 一个必须修的安全问题", "准备交付 / 上线前", "10 分钟"],
        ],
        widths=[1.2, 4.6, 3.4, 1.4])
    d.box("warn", "**安全提示**：本手册所有实验都在 `experiments/data` 这个**独立目录**里做，"
                  "不碰你的主数据 `data/`。第二章的故障注入会「故意弄坏东西」，"
                  "每个实验都给了恢复命令；做完记得执行第零章的收尾清理。")

    # ============================================================ 第零章
    d.h1("第零章　把它跑起来", number="")

    d.h2("0.1 一次性环境准备")
    d.para("全程使用 PowerShell。**注意解释器路径**：项目里 `.venv` 已失效（其 pyvenv.cfg 指向的 "
           "minconda3 已不存在），必须用 `.venv-rag`。")
    d.code("""
# 0.1 进入项目
cd D:\\Deepseek\\dsh\\rag-qa-system

# 0.2 确认解释器（应为 Python 3.10.4）
.venv-rag\\Scripts\\python.exe -V

# 0.3 建独立实验目录（隔离数据，实验完可直接删）
New-Item -ItemType Directory -Force -Path experiments\\data  | Out-Null
New-Item -ItemType Directory -Force -Path experiments\\logs  | Out-Null

# 0.4 关键环境变量（同一窗口里执行；新开窗口要重新设置）
$env:HF_HOME  = "D:\\Deepseek\\dsh\\rag-qa-system\\data\\hf"
$env:DATA_DIR = "D:\\Deepseek\\dsh\\rag-qa-system\\experiments\\data"
""")
    d.box("warn", "**为什么 DATA_DIR 必须传绝对路径**：配置里的 `DATA_DIR=./data` 是相对**当前工作目录**"
                  "解析的。换个目录启动脚本，它会去找 `那个目录\\data\\kb.jsonl` 然后报 "
                  "`FileNotFoundError` —— 这是相对路径的经典坑，不是代码 bug，"
                  "也是新手在「跑不起来」上浪费最多时间的地方。")

    d.h2("0.2 第 1 条验证路径：不启服务，30 秒确认链路是通的")
    d.code("""
# 灌入 3 篇示例文档
.venv-rag\\Scripts\\python.exe scripts\\seed_demo.py
""")
    d.para("**期望输出**（每篇文档一行，最后汇总）：")
    d.code("""
ingest: fastapi速查.md ...
  [OK] fastapi速查: 712 chars -> 2 chunks (xxxx ms)
ingest: langchain速查.md ...
  [OK] langchain速查: xxx chars -> 2 chunks (xxxx ms)
ingest: rag原理速查.md ...
  [OK] rag原理速查: xxx chars -> 2 chunks (xxxx ms)

KB now: 3 docs, 6 chunks.
Try: POST /api/search  {"question": "混合检索为什么用RRF？"}
""")
    d.para("再直接调引擎测检索（**不花 LLM 的钱**）：")
    d.code("""
.venv-rag\\Scripts\\python.exe -c @"
import asyncio, sys
sys.path.insert(0, '.')
from app.config import get_settings
from app.core.engine import RAGEngine

async def main():
    s = get_settings()
    e = RAGEngine(s); await e.initialize()
    hits = await e.search('混合检索为什么用 RRF 融合？', top_k=3)
    for h in hits:
        print(f'[{h.cite_index}] {h.doc_title} p{h.page} score={h.score}  {h.snippet[:40]}')

asyncio.run(main())
"@
""")
    d.para("**期望**：3 条命中，第一条是《rag原理速查》，`score` 是 0.5 左右的正数"
           "（cross-encoder 的 logits，可正可负，越大越相关）。")

    d.h2("0.3 第 2 条验证路径：启动 Web 服务")
    d.code("""
.venv-rag\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level debug
""")
    d.para("**期望的关键日志行**：")
    d.code("""
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
RAG engine ready: docs=3 chunks=6 rerank=on
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
""")
    d.box("tip", "`RAG engine ready: docs=3 chunks=6 rerank=on` 就是**第一条健康证据**。"
                 "如果显示 `docs=0`，先别改代码 —— 九成是 `DATA_DIR` 没生效或没灌库。")

    d.h2("0.4 第 3 条验证路径：三个入口逐个点一遍")
    d.table(
        ["入口", "命令 / 地址", "看什么", "不该出现什么"],
        [
            ["健康检查", "curl http://127.0.0.1:8000/health",
             "status=ok、docs/chunks 数量、agent.tools 六个工具", "docs 为 0"],
            ["三栏界面", "http://127.0.0.1:8000",
             "左：知识库列表；中：问答；右：推理轨迹 + 引用来源", "右上角显示「后端不可用」"],
            ["Swagger", "http://127.0.0.1:8000/docs",
             "所有接口可分组的交互调试页", "缺 /api/agent/* 四个接口"],
            ["只检索", 'POST /api/search {"question":"...","top_k":3}',
             "命中片段带 doc_title / page / score / cite_index", "hits 为空"],
            ["看真实提示词", 'POST /api/debug/prompt {"question":"..."}',
             "messages 里有【参考资料】与 [1] 编号", "编号后跟的是不相关文档"],
        ],
        widths=[1.4, 3.4, 3.6, 2.4])

    d.h2("0.5 看 Agent 的决策过程（两个不花钱 / 少花钱的接口）")
    d.code("""
# ① 只跑"规划 + 检索 + 判定"，不生成答案 —— 排查 Agent 问题的第一站
curl.exe -s -X POST http://127.0.0.1:8000/api/agent/debug ^
  -H "Content-Type: application/json" ^
  -d "{\\"question\\":\\"混合检索为什么用 RRF？\\"}"

# ② 完整 Agent 问答（会花钱，约 0.01 元/次），把 JSON 格式化后看
curl.exe -s -X POST http://127.0.0.1:8000/api/agent/query ^
  -H "Content-Type: application/json" ^
  -d "{\\"question\\":\\"RRF 的 k 取多少？为什么不用加权求和？\\"}" | .venv-rag\\Scripts\\python.exe -m json.tool
""")
    d.para("第 ① 个接口重点看四个字段：`task_type`（应为 `qa`）、`queries`（规划出的 2~3 条检索式）、"
           "`sufficient` 与 `missing`（判定器认为够不够、缺什么）。")
    d.para("第 ② 个接口重点看 `agent.steps` 的 `kind` 序列，正常长这样：")
    d.code("""
plan → act → grade → reflect → act → act → grade → answer → verify
（规划）（检索）（判定）（反思改写）（再检索）（再判定）（生成）（忠实度自检）
""")

    d.h2("0.6 在终端直接看流式事件（理解 SSE 最快的方式）")
    d.code("""
curl.exe -N -s -X POST http://127.0.0.1:8000/api/agent/stream ^
  -H "Content-Type: application/json" ^
  -d "{\\"question\\":\\"知识库里有哪些文档？\\"}"
""")
    d.para("`-N` 关闭缓冲，你会看到逐行输出：`data: {\"type\":\"plan\"...}` → `tool` → `token`… → `final`。"
           "这条命令比开浏览器更能看清「事件流到底是什么」。")

    # ============================================================ 第一章
    d.h1("第一章　亲手改参数：8 组实验", number="")
    d.box("note", "**通用规则**：改 `.env` 后必须**重启服务**（配置用 `lru_cache` 单例缓存，"
                  "热改不生效）；改完先用 `curl /health` 或 `/api/stats/routes` 确认参数真的生效了。"
                  "每组实验做完，记得把参数改回基线值。")

    exp_card(d, "实验 A", "分块粒度：最影响检索效果的超参数", [
        ("改什么", "`.env` 里 `CHUNK_SIZE` 与 `CHUNK_OVERLAP`"),
        ("怎么做", "先清空实验库，再把分块改成极碎（80/0），重启 → 重新灌库 → 观察"),
        ("看什么", "`/health` 的 chunks 数量、`/api/search` 命中片段是否被「拦腰砍断」、"
                  "`/api/stats/summary` 的 prompt_tokens（上下文变碎 → 要更多片段才够）"),
        ("结论", "chunk 太小 → 命中准但上下文碎、答案缺前因后果；chunk 太大 → 命中糙、噪声多、成本高。"
                "本项目基线 500/50 是在 4 篇文档（含 1 篇 66 分块长文档）上把「证据要点覆盖率」做到 95.5% 的取值。"),
    ])
    d.code("""
# 清空实验库（保证干净）
Remove-Item experiments\\data\\kb.jsonl, experiments\\data\\vectors.index -ErrorAction SilentlyContinue

# 改 .env：极碎分块
#   CHUNK_SIZE=80
#   CHUNK_OVERLAP=0
# 重启服务后：
.venv-rag\\Scripts\\python.exe scripts\\seed_demo.py
curl.exe -s http://127.0.0.1:8000/health          # chunks 从 6 涨到 20 左右

# 再改 .env：极大分块
#   CHUNK_SIZE=2000
#   CHUNK_OVERLAP=100
# 重启 + 清库 + 重新灌：
# chunks 掉到 3（每篇 1 块），/api/search 的 snippet 里塞满无关内容
""")

    exp_card(d, "实验 B", "关掉重排：看「质量换来了什么、代价是什么」", [
        ("改什么", "`RERANK_ENABLED=false`"),
        ("怎么做", "重启服务，问同一个问题，前后各跑一次 `/api/agent/debug`"),
        ("看什么", "① evidence 里的 `stage` 从 `rerank` 变回 `hybrid`；"
                  "② `/api/stats/summary` 的 `avg_latency_ms` 明显下降（重排是本地 CPU 大头）"),
        ("结论", "召回（快、全）→ 精排（慢、准）的三段式不是玄学：关掉重排能省下可观的 CPU 时间，"
                "但进入上下文的噪声变多，题目越难差距越明显。"),
    ])

    exp_card(d, "实验 C", "RRF 常数 k：理解「按名次融合」的最直观实验", [
        ("改什么", "`RRF_CONSTANT`（默认 60）"),
        ("怎么做", "分别设成 `1` 与 `1000`，各重启一次，用 `/api/search` 问同一题"),
        ("看什么", "命中结果的**顺序**变化（分数值本身也会变小/变大，但顺序才是重点）"),
        ("结论", "公式是 `score = Σ 1/(k+rank)`：**k 越小**越强调「某一路的第 1 名」；"
                "**k 越大**越偏向「两路都靠前的文档」。k=60 是原论文取值，工程上够用。"),
    ])

    exp_card(d, "实验 D", "Agent 轮数上限与「提前收束」：成本和延迟的主开关", [
        ("改什么", "`AGENT_MAX_RETRIEVAL_ROUNDS`、`AGENT_STRONG_SCORE`"),
        ("怎么做", "先设 `MAX_ROUNDS=1` + `STRONG_SCORE=0.0`（关掉收束）跑一次；"
                  "再恢复 `3` + `0.55` 跑一次，对比两次的用量"),
        ("看什么", "`/api/stats/summary` 的 `by_step`：`grade` 的 calls 从 1 变 3；"
                  "以及轨迹里是否出现「强证据提前收束，停止继续检索」这一步"),
        ("结论", "**LLM 判定器天然偏严**（宁可说不足也不放过噪声），纯靠它决定「要不要再检」"
                "会白烧 2~3 轮 token。所以加了一条确定性规则：精排最高分 ≥ 0.55 就停机 —— "
                "这就是「用确定性代码兜住模型不确定性」的典型例子。"),
    ])

    exp_card(d, "实验 E", "关掉防幻觉闸门：让它「裸奔」一次", [
        ("改什么", "`AGENT_VERIFY_ENABLED=false`；并把 `AGENT_SCORE_FLOOR_RATIO` 与 "
                  "`AGENT_SCORE_FLOOR_RATIO_LOOSE` 都设成 `1.1`（阈值 > 1 → 保护永不生效）"),
        ("怎么做", "重启，问一道**库里没有答案**的题（如「我们公司2025年第三季度营收是多少？」）"),
        ("看什么", "轨迹里没有 `verify` 这一步；答案末尾没有「⚠️ 忠实度自检提示」；"
                  "但**仍然会拒答** —— 因为「证据为空就短路拒答」在生成分支里，不归这个开关管"),
        ("结论", "两道闸门的分工要分清：闸门 1（判定）管「进去的资料」，闸门 2（校验）管「出去的答案」。"
                "想连短路拒答一起停掉，只能改代码 —— 这正好可以当成第二章的故障注入练习。"),
    ])

    exp_card(d, "实验 F", "同一题跑两条链路：得到你自己的「按场景路由」依据", [
        ("改什么", "不用改配置，用请求级开关 `agent: true/false`"),
        ("怎么做", "对同一道题分别请求 `/api/chat`（agent=false）与 `/api/chat`（agent=true）"),
        ("看什么", "对比 `usage.cost`、`elapsed_ms`，以及 `agent` 字段是否存在；"
                  "再对照答案是否引用了更多来源"),
        ("结论", "本项目实测（对照）：平均延迟约 4~5 倍、单问成本约 7~9 倍，换来生成层准确率提升 4~11 个百分点。"
                "**所以正确做法是按场景路由，而不是无脑全上 Agent** —— 面试讲这条比讲「我上了 Agent」更有分量。"),
    ])

    exp_card(d, "实验 G", "上下文预算：把预算调到很小，看它怎么裁剪", [
        ("改什么", "`AGENT_CONTEXT_MAX_CHARS`（默认 6000）→ 设成 `800`"),
        ("怎么做", "重启，问一个需要综合多条证据的问题（例如「给我一份知识库问答准确率不高的排查思路」）"),
        ("看什么", "轨迹里 `evidence_compress` 工具的 observation：`dropped_over_budget` 变大、"
                  "`context_chars` 贴近预算；被丢弃的证据 reason 写着「超出上下文预算被丢弃」"),
        ("结论", "裁剪是**按分数从高到低整段装**，装不下的整段丢弃并记录原因 —— "
                "而不是把句子硬截断。这个细节决定了「答案会不会突然断在半句话上」。"),
    ])

    exp_card(d, "实验 H", "模型分档路由：让便宜的任务走便宜的路", [
        ("改什么", "`LLM_SMALL_MODEL`（留空 = 与主模型相同）、`LLM_TASK_ROUTES`"),
        ("怎么做", "先保持留空，跑 `/api/stats/routes` 看每个任务实际落到哪个模型；"
                  "再填一个真实存在的小模型名（例如同厂商的轻量档），重启后重跑同一题"),
        ("看什么", "`/api/stats/summary` 的 `by_model`：规划/判定/改写/压缩是否都迁到了小模型；"
                  "以及总成本的变化（这些任务占调用次数的大头）"),
        ("结论", "Agent 的成本大头在「高频低价值」的判定与改写上 —— **把这几步路由到小模型，"
                "是降本最有效的一刀**，比砍轮数更不影响效果。"),
    ])

    # ============================================================ 第二章
    d.h1("第二章　故意弄坏它：7 个故障注入实验", number="")
    d.box("warn", "**每个实验都请按顺序做**：① 弄坏 → ② 观察现象与日志 → ③ 用给出的命令恢复。"
                  "全部在 `experiments/` 目录内进行，不影响主数据。")

    exp_card(d, "故障 1", "把 API Key 改错（模拟密钥过期 / 泄露后轮换）", [
        ("改什么", "`.env` 里 `LLM_API_KEY=sk-wrong-key-for-test`，重启"),
        ("怎么做", "先用 `/api/chat` 问一次，再用 `/api/chat/stream` 问一次"),
        ("看什么", "非流式：HTTP 503 且 detail 明确；流式：`{\"type\":\"error\",...}` 事件后"
                  "紧跟 `{\"type\":\"done\",\"closed\":true}` —— **不会静默断流**；"
                  "终端日志里有上游 401/403 报错"),
        ("结论", "考点是「错误要可见」：流式接口的 `except` 把异常转成 error 事件、`finally` 必补 done。"
                "对比很多项目的做法（连接直接断掉、前端只显示「无输出」）—— 这就是可观测性从接口层开始的例子。"),
        ("恢复", "把 key 改回真实值 → 重启"),
    ])

    exp_card(d, "故障 2", "弄坏知识库文件（最常见的线上数据故障）", [
        ("改什么", "把 `experiments/data/kb.jsonl` 第 1 行截断成半行 JSON"),
        ("怎么做", "备份原文件后，用 PowerShell 截断首行，重启服务"),
        ("看什么", "**启动直接失败**，日志里是 `json.decoder.JSONDecodeError`，指向 `store._load()`"),
        ("结论", "**数据损坏时必须响亮地失败**。这里刻意不做「跳过坏行」的容错 —— "
                "静默跳过会让你以为库是完整的，等到答案出错时再查就晚了。"),
        ("恢复", "`Copy-Item experiments\\data\\kb.jsonl.bak experiments\\data\\kb.jsonl -Force` → 重启"),
    ])
    d.code("""
# 备份 + 截断首行
Copy-Item experiments\\data\\kb.jsonl experiments\\data\\kb.jsonl.bak -Force
$lines = Get-Content experiments\\data\\kb.jsonl
$lines[0] = $lines[0].Substring(0, [Math]::Min(40, $lines[0].Length))
$lines | Set-Content experiments\\data\\kb.jsonl -Encoding UTF8
""")

    exp_card(d, "故障 3", "向量索引与元数据错位（最值得亲手做一次的一致性实验）", [
        ("改什么", "两种破坏方式：① 覆盖 `vectors.index` 的文件头；② 直接删掉 `kb.jsonl` 但保留索引"),
        ("怎么做", "先做 ①（应报错），再做 ②（应自愈），对比两种反应"),
        ("看什么", "① `faiss.read_index` 抛异常 → 启动失败；"
                  "② 启动正常，日志显示 `docs=0 chunks=0`，**且不崩** —— 因为引擎发现"
                  "「索引里的向量数 != 记录数」就**自动全量重建**"),
        ("结论", "这一段是面试讲「数据一致性」的现成素材，关键代码在 `engine.initialize()`："
                "`if not loaded or self.vectors.size != self.store.total_chunks(): 重建`。"
                "设计意图：宁可多花一次重建的时间，也不要让「向量位置与记录下标错位」污染检索结果。"),
        ("恢复", "删掉 `experiments\\data\\vectors.index` 与 `kb.jsonl`，重新 `seed_demo.py`"),
    ])
    d.code("""
# 方式 ①：覆盖索引文件头 64 字节
$fs = [System.IO.File]::OpenWrite("experiments\\data\\vectors.index")
$zero = New-Object byte[] 64
$fs.Write($zero, 0, 64); $fs.Close()

# 方式 ②：只删元数据、保留索引
Remove-Item experiments\\data\\kb.jsonl -Force
""")

    exp_card(d, "故障 4", "上传坏文件：把三种校验链路都试一遍", [
        ("改什么", "不用改代码，用三种「坏输入」打上传接口"),
        ("怎么做", "① 非法扩展名 `.exe`；② 内容是图片但改名成 `.md`；③ 60MB 超大文件"),
        ("看什么", "① **400** 并列出允许的扩展名；② **400**（解析不出文本 / 无分块），"
                  "且 `experiments/data/uploads/` 里**临时文件被清理**；③ **413** 且临时文件被清理"),
        ("结论", "三个状态码要背下来：**400 类型错 / 413 超大 / 500 兜底**。"
                "另外注意：扩展名白名单是「第一道门」，真实生产还要校验**文件头魔数**（改后缀即可绕过）。"
                "想亲眼看到「绕过」，可以把一个 exe 改名成 `.md` 再上传 —— 你会发现它通过了扩展名校验，"
                "然后在解析阶段才失败。"),
    ])
    d.code("""
# ① 非法扩展名
"test" | Set-Content experiments\\bad.exe
curl.exe -s -o - -w "`nHTTP=%{http_code}`n" -X POST http://127.0.0.1:8000/api/documents/upload -F "file=@experiments/bad.exe"

# ② 假装成 md 的图片
curl.exe -s -o - -w "`nHTTP=%{http_code}`n" -X POST http://127.0.0.1:8000/api/documents/upload -F "file=@_resume_photo.png;filename=fake.md"

# ③ 60MB 超大文件
fsutil file createnew experiments\\big.txt 60000000
curl.exe -s -o - -w "`nHTTP=%{http_code}`n" -X POST http://127.0.0.1:8000/api/documents/upload -F "file=@experiments/big.txt"
""")

    exp_card(d, "故障 5", "注入 Agent 节点故障：看「兜底」到底兜没兜住（本手册最有价值的一条）", [
        ("改什么", "在 `app/core/agent_nodes.py` 的 `grade()` 方法第一行插入 "
                  "`raise RuntimeError(\"INJECTED_grading_failure\")`"),
        ("怎么做", "重启服务，问一道普通问题（例如「混合检索为什么用 RRF？」）"),
        ("看什么", "**不会 500、不会中断**：`_json_call` 吞掉异常 → 重试两次 → 返回 fallback"
                  "（`sufficient=False`）；轨迹里 `grade` 显示「资料不足」；"
                  "循环去调 `query_rewrite` 再检（撞轮数上限）；最终**仍然给出带证据的回答**"),
        ("结论", "**LLM 是概率组件，控制流必须比它更确定。** 这就是「每个决策节点都能返回一个合法结果"
                "（而不是抛异常）」落到代码上的样子。把它讲给面试官，比说「我做了容错」具体得多。"),
        ("恢复", "删掉插入的那一行 → 重启"),
    ])
    d.code("""
# app/core/agent_nodes.py 中找到 grade()，插入第一行：
async def grade(self, state, question: str, evidence: list) -> GradeOutcome:
    raise RuntimeError("INJECTED_grading_failure")      # ← 实验用，做完删掉
    if not evidence:
        ...
""")

    exp_card(d, "故障 6", "花括号文档：复现「模板变量」这个真实历史坑", [
        ("改什么", "上传一篇正文含 `{\"item_id\": 123}` 的 md，然后针对它提问"),
        ("怎么做", "上传 → 问「item_id 为空怎么办？」"),
        ("看什么", "**正常回答，不报错** —— 因为渲染好的消息直接 `ainvoke`，"
                  "**不过 `ChatPromptTemplate`**；否则 `{item_id}` 会被当成模板变量，"
                  "抛 `INVALID_PROMPT_INPUT`（这就是 README 里记录的那个坑）"),
        ("结论", "凡是要把「用户/文档内容」送进模型的链路，都不要让它经过任何模板解析。"
                "想看「坏版本」，把 `engine._as_langchain_messages()` 换成模板链路即可复现报错。"),
    ])
    d.code("""
@"
# 代码示例文档
接口返回结构如下：{\\"item_id\\": 123, \\"name\\": \\"demo\\"}
如果 item_id 为空，请检查上游。
"@ | Set-Content experiments\\brace.md -Encoding UTF8
curl.exe -s -X POST http://127.0.0.1:8000/api/documents/upload -F "file=@experiments/brace.md" -F "title=花括号测试"
""")

    exp_card(d, "故障 7", "把知识库问「空」：边界与拒答", [
        ("改什么", "删掉所有文档（用 `DELETE /api/documents/{doc_id}`）"),
        ("怎么做", "逐个删除后，分别测 `/api/chat`、Agent 链路、`/api/search`"),
        ("看什么", "`/api/chat` → **503** 且提示清晰；Agent 链路 → **确定性拒答模板**"
                  "（说明检索了什么、为什么答不了、建议怎么做），**不是模型编的**；"
                  "`/api/search` → 返回空 `hits`，**不 500**"),
        ("结论", "空库是最容易被忽略的边界：很多系统在这里 500、或者让模型对着空气编。"
                "**正确的表现是「明确知道我答不了」**。"),
        ("恢复", "`.venv-rag\\Scripts\\python.exe scripts\\seed_demo.py`"),
    ])

    # ============================================================ 第三章
    d.h1("第三章　把日志看明白", number="")

    d.h2("3.1 症状 → 病因速查表")
    d.table(
        ["你看到的现象", "八成原因", "去哪儿查 / 怎么修"],
        [
            ["启动后 docs=0 chunks=0，但库里明明有数据", "DATA_DIR 相对路径没生效",
             "启动命令所在目录；改成绝对路径"],
            ["WinError 10051 / MaxRetryError，卡在加载模型", "HF 联网校验被墙（离线变量没在 import 前设置）",
             "app/core/hf_env.py；确认 HF_HUB_OFFLINE=1 且 data/hf 有模型"],
            ["答非所问，但 /api/search 命中是对的", "生成层或上下文拼装问题",
             "POST /api/debug/prompt 看真实送进模型的上下文（不花钱）"],
            ["答案缺要点，检索却「看着命中」", "判定器误杀了高分证据",
             "轨迹里 grade 的 observation：score_protected、kept/total"],
            ["每问都跑满 3 轮，又慢又贵", "AGENT_STRONG_SCORE 太高 / 判定器偏严",
             "轨迹里的 reflect 步骤；/api/stats/summary 的 by_step"],
            ["日志出现 Agent 节点 compress 输出不可用", "模型没按 JSON 形状返回（已兜底）",
             "偶发可忽略；频繁出现就改提示词或解析器"],
            ["引用编号指向无关内容", "上下文编号与 sources 错位",
             "/api/agent/query 的 agent.evidence[].cite_index 与回答里的 [n] 对照"],
            ["接口 500 但看不到原因", "兜底 except 吞了异常",
             "终端日志 + 临时把 except Exception 改成 raise 定位"],
            ["首次提问特别慢", "本地模型首次加载（embedding 95MB / 重排 430MB）",
             "第二次就会快；确认 data/hf 缓存存在"],
            ["中文分块把句子砍半", "分隔符列表没适配中文",
             "app/core/chunking.py 的 ZH_SEPARATORS"],
        ],
        widths=[3.0, 3.0, 4.4], font_size=9)

    d.h2("3.2 三个「排查第一站」（背下来）")
    d.bullet("**检索对不对** → `POST /api/search`：只跑混合检索 + 重排，不花钱。")
    d.bullet("**上下文拼得对不对** → `POST /api/debug/prompt`：看真实发给 LLM 的消息，不花钱。"
             "**这一步能定位八成「答不好」**：引用编号、来源文档、上下文顺序全在这里。")
    d.bullet("**Agent 决策对不对** → `POST /api/agent/debug`：只跑规划 + 检索 + 判定，"
             "不生成答案，最便宜。判定器的 `missing` 字段会直接告诉你「缺什么」。")
    d.box("key", "排错的正确顺序永远是**从上游往下游**：先确认检索命中 → 再确认上下文拼装 → "
                 "最后才怀疑生成。反过来做（先改提示词）是最常见的时间浪费。")

    # ============================================================ 第四章
    d.h1("第四章　配置速查与一个必须修的安全问题", number="")

    d.h2("4.1 最常调的几个配置项")
    d.table(
        ["配置项", "默认", "作用", "调它的后果"],
        [
            ["CHUNK_SIZE / CHUNK_OVERLAP", "500 / 50", "中文分块粒度", "最影响检索质量，需配合评测集验证"],
            ["RERANK_ENABLED / RERANK_TOP_K", "true / 4", "是否精排、精排后留几条",
             "关掉省 CPU，但噪声进上下文"],
            ["RRF_CONSTANT", "60", "RRF 融合常数 k", "越小越看重单路第一名"],
            ["AGENT_ENABLED", "true", "Agent 链路总开关", "关掉即回退朴素 RAG（可做 A/B）"],
            ["AGENT_MAX_RETRIEVAL_ROUNDS", "3", "最多几轮检索-判定-改写", "成本与延迟的主开关"],
            ["AGENT_STRONG_SCORE", "0.55", "强证据提前收束阈值", "调高 → 少检几轮；调低 → 更容易收束"],
            ["AGENT_SCORE_FLOOR_RATIO(_LOOSE)", "0.55 / 0.25", "分数下限保护系数",
             "防判定器误杀高分证据；判定「不足」时用宽松值"],
            ["AGENT_VERIFY_ENABLED", "true", "生成后忠实度自检", "关掉少一次调用，但少一道防幻觉闸门"],
            ["AGENT_CONTEXT_MAX_CHARS", "6000", "证据进上下文的字符预算", "调小会丢证据、答案变浅"],
            ["LLM_SMALL_MODEL / LLM_TASK_ROUTES", "空 / 见 .env",
             "模型分档路由", "填入小模型可显著降本（判定/改写占调用次数大头）"],
            ["QUERY_REWRITE", "true", "多轮历史改写为独立问题", "关掉省一次调用，多轮指代会失效"],
        ],
        widths=[3.0, 1.4, 3.2, 3.4], font_size=9)

    d.h2("4.2 交付前必查：密钥有没有被写进代码")
    d.para("在准备把项目交付 / 上传 git / 写进简历之前，先做这一项检查 —— 它比任何功能问题都严重。")
    d.code("""
# 一条命令扫出全项目里的疑似密钥（排除虚拟环境）
Get-ChildItem -Recurse -File -Include *.py,*.js,*.json,*.md,*.yml,*.txt,*.ps1 |
  Where-Object { $_.FullName -notmatch '\\(\\.venv|\\.venv-rag|__pycache__)\\' } |
  Select-String -Pattern 'sk-[A-Za-z0-9]{20,}'
""")
    d.para("**为什么危险**：即使 `.env` 会覆盖代码里的值、功能上「看起来没事」，"
           "只要那个文件被提交、被打包、被发给别人，key 就泄露了 —— "
           "而且 GitHub 的密钥扫描会直接命中，仓库可能被限流或标记。")
    d.para("**正确做法**：")
    d.code("""
# app/config.py：默认值必须是空字符串，只在 .env / 环境变量里给真值
llm_api_key: str = ""            # 未配置时 llm_ready=False，接口返回友好提示，而不是报错

# .env.example：只写占位符，绝不写真实 key
LLM_API_KEY=sk-请填入你的key

# 并确认 .gitignore 里有（本项目已有）
.env
""")
    d.box("warn", "**做完这三件事再交付**：① 把代码里的硬编码 key 改成空字符串；"
                  "② 确认 `.env` 在 `.gitignore` 里（本项目已有）；"
                  "③ **轮换那把已经暴露过的 key** —— 既然它曾经出现在文件里，就当它已泄露。")
    d.box("tip", "这也是一个很好的面试素材：**「我知道密钥不能进代码，并且在自己的项目里做了扫描检查」** —— "
                 "能主动说出这条的人，通常比只会写功能的人更让人放心。")

    d.h2("4.3 收尾清理")
    d.code("""
# 1) 在跑 uvicorn 的窗口按 Ctrl+C 停服务

# 2) 删掉实验目录（主数据 data/ 不受影响）
Remove-Item -Recurse -Force experiments

# 3) 确认主数据完好（应输出一个大于 0 的分块数）
.venv-rag\\Scripts\\python.exe -c @"
import pathlib
p = pathlib.Path('data/kb.jsonl')
n = sum(1 for l in p.read_text(encoding='utf-8').splitlines() if '\\"kind\\": \\"chunk\\"' in l)
print('主库分块数 =', n)
"@
""")

    d.h2("附录　实验记录表（建议打印出来边做边填）")
    d.table(
        ["实验", "改了哪个参数 / 怎么弄坏", "观察到的现象（一句话）", "结论 / 意外发现", "☐"],
        [
            ["A 分块粒度", "", "", "", "☐"],
            ["B 关重排", "", "", "", "☐"],
            ["C RRF 常数", "", "", "", "☐"],
            ["D 轮数 / 收束", "", "", "", "☐"],
            ["E 关闸门", "", "", "", "☐"],
            ["F 双链路 A/B", "", "", "", "☐"],
            ["G 上下文预算", "", "", "", "☐"],
            ["H 模型分档", "", "", "", "☐"],
            ["故障 1 Key 错", "", "", "", "☐"],
            ["故障 2 坏 JSONL", "", "", "", "☐"],
            ["故障 3 索引错位", "", "", "", "☐"],
            ["故障 4 坏上传", "", "", "", "☐"],
            ["故障 5 注入节点故障", "", "", "", "☐"],
            ["故障 6 花括号文档", "", "", "", "☐"],
            ["故障 7 空库", "", "", "", "☐"],
        ],
        widths=[2.2, 3.4, 3.4, 3.4, 0.5], font_size=9)
    d.para("")
    d.para(f"文档生成日期：{date.today().isoformat()}　｜　"
           f"对应代码版本：rag-qa-system（Agentic RAG 改造版）　｜　"
           f"配套文档：《改造全流程教程》《如何验证系统是正确的》",
           size=9, color=C_MUTED)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    print(f"SAVED {out}")
    print(f"size = {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
