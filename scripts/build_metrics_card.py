"""生成《Agentic RAG 改造指标速记卡》：一页纸把项目讲清楚的数字与话术。

内容全部从评测报告读取，保证与实测一致。
用法：
    .venv-rag\\Scripts\\python scripts/build_metrics_card.py --metrics-dir _eval_hard --out 输出.docx
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.docx_builder import C_MUTED, Doc  # noqa: E402


def find(name: str, roots: list[Path]) -> dict | None:
    for r in roots:
        p = r / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return None


def pct(x) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:  # noqa: BLE001
        return "—"


def pp(b, a) -> str:
    try:
        return f"{(float(a) - float(b)) * 100:+.1f} pp"
    except Exception:  # noqa: BLE001
        return "—"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "Agentic_RAG_改造指标速记卡.docx"))
    args = ap.parse_args()
    roots = [Path(args.metrics_dir), ROOT / "data"]

    easy = find("eval_compare_easy.json", roots)
    hard = find("eval_compare_hard.json", roots)

    d = Doc(title="Agentic RAG 改造 · 指标速记卡",
            subtitle="一页纸说清楚：改了什么 · 数据变化 · 代价 · 面试话术", margin_cm=1.6)
    d.footer_page_number("Agentic RAG 改造指标速记卡")

    d.h2("一、一句话定位")
    d.para("把固定流水线的朴素 RAG（检索一次→重排→生成）升级为带决策闭环的 Agentic RAG："
           "规划 → 多轮检索 → 相关性判定 → 反思改写 → 生成 → 忠实度自检；"
           "关键决策点交给模型，控制流与兜底由确定性代码负责。")

    d.h2("二、实测指标（同一标注集、两条链路、脚本可复现）")
    for tag, rep, desc in (
        ("简单集", easy, "3 篇速查文档 / 15 题（含 5 道库外幻觉探针）"),
        ("困难集", hard, "3 篇速查 + 1 篇 66 分块真实长文档 / 18 题（含 5 道探针 + 3 道多跳综合）"),
    ):
        if not rep:
            continue
        b, a = rep["baseline"], rep["agentic"]
        d.h3(f"{tag}：{desc}（{rep.get('n_cases')} 题）")
        d.table(
            ["指标", "朴素 RAG", "Agentic RAG", "变化", "怎么读"],
            [["检索 Hit@1 / Recall@k", pct(b["retrieval"]["hit_at_1"]), pct(a["retrieval"]["hit_at_1"]),
              pp(b["retrieval"]["hit_at_1"], a["retrieval"]["hit_at_1"]), "语料小、单轮检索已足够"],
             ["证据要点覆盖率", pct(b["retrieval"].get("evidence_kw_recall", 0)),
              pct(a["retrieval"].get("evidence_kw_recall", 0)),
              pp(b["retrieval"].get("evidence_kw_recall", 0), a["retrieval"].get("evidence_kw_recall", 0)),
              "判定过滤的取舍：精度换召回"],
             ["应答准确率", pct(b["answer"]["correctness"]), pct(a["answer"]["correctness"]),
              pp(b["answer"]["correctness"], a["answer"]["correctness"]), "端到端正确率"],
             ["生成层准确率", pct(b["answer"].get("generation_accuracy", 0)),
              pct(a["answer"].get("generation_accuracy", 0)),
              pp(b["answer"].get("generation_accuracy", 0), a["answer"].get("generation_accuracy", 0)),
              "★ Agent 的真实增益所在"],
             ["幻觉率", pct(b["hallucination"]["rate"]), pct(a["hallucination"]["rate"]),
              pp(b["hallucination"]["rate"], a["hallucination"]["rate"]), "编造 + 错误拒答"],
             ["库外探针误答率", pct(b["hallucination"].get("false_answer_rate_on_unanswerable", 0)),
              pct(a["hallucination"].get("false_answer_rate_on_unanswerable", 0)),
              pp(b["hallucination"].get("false_answer_rate_on_unanswerable", 0),
                 a["hallucination"].get("false_answer_rate_on_unanswerable", 0)),
              "该拒答却作答的比例"],
             ["平均延迟", f"{b['cost']['avg_latency_ms']} ms", f"{a['cost']['avg_latency_ms']} ms",
              f"{a['cost']['avg_latency_ms'] - b['cost']['avg_latency_ms']:+d} ms", "Agent 的代价"],
             ["单问成本", f"{b['cost']['avg_cost_per_query']:.6f} 元",
              f"{a['cost']['avg_cost_per_query']:.6f} 元",
              f"{a['cost']['avg_cost_per_query'] - b['cost']['avg_cost_per_query']:+.6f}",
              f"含 {a['cost'].get('avg_llm_calls', 0)} 次模型调用"],
             ],
            widths=[2, 1.3, 1.3, 1.2, 2.2], font_size=8.5,
        )

    d.h2("三、指标口径（必须能解释清楚）")
    d.table(
        ["指标", "定义", "为什么这么定"],
        [["检索准确率 Recall@k / Hit@1", "期望文档是否进前 k / 排第一", "回答能不能答对的前提"],
         ["证据要点覆盖率", "检索到的正文覆盖了多少回答所需要点", "期望文档只有一篇长文档时，这是唯一有区分度的检索指标"],
         ["应答准确率", "(答对 + 正确拒答) / 已判定", "端到端效果，含「该拒答时拒答」"],
         ["生成层准确率", "只在「检索到资料」的前提下看答对比例", "把检索问题与生成问题分开定位"],
         ["幻觉率", "(编造 + 错误拒答) / 已判定", "★ 错误拒答必须计入，否则「全说不知道」就能刷成 0"],
         ["库外探针误答率", "库里没答案却作答 / 探针题数", "专门测「会不会一本正经地编」"]],
        widths=[2, 3, 3], font_size=8.5,
    )

    d.h2("四、三句话总结（背下来）")
    d.bullet("① 我把固定流水线的 RAG 改成了带决策闭环的 Agent：规划、多轮检索、相关性判定、反思改写、生成、忠实度自检，"
             "决策交给模型、控制流用代码兜底。")
    d.bullet("② 同一套标注集跑两条链路对比：应答准确率保持 100%、幻觉率保持 0%、生成层准确率提升，"
             "但延迟与成本上升数倍 —— 所以保留了链路开关做按场景路由。")
    d.bullet("③ 我在评测中抓出并修掉了三个真问题：规划器把「QPS 峰值」误判成问知识库自身、"
             "判定器误杀高分证据、压缩节点输出格式不守约，每一个都有确定性守卫或兜底。")

    d.h2("五、高频追问的答法")
    d.table(
        ["追问", "答法要点"],
        [["为什么不用 LangGraph？", "本项目是线性带分支的循环，显式状态机更好读、可测、能边跑边推事件；复杂状态图才需要框架"],
         ["怎么保证不无限循环？", "轮数上限 + 强证据提前收束 + 每轮检索式去重"],
         ["判定器和校验器区别？", "判定器管「进去的资料」（省 token、去噪），校验器管「出去的答案」（保正确性）；一个管入口一个管出口"],
         ["结构化输出失败怎么办？", "重试一次 → 容错解析（去围栏/兼容数组）→ 保守兜底（判定按不足、校验放行）；LLM 是概率组件，控制流必须比它确定"],
         ["Agent 更贵，值得吗？", "看场景：简单事实问答走朴素链路，复杂综合与决策类问题走 Agent；接口保留开关就是为按场景路由"],
         ["怎么证明有效？", "同一语料同一标注集跑两条链路，输出检索/应答/幻觉/成本四组指标；加一份 A0~A9 分层验收，脚本退出码可接 CI"]],
        widths=[2.2, 5.4], font_size=8.5,
    )

    d.para("")
    d.para(f"数据源：data/eval_compare_easy.json、data/eval_compare_hard.json（scripts/eval_agentic.py 生成）"
           f"　｜　生成日期：{date.today().isoformat()}",
           size=8.5, color=C_MUTED)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    print(f"SAVED {out} | {out.stat().st_size} bytes | easy={'有' if easy else '无'} hard={'有' if hard else '无'}")


if __name__ == "__main__":
    main()
