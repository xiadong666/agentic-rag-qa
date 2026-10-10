"""生成《Agentic RAG 企业级知识库问答与决策系统 —— 改造全流程 + 知识点巩固》Word 教程。

为什么用 Markdown 作内容源：
    直接用 Python 拼 docx，长中文文档里到处是引号嵌套，字符串定界符冲突极难排查。
    把内容写成 Markdown（docs/agentic_rag_tutorial*.md），排版交给 scripts/md_to_docx.py，
    内容与排版彻底解耦：改文案不用碰代码，调样式不用碰文案。

数据驱动：
    第七部分的两张指标表不写死在文案里，而是从 data/eval_compare_*.json 读取后注入。
    重新跑评测再重新生成文档，指标自动同步 —— 文档永远不会和实测数据脱节。

用法：
    .venv-rag\\Scripts\\python scripts\\build_agentic_rag_doc.py
    # --out 可指定输出路径（默认写 docs/；若该目录不可写可先写到可写目录再拷过去）
输出：
    docs/Agentic_RAG_企业级知识库问答与决策系统_改造全流程教程.docx
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.docx_builder import Doc  # noqa: E402
from scripts.md_to_docx import render  # noqa: E402

DOCS = ROOT / "docs"
DATA = ROOT / "data"
PARTS = [DOCS / "agentic_rag_tutorial.md", DOCS / "agentic_rag_tutorial_part2.md"]
OUT = DOCS / "Agentic_RAG_企业级知识库问答与决策系统_改造全流程教程.docx"

# 指标报告可能落在不同目录（评测脚本用 --out-dir 指定），按候选顺序找第一个存在的
METRIC_CANDIDATES = [
    "eval_compare_hard.json", "eval_compare_hard11.json", "eval_compare_easy.json",
]


def find_report(name: str, roots: list[Path]) -> dict | None:
    for root in roots:
        p = root / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return None


def load(name: str) -> dict | None:
    p = DATA / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def pct(x, digits: int = 1) -> str:
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except Exception:  # noqa: BLE001
        return "—"


def delta_pp(b, a) -> str:
    try:
        return f"{(float(a) - float(b)) * 100:+.1f} 个百分点"
    except Exception:  # noqa: BLE001
        return "—"


def delta_num(b, a, digits: int = 3) -> str:
    try:
        return f"{float(a) - float(b):+.{digits}f}"
    except Exception:  # noqa: BLE001
        return "—"


def metric_table(cmp: dict | None) -> str:
    """把 eval_compare_*.json 渲染成 Markdown 指标表（含变化列）。"""
    if not cmp:
        return "> [warn] 未找到该评测集的对比报告（data/eval_compare_*.json）。" \
               "请先运行 scripts/eval_agentic.py --mode both 生成数据，再重新生成本文档。"
    b, a = cmp["baseline"], cmp["agentic"]

    def row(name, bp, ap, delta):
        return f"| {name} | {bp} | {ap} | {delta} |"

    lines = [
        f"样本 {cmp.get('n_cases', '?')} 题　｜　生成时间 {cmp.get('generated_at', '—')}",
        "",
        "| 指标 | 朴素 RAG | Agentic RAG | 变化 |",
        "| --- | --- | --- | --- |",
        row("检索 Hit@1", pct(b["retrieval"]["hit_at_1"]), pct(a["retrieval"]["hit_at_1"]),
            delta_pp(b["retrieval"]["hit_at_1"], a["retrieval"]["hit_at_1"])),
        row("检索 Recall@k", pct(b["retrieval"]["recall_at_k"]), pct(a["retrieval"]["recall_at_k"]),
            delta_pp(b["retrieval"]["recall_at_k"], a["retrieval"]["recall_at_k"])),
        row("检索 MRR", f"{b['retrieval']['mrr']:.3f}", f"{a['retrieval']['mrr']:.3f}",
            delta_num(b["retrieval"]["mrr"], a["retrieval"]["mrr"])),
        row("证据要点覆盖率", pct(b["retrieval"].get("evidence_kw_recall", 0)),
            pct(a["retrieval"].get("evidence_kw_recall", 0)),
            delta_pp(b["retrieval"].get("evidence_kw_recall", 0),
                     a["retrieval"].get("evidence_kw_recall", 0))),
        row("应答准确率", pct(b["answer"]["correctness"]), pct(a["answer"]["correctness"]),
            delta_pp(b["answer"]["correctness"], a["answer"]["correctness"])),
        row("生成层准确率", pct(b["answer"].get("generation_accuracy", 0)),
            pct(a["answer"].get("generation_accuracy", 0)),
            delta_pp(b["answer"].get("generation_accuracy", 0),
                     a["answer"].get("generation_accuracy", 0))),
        row("幻觉率", pct(b["hallucination"]["rate"]), pct(a["hallucination"]["rate"]),
            delta_pp(b["hallucination"]["rate"], a["hallucination"]["rate"])),
        row("无答案误答率", pct(b["hallucination"]["false_answer_rate_on_unanswerable"]),
            pct(a["hallucination"]["false_answer_rate_on_unanswerable"]),
            delta_pp(b["hallucination"]["false_answer_rate_on_unanswerable"],
                     a["hallucination"]["false_answer_rate_on_unanswerable"])),
        row("无答案正确拒答率", pct(b["hallucination"].get("refusal_rate_on_unanswerable", 0)),
            pct(a["hallucination"].get("refusal_rate_on_unanswerable", 0)),
            delta_pp(b["hallucination"].get("refusal_rate_on_unanswerable", 0),
                     a["hallucination"].get("refusal_rate_on_unanswerable", 0))),
        row("平均延迟", f"{b['cost']['avg_latency_ms']} ms", f"{a['cost']['avg_latency_ms']} ms",
            f"{a['cost']['avg_latency_ms'] - b['cost']['avg_latency_ms']:+d} ms"),
        row("单问成本", f"{b['cost']['avg_cost_per_query']:.6f} 元",
            f"{a['cost']['avg_cost_per_query']:.6f} 元",
            f"{a['cost']['avg_cost_per_query'] - b['cost']['avg_cost_per_query']:+.6f} 元"),
        row("平均模型调用次数", "1~2 次", f"{a['cost'].get('avg_llm_calls', 0)} 次", "—"),
    ]
    return "\n".join(lines)


def main() -> None:
    global DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT), help="输出 docx 路径")
    ap.add_argument("--metrics-dir", default=str(DATA),
                    help="评测报告所在目录（默认 data/，即 eval_compare_*.json 的位置）")
    args = ap.parse_args()
    out = Path(args.out)
    DATA = Path(args.metrics_dir)

    md = "\n\n".join(p.read_text(encoding="utf-8") for p in PARTS if p.exists())
    if not md.strip():
        raise SystemExit("没有找到 Markdown 内容源")

    easy = find_report("eval_compare_easy.json", [DATA, ROOT / "data"])
    hard = find_report("eval_compare_hard.json", [DATA, ROOT / "data"]) or \
        find_report("eval_compare_hard11.json", [DATA, ROOT / "data"])
    md = md.replace("{{EASY_TABLE}}", metric_table(easy))
    md = md.replace("{{HARD_TABLE}}", metric_table(hard))
    md += (f"\n\n---\n\n文档生成日期：{date.today().isoformat()}　｜　"
           f"对应代码版本：rag-qa-system（Agentic RAG 改造版）　｜　"
           f"指标数据源：data/eval_compare_easy.json、data/eval_compare_hard11.json\n")

    d = Doc(title="Agentic RAG 企业级知识库问答与决策系统",
            subtitle="改造全流程详解 · 每一步做什么 · 代码知识点巩固 · 指标前后对比 · 避坑与面试话术",
            margin_cm=1.9)
    d.footer_page_number()
    render(d, md)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    print(f"SAVED {out}")
    print(f"size = {out.stat().st_size} bytes | 指标表：easy={'有' if easy else '无'} hard={'有' if hard else '无'}")


if __name__ == "__main__":
    main()
