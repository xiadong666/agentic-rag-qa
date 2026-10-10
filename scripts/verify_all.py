"""端到端自动验收：分层检查 RAG 知识库问答系统是否“真的正确”。

用法（先启动服务）：
    .venv\\Scripts\\python -m uvicorn app.main:app --port 8000
    .venv\\Scripts\\python scripts\\verify_all.py http://127.0.0.1:8000

检查分层：
  L0 服务层   /health 可用、数据目录可读
  L1 数据层   入库文件与索引一致（kb.jsonl 分块数 == health.chunks，vectors.index 存在）
  L2 入库链   上传→解析→分块→向量化→索引（唯一标记文档可被检索到，证明新数据真正入库）
  L3 检索层   混合检索命中有出处（chunk_id/doc_title/score/snippet 齐全、cite_index 连续）
  L4 组装层   /api/debug/prompt 的上下文带编号 [1][2] 与来源（不花 LLM 钱就能验）
  L5 生成层   非流式回答非空、引用编号落在 sources 范围内；SSE 有 meta→token→done
  L6 多轮     同一 session 第二问可用历史（used_history=True）
  L7 鲁棒性   非法扩展名 400；删除文档后计数恢复、且该文档不再被检索到

退出码：0 = 全部 PASS（允许 SKIP），1 = 存在 FAIL。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def check(layer: str, name: str, ok: bool | None, detail: str = "") -> None:
    status = SKIP if ok is None else (PASS if ok else FAIL)
    results.append((layer, name, status, detail))
    print(f"[{status}] {layer} {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data"))
    args = ap.parse_args()
    base = args.base.rstrip("/")
    data_dir = Path(args.data_dir)
    c = httpx.Client(timeout=180.0)
    temp_id = ""
    unique = f"零号校验协议 ZEROCHECK{int(time.time())}"

    try:
        # ---------- L0 服务层 ----------
        try:
            h = c.get(f"{base}/health").json()
            check("L0", "GET /health", h.get("status") == "ok", json.dumps(h, ensure_ascii=False))
        except Exception as e:
            check("L0", "GET /health", False, repr(e))
            print("\n服务不可用，后续检查无法进行。")
            return 1
        llm_ready = bool(h.get("llm_ready"))

        # ---------- L1 数据层 ----------
        kb = data_dir / "kb.jsonl"
        vec = data_dir / "vectors.index"
        if kb.exists():
            chunk_lines = 0
            with open(kb, "r", encoding="utf-8") as f:
                for line in f:
                    if '"kind": "chunk"' in line:
                        chunk_lines += 1
            check("L1", "kb.jsonl 分块数与 /health 一致", chunk_lines == h.get("chunks"),
                  f"file={chunk_lines} api={h.get('chunks')}")
        else:
            check("L1", "kb.jsonl 存在", False, str(kb))
        check("L1", "vectors.index 存在且非空", vec.exists() and vec.stat().st_size > 0,
              f"{vec.stat().st_size if vec.exists() else 0} bytes")

        # ---------- L2 入库链 ----------
        baseline_docs = len(c.get(f"{base}/api/documents").json())
        tmp = data_dir / "_verify_doc.md"
        tmp.write_text(
            f"# 自检文档\n\n{unique} 是本系统端到端自检用的唯一标记文本。\n"
            "如果检索能命中这句话，说明上传→解析→分块→向量化→索引链路是通的。\n",
            encoding="utf-8",
        )
        with tmp.open("rb") as f:
            r = c.post(f"{base}/api/documents/upload",
                       files={"file": ("verify_doc.md", f, "text/markdown")},
                       data={"title": "自检临时文档"})
        up = r.json() if r.status_code == 200 else {}
        temp_id = up.get("doc_id", "")
        check("L2", "上传接口 200", r.status_code == 200, r.text[:160] if r.status_code != 200 else "")
        check("L2", "解析出字符 & 产出分块", bool(up.get("char_count")) and (up.get("chunk_count") or 0) >= 1,
              f"chars={up.get('char_count')} chunks={up.get('chunk_count')}")
        check("L2", "文档列表 +1", len(c.get(f"{base}/api/documents").json()) == baseline_docs + 1)

        # ---------- L3 检索层 ----------
        r = c.post(f"{base}/api/search", json={"question": unique, "top_k": 3})
        hits = r.json().get("hits", []) if r.status_code == 200 else []
        top_title = hits[0]["doc_title"] if hits else ""
        check("L3", "唯一标记能检索到（新数据真正入库）", bool(hits) and top_title == "自检临时文档",
              f"top={top_title}")
        required = {"chunk_id", "doc_id", "doc_title", "score", "snippet", "cite_index"}
        fields_ok = bool(hits) and all(required.issubset(set(x.keys())) for x in hits)
        check("L3", "命中字段齐全（可溯源）", fields_ok, f"hits={len(hits)}")
        idx_ok = [x["cite_index"] for x in hits] == list(range(1, len(hits) + 1))
        check("L3", "cite_index 与编号连续", idx_ok)
        snippet_ok = bool(hits) and all(len(x.get("snippet", "")) > 0 for x in hits)
        check("L3", "snippet 非空", snippet_ok)

        # ---------- L4 组装层（不花 LLM 钱） ----------
        r = c.post(f"{base}/api/debug/prompt", json={"question": "混合检索为什么用 RRF 融合？", "session_id": "verify"})
        dbg = r.json() if r.status_code == 200 else {}
        msgs = dbg.get("messages", [])
        roles = [m["role"] for m in msgs]
        user_msg = next((m["content"] for m in msgs if m["role"] == "user"), "")
        check("L4", "debug/prompt 返回 system+user", roles[:2] == ["system", "user"], str(roles))
        check("L4", "上下文包含编号资料 [1]", "[1]" in user_msg and "【参考资料】" in user_msg,
              f"user_len={len(user_msg)}")
        check("L4", "同时返回结构化 sources", len(dbg.get("sources", [])) >= 1,
              f"sources={len(dbg.get('sources', []))}")

        # ---------- L5 生成层 ----------
        if not llm_ready:
            check("L5", "非流式回答非空", None, "SKIP：未配置 LLM_API_KEY")
            check("L5", "SSE 流式事件序列", None, "SKIP：未配置 LLM_API_KEY")
        else:
            r = c.post(f"{base}/api/chat", json={"question": "混合检索和重排序分别解决什么问题？", "session_id": "verify"})
            d = r.json() if r.status_code == 200 else {}
            ans = d.get("answer", "")
            check("L5", "非流式回答非空", r.status_code == 200 and len(ans) >= 20,
                  f"http={r.status_code} len={len(ans)}")
            srcs = d.get("sources", [])
            cites = [int(t) for t in re.findall(r"\[(\d+)\]", ans)]
            cite_ok = (not cites) or all(1 <= n <= len(srcs) for n in cites)
            check("L5", "引用编号落在 sources 范围内", cite_ok,
                  f"cites={sorted(set(cites))} sources={len(srcs)}")
            # SSE
            n_tok, saw_meta, saw_done, err = 0, False, False, None
            with c.stream("POST", f"{base}/api/chat/stream",
                          json={"question": "引用来源是怎么实现的？", "session_id": "verify"}) as resp:
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    evt = json.loads(line[5:].strip())
                    if evt["type"] == "meta":
                        saw_meta = True
                    elif evt["type"] == "token":
                        n_tok += 1
                    elif evt["type"] == "done":
                        saw_done = True
                    elif evt["type"] == "error":
                        err = evt["data"].get("message")
            check("L5", "SSE：meta→token→done 且无 error", saw_meta and n_tok > 0 and saw_done and err is None,
                  f"meta={saw_meta} tokens={n_tok} done={saw_done} err={err}")

        # ---------- L6 多轮 ----------
        if not llm_ready:
            check("L6", "多轮历史可用", None, "SKIP：未配置 LLM_API_KEY")
        else:
            c.post(f"{base}/api/chat", json={"question": "什么是 LCEL？", "session_id": "verify-multi"})
            r = c.post(f"{base}/api/chat", json={"question": "那它怎么逐 token 输出？", "session_id": "verify-multi"})
            d = r.json() if r.status_code == 200 else {}
            check("L6", "第二问标记 used_history", r.status_code == 200 and d.get("used_history") is True,
                  f"rewritten={d.get('rewritten_question')}")

        # ---------- L7 鲁棒性 ----------
        r = c.post(f"{base}/api/documents/upload", files={"file": ("bad.exe", b"MZ...", "application/octet-stream")})
        check("L7", "非法扩展名返回 400", r.status_code == 400, f"http={r.status_code}")

        r = c.delete(f"{base}/api/documents/{temp_id}") if temp_id else None
        check("L7", "删除自检文档 200", bool(r is not None and r.status_code == 200))
        after = len(c.get(f"{base}/api/documents").json())
        check("L7", "删除后文档数恢复", after == baseline_docs, f"before={baseline_docs} after={after}")
        hits2 = c.post(f"{base}/api/search", json={"question": unique, "top_k": 3}).json().get("hits", [])
        check("L7", "删除后索引同步（旧内容不再置顶）",
              not hits2 or hits2[0]["doc_title"] != "自检临时文档",
              f"top={hits2[0]['doc_title'] if hits2 else '(none)'}")

    finally:
        try:
            if temp_id:
                c.delete(f"{base}/api/documents/{temp_id}")
        except Exception:
            pass
        (data_dir / "_verify_doc.md").unlink(missing_ok=True)

    # ---------- 汇总 ----------
    n_pass = sum(1 for *_, s, _d in results if s == PASS)
    n_fail = sum(1 for *_, s, _d in results if s == FAIL)
    n_skip = sum(1 for *_, s, _d in results if s == SKIP)
    print("\n" + "=" * 60)
    print(f"验收结果：PASS {n_pass} / FAIL {n_fail} / SKIP {n_skip}")
    if n_fail:
        print("未通过项：")
        for layer, name, status, detail in results:
            if status == FAIL:
                print(f"  - {layer} {name} | {detail}")
    print("=" * 60)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
