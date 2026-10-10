"""生成"更难"的评测集：从真实语料里抽可验证的考点，产出候选用例供人工筛选。

为什么需要它：
    评测集如果只覆盖"一篇文档一个主题"的简单问答，朴素 RAG 就能拿满分，
    改造前后没有差异 —— 这种评测集无法证明 Agentic RAG 的价值。
    真正能拉开差距的是这四类：
      ① 同一术语散落在多篇文档（需要跨文档综合）；
      ② 问题与文档用词不一致（需要多轮改写检索式，单轮容易漏）；
      ③ 需要限定条件的精确查询（型号/参数名/数字，靠 BM25 与重排）；
      ④ 知识库里确实没有答案（幻觉探针：看它会不会硬答）。

用法（产出候选集，人工挑选后写进 eval_set_agentic.json）：
    .venv\\Scripts\\python scripts/gen_eval_candidates.py --docs 3 --per-doc 6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.core.llm import create_chat_model  # noqa: E402
from app.core.agent_nodes import parse_json_loose  # noqa: E402

SYSTEM = """你是 RAG 评测集设计专家。给你一篇企业文档，请设计可以**严格依据该文档验证**的考题。
只输出 JSON：{"cases": [ ... ]}，每个元素字段如下：
{
  "question": "用户会怎么问（要口语化、贴近真实提问，不要照抄文档标题）",
  "type": "A-语义单跳|B-精确词|C-同义改写|D-跨段综合|N-无答案(幻觉探针)",
  "answerable": true/false,
  "ref_keywords": ["回答中必须出现或语义等价的关键词，2~4 个"],
  "why": "为什么这道题能区分朴素 RAG 与 Agentic RAG（一句话）"
}
要求：
- 至少 3 道题的答案要点分散在文档不同段落（跨段综合）；
- 至少 1 道题必须用文档里的**精确术语/参数名/数字**才能答准；
- 至少 2 道题问法要与文档用词不同（同义改写、上位概念、英文术语）；
- 出 1 道 answerable=false 的题：问一个该文档**没有**涉及的相关细节，用于检测幻觉；
- 不要设计"文档里没有但常识能答"的题；
- 只输出 JSON，不要解释。"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=3, help="取前 N 篇文档（按分块数从多到少）")
    ap.add_argument("--per-doc", type=int, default=6)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "data" / "eval_candidates.json"))
    ap.add_argument("--include-prefix", default="", help="只取标题以此开头的文档")
    args = ap.parse_args()

    settings = get_settings().model_copy(update={"data_dir": Path(args.data_dir).resolve()})
    from app.core.engine import RAGEngine

    engine = RAGEngine(settings)
    await engine.initialize()

    docs = [d for d in engine.store.doc_list() if not args.include_prefix
            or d.title.startswith(args.include_prefix)]
    docs.sort(key=lambda d: d.chunk_count, reverse=True)
    docs = docs[: args.docs]
    if not docs:
        print("没有可用文档")
        return 1

    llm = create_chat_model(settings, model=settings.llm_model)
    from langchain_core.messages import HumanMessage, SystemMessage

    out: list[dict] = []
    for d in docs:
        text = "\n\n".join(c.text for c in engine.store.chunks if c.doc_id == d.doc_id)
        text = text[:12000]
        print(f"生成候选：{d.title}（{d.chunk_count} 分块 / {len(text)} 字）")
        resp = await llm.ainvoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=f"文档标题：{d.title}\n\n文档全文：\n{text}\n\n请出 {args.per_doc} 道题。"),
        ])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        obj = parse_json_loose(raw) or {}
        for c in (obj.get("cases") or []):
            c["expect_docs"] = [d.title]
            c["difficulty"] = "generated"
            out.append(c)
        print(f"  -> {len(obj.get('cases') or [])} 道")

    Path(args.out).write_text(json.dumps({"cases": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n候选集已写入 {args.out}（共 {len(out)} 道，请人工筛选后并入 eval_set_agentic.json）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
