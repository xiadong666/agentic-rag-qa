"""把 sample_docs/hard 的题集转换成评测框架能直接吃的标注集。

为什么要这一步：
    `seed_hard_corpus.py` 的 test_cases.json 面向"人工看结果"（带 why 解释）；
    而 `eval_agentic.py` 需要的是标准标注集（meta.extra_docs 指定语料、scope_docs 限定范围）。
    两边格式不同，用手抄容易出错，所以用一个 20 行的脚本做转换，保证口径一致。

用法：
    .venv-rag\\Scripts\\python scripts/make_hard_eval_set.py
输出：
    data/eval_set_hardcorpus.json
然后可以直接跑双链路对比：
    .venv-rag\\Scripts\\python scripts\\eval_agentic.py --mode both --tag hardcorpus ^
        --set data/eval_set_hardcorpus.json --top-k 4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sample_docs" / "hard" / "test_cases.json"
DST = ROOT / "data" / "eval_set_hardcorpus.json"

# 语料文件（相对项目根）；评测脚本会在空库时自动灌入这些文件
EXTRA_DOCS = [
    "sample_docs/hard/01_网关与鉴权接入说明.md",
    "sample_docs/hard/02_API变更记录.md",
    "sample_docs/hard/03_数据平台运维手册.md",
    "sample_docs/hard/04_支付服务接口规范.md",
    "sample_docs/hard/05_部署与发布SOP.md",
    "sample_docs/hard/06_Nexus_Gateway_Integration_Guide_EN.md",
    "sample_docs/hard/07_线上问题登记表.csv",
]


def main() -> int:
    ap_out = "--stdout" in sys.argv          # 受限环境可只打印，由外部写入
    if not SRC.exists():
        print(f"找不到题集：{SRC}")
        return 1
    src = json.loads(SRC.read_text(encoding="utf-8"))
    cases = []
    for c in src.get("cases", []):
        cases.append({
            "id": c["id"],
            "type": c.get("type", ""),
            "question": c["question"],
            "answerable": bool(c.get("answerable", True)),
            "expect_docs": c.get("expect_docs") or [],
            "ref_keywords": c.get("ref_keywords") or [],
            "difficulty": c.get("difficulty", "hard"),
            "why": c.get("why", ""),
        })

    meta = {
        "name": "hard-corpus-eval-set",
        "version": "1.0",
        "note": ("由 sample_docs/hard 的企业内部语料构建：7 篇文档 + 14 道题（含 3 道库外幻觉探针）。"
                 "难点集中在精确标识符、版本冲突、长文埋点、口语 vs 术语、语义干扰、"
                 "中英混排、结构化数据七类。scope_docs 限定在困难语料范围内，"
                 "便于与 sample_docs 的简单文档混库时仍能算准指标。"),
        "scope_docs": [Path(p).stem for p in EXTRA_DOCS],
        "extra_docs": EXTRA_DOCS,
        "source": "sample_docs/hard/test_cases.json",
    }
    payload = json.dumps({"meta": meta, "cases": cases}, ensure_ascii=False, indent=2)
    if ap_out:
        print(payload)
        return 0
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(payload, encoding="utf-8")
    print(f"OK -> {DST}")
    print(f"题目 {len(cases)} 道（可答 {sum(1 for c in cases if c['answerable'])} / "
          f"探针 {sum(1 for c in cases if not c['answerable'])}）｜语料 {len(EXTRA_DOCS)} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
