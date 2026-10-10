"""端到端 API 冒烟脚本（httpx，无需浏览器/curl 转义问题）。

用法：.venv\\Scripts\\python scripts/smoke_api.py [base_url]
默认 http://127.0.0.1:8010

它会依次执行：health → 列表 → search(混合检索+重排) → debug/prompt →
chat(未配 key 应 503) → 上传新文档 → 列表 → 删除 → 列表。
每个响应存到 data/smoke_<n>.json（UTF-8），并打印 ASCII 状态行。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(parents=True, exist_ok=True)
n = 0


def save(name: str, data) -> None:
    global n
    n += 1
    p = OUT / f"smoke_{n:02d}_{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] {name} -> {p.name} ({p.stat().st_size} bytes)")


def main() -> None:
    c = httpx.Client(timeout=600.0)
    t0 = time.perf_counter()

    h = c.get(f"{BASE}/health").json()
    print("[ok] health", h)
    save("health", h)

    docs = c.get(f"{BASE}/api/documents").json()
    print("[ok] documents", [(d["title"], d["chunk_count"]) for d in docs])
    save("documents_before", docs)

    q_search = "混合检索为什么要用 RRF 融合？cross-encoder 重排和 bi-encoder 区别？"
    r = c.post(f"{BASE}/api/search", json={"question": q_search, "top_k": 3})
    print("[ok] search status", r.status_code, "elapsed(s)", round(time.perf_counter() - t0, 2))
    save("search", r.json())
    for i, hit in enumerate(r.json().get("hits", []), 1):
        print(f"    hit{i}: [{hit['cite_index']}] {hit['doc_title']} p{hit['page']} score={hit['score']} stage? retriever={hit.get('retriever')}")

    q_prompt = "LCEL 怎么做到流式输出？"
    r = c.post(f"{BASE}/api/debug/prompt", json={"question": q_prompt, "session_id": "demo"})
    print("[ok] debug_prompt status", r.status_code)
    save("debug_prompt", r.json())
    msgs = r.json().get("messages", [])
    print("    roles:", [m["role"] for m in msgs], "| rewritten:", r.json().get("rewritten_question"))

    r = c.post(f"{BASE}/api/chat", json={"question": "什么是 LCEL？"})
    print("[ok] chat(no-key) status", r.status_code)
    save("chat_no_key", r.json())

    # 上传一篇新 md（用样例文件），然后删除它
    md = Path(__file__).resolve().parents[1] / "sample_docs" / "fastapi速查.md"
    with md.open("rb") as f:
        r = c.post(
            f"{BASE}/api/documents/upload",
            files={"file": ("fastapi-extra.md", f, "text/markdown")},
            data={"title": "上传测试文档"},
        )
    print("[ok] upload status", r.status_code)
    save("upload", r.json())
    new_id = r.json().get("doc_id", "")

    docs2 = c.get(f"{BASE}/api/documents").json()
    print("[ok] documents_after_upload", len(docs2), "docs")

    r = c.delete(f"{BASE}/api/documents/{new_id}")
    print("[ok] delete status", r.status_code)
    docs3 = c.get(f"{BASE}/api/documents").json()
    print("[ok] documents_after_delete", len(docs3), "docs")
    save("documents_after", docs3)
    print("[done] total elapsed(s)", round(time.perf_counter() - t0, 2))


if __name__ == "__main__":
    main()
