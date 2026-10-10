"""检索质量量化评测：小评测集 + Recall@k / MRR。

为什么需要它：系统"能回答"不代表"检索对"。用一组 (问题 → 期望来源文档) 的
标注样本，跑 /api/search，算命中率指标，才能对比调参前后的效果（chunk_size、
top_k、是否开 rerank、RRF 常数……）。

用法（先启动服务）：
    .venv\\Scripts\\python scripts\\eval_retrieval.py http://127.0.0.1:8000

输出：逐题命中情况 + Recall@1 / Recall@3 / MRR + 阈值判定（默认 Recall@3 >= 0.8）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

# ---- 标注集：问题 → 期望命中的文档标题（基于 sample_docs 三篇内置文档）----
CASES: list[tuple[str, str]] = [
    ("混合检索为什么要用 RRF 融合？", "rag原理速查"),
    ("cross-encoder 重排和 bi-encoder 有什么区别？", "rag原理速查"),
    ("引用来源对 RAG 系统有什么价值？", "rag原理速查"),
    ("LCEL 怎么把组件串成链？", "langchain速查"),
    ("bge 中文向量模型使用时要注意什么？", "langchain速查"),
    ("中文文本分块的分隔符要怎么设置？", "langchain速查"),
    ("FastAPI 怎么做文件上传？", "fastapi速查"),
    ("怎么把服务部署到生产环境？", "fastapi速查"),
    ("异步路由里遇到 CPU 密集代码怎么办？", "fastapi速查"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--k", type=int, default=3, help="评测的 k（Recall@k）")
    ap.add_argument("--min-recall", type=float, default=0.8, help="Recall@k 阈值，低于则退出码 1")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    c = httpx.Client(timeout=180.0)

    hit1 = hitk = 0
    rr_sum = 0.0
    rows: list[str] = []
    print(f"{'问题':<34} {'期望文档':<14} {'排名':<6} {'top1 命中':<8} 结果")
    print("-" * 88)
    for q, expect in CASES:
        hits = c.post(f"{base}/api/search", json={"question": q, "top_k": max(args.k, 5)}).json().get("hits", [])
        titles = [h["doc_title"] for h in hits]
        rank = titles.index(expect) + 1 if expect in titles else 0
        ok1 = rank == 1
        okk = 1 <= rank <= args.k
        hit1 += int(ok1)
        hitk += int(okk)
        rr_sum += (1.0 / rank) if rank else 0.0
        rows.append(f"{q:<34} {expect:<14} {rank or '-':<6} {'✓' if ok1 else '✗':<8} {'PASS' if okk else 'MISS'}")
        print(rows[-1])

    n = len(CASES)
    recall1, recallk, mrr = hit1 / n, hitk / n, rr_sum / n
    print("-" * 88)
    print(f"样本数 {n} | Recall@1 = {recall1:.2%} | Recall@{args.k} = {recallk:.2%} | MRR = {mrr:.3f}")
    print(f"（阈值 Recall@{args.k} >= {args.min_recall:.0%}，低分题请对照检索/分块/重排参数排查）")
    return 0 if recallk >= args.min_recall else 1


if __name__ == "__main__":
    sys.exit(main())
