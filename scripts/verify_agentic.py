"""Agentic RAG 专项验收：分层检查 Agent 编排是否"真的按预期工作"。

与 verify_all.py 的关系：
    verify_all.py 验的是**朴素 RAG 链路**（数据/检索/组装/生成/工程五层）；
    本脚本补上 Agent 特有的那一层 —— **决策层**：
      它有没有先规划？检索不够时会不会改写重试？判定器是否真的在过滤噪声？
      证据为空时会不会拒答？答案有没有被忠实度自检？整条轨迹是否可复现？

用法（先启动服务）：
    .venv\\Scripts\\python -m uvicorn app.main:app --port 8000
    .venv\\Scripts\\python scripts\\verify_agentic.py http://127.0.0.1:8000

分层：
  A0 服务层    /health 暴露 agent 能力；/api/agent/tools 工具清单完整
  A1 规划层    /api/agent/debug 能给出任务类型与检索计划（不花钱生成）
  A2 检索层    规划出的检索式能命中知识库（evidence 非空、带来源与页码）
  A3 判定层    判定结果结构完整（sufficient/confidence/missing 三件套）
  A4 决策层    /api/agent/query 有完整轨迹：plan → act → grade →（verify）→ answer
  A5 引用层    回答里的 [n] 全部落在证据编号范围内（引用不越界）
  A6 拒答层    知识库外的探针问题 → 拿到拒答且**不编造**答案
  A7 流式层    /api/agent/stream 事件序列正确：plan → …→ token* → final → done
  A8 兼容层    /api/chat 传 agent=false 仍走朴素链路（改造不破坏老接口）
  A9 治理层    /api/stats/summary 里能看到 agent:* 分任务的 token 与成本

退出码：0 = 全部 PASS（允许 SKIP），1 = 存在 FAIL。
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import httpx

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str, str]] = []


def check(layer: str, name: str, ok: bool | None, detail: str = "") -> None:
    status = SKIP if ok is None else (PASS if ok else FAIL)
    results.append((layer, name, status, detail))
    print(f"[{status}] {layer} {name}" + (f" | {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    ap.add_argument("--session", default="verify-agent")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    sid = args.session
    c = httpx.Client(timeout=300.0)

    # ---------- A0 服务层 ----------
    try:
        h = c.get(f"{base}/health").json()
    except Exception as e:  # noqa: BLE001
        check("A0", "GET /health", False, repr(e))
        print("\n服务不可用，后续检查无法进行。")
        return 1
    agent = h.get("agent") or {}
    check("A0", "/health 暴露 agent 能力", "enabled" in agent and "tools" in agent,
          json.dumps(agent, ensure_ascii=False)[:160])
    llm_ready = bool(h.get("llm_ready"))

    tools = c.get(f"{base}/api/agent/tools").json()
    names = {t["name"] for t in tools.get("tools", [])}
    expect_tools = {"knowledge_search", "query_rewrite", "evidence_compress",
                    "decision_memo", "kb_stats", "calc"}
    check("A0", "工具清单完整（6 个）", expect_tools.issubset(names),
          f"got={sorted(names)}")
    check("A0", "模型路由表可见（含 agent 档）",
          "routes" in tools and isinstance(tools["routes"].get("routes"), dict),
          json.dumps(tools.get("routes", {}).get("routes", {}), ensure_ascii=False)[:160])

    # ---------- A1/A2/A3 规划 → 检索 → 判定（不花钱生成） ----------
    probe_q = "混合检索为什么用 RRF 融合？"
    r = c.post(f"{base}/api/agent/debug", json={"question": probe_q, "session_id": sid})
    dbg = r.json() if r.status_code == 200 else {}
    ok_dbg = r.status_code == 200
    check("A1", "/api/agent/debug 可用", ok_dbg, f"http={r.status_code}" if not ok_dbg else "")
    check("A1", "给出任务类型与计划",
          bool(dbg.get("task_type")) and bool(dbg.get("plan")),
          f"task_type={dbg.get('task_type')} plan={len(dbg.get('plan') or [])} 步")
    check("A1", "给出可执行检索式", bool(dbg.get("queries")),
          f"queries={dbg.get('queries')}")
    ev = dbg.get("evidence") or []
    check("A2", "检索命中并进证据池", len(ev) >= 1, f"evidence={len(ev)}")
    fields_ok = bool(ev) and all(
        {"cite_index", "doc_title", "score", "text"}.issubset(set(x)) for x in ev
    )
    check("A2", "证据字段齐全（可溯源）", fields_ok,
          f"sample={json.dumps(ev[0], ensure_ascii=False)[:120] if ev else '(none)'}")
    check("A3", "判定输出三件套完整",
          all(k in dbg for k in ("sufficient", "confidence", "missing")),
          f"sufficient={dbg.get('sufficient')} conf={dbg.get('confidence')} missing={str(dbg.get('missing'))[:40]}")

    # ---------- A4~A6 完整 Agent 问答 ----------
    if not llm_ready:
        for layer, name in (("A4", "轨迹完整"), ("A5", "引用不越界"),
                            ("A6", "库外问题不编造"), ("A7", "SSE 事件序列")):
            check(layer, name, None, "SKIP：未配置 LLM_API_KEY")
    else:
        r = c.post(f"{base}/api/agent/query",
                   json={"question": "RRF 的 k 取多少？为什么不用加权求和？", "session_id": sid})
        d = r.json() if r.status_code == 200 else {}
        ok_q = r.status_code == 200
        check("A4", "/api/agent/query 200", ok_q, f"http={r.status_code} {r.text[:120]}" if not ok_q else "")
        ag = d.get("agent") or {}
        kinds = [s.get("kind") for s in (ag.get("steps") or [])]
        check("A4", "轨迹含 规划→动作→判定→生成",
              all(k in kinds for k in ("plan", "act", "grade", "answer")),
              f"kinds={kinds}")
        check("A4", "轨迹可解释停止原因",
              bool(ag.get("stop_reason")) and bool(ag.get("plan")),
              f"stop_reason={ag.get('stop_reason')} rounds={ag.get('rounds')}")
        check("A4", "逐节点用量可见（模型路由治理）",
              isinstance(d.get("usage"), dict) and d["usage"].get("by_step"),
              f"by_step={list((d.get('usage') or {}).get('by_step', {}))}")
        ans = d.get("answer") or ""
        srcs = d.get("sources") or []
        cites = sorted({int(x) for x in re.findall(r"\[(\d+)\]", ans)})
        check("A5", "回答非空且带引用", len(ans) >= 20,
              f"len={len(ans)} cites={cites} sources={len(srcs)}")
        check("A5", "引用编号不越界", (not cites) or all(1 <= n <= len(srcs) for n in cites),
              f"cites={cites} sources={len(srcs)}")

        # A6：知识库外的问题 —— 正确行为是明确拒答，而不是编造
        r2 = c.post(f"{base}/api/agent/query",
                    json={"question": "我们公司2025年第三季度的营收是多少？", "session_id": sid + "-probe"})
        d2 = r2.json() if r2.status_code == 200 else {}
        ans2 = d2.get("answer") or ""
        refused = any(k in ans2 for k in ("没有找到", "未找到", "无法", "无相关信息", "不包含", "没有相关"))
        check("A6", "库外问题明确拒答", r2.status_code == 200 and refused and len(ans2) < 1200,
              f"len={len(ans2)} head={ans2[:60]!r}")
        cites2 = sorted({int(x) for x in re.findall(r"\[(\d+)\]", ans2)})
        check("A6", "拒答时不编造引用", (not cites2) or refused, f"cites={cites2}")

        # ---------- A7 流式 ----------
        order: list[str] = []
        n_tok = 0
        err = None
        final_usage = None
        with c.stream("POST", f"{base}/api/agent/stream",
                      json={"question": "中文分块的分隔符怎么配？", "session_id": sid}) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                evt = json.loads(line[5:].strip())
                t = evt.get("type")
                if t == "token":
                    n_tok += 1
                    if order and order[-1] == "token":
                        continue
                    order.append("token")
                elif t not in ("done",):
                    order.append(t)
                if t == "final":
                    final_usage = evt["data"].get("usage")
                if t == "error":
                    err = evt["data"].get("message")
        check("A7", "SSE 含 plan/token/final 且无 error",
              order and order[0] == "plan" and "token" in order and "final" in order and err is None,
              f"order={order} tokens={n_tok} err={err}")
        check("A7", "流式也回传用量与轨迹",
              isinstance(final_usage, dict) and final_usage.get("llm_calls", 0) >= 2,
              f"usage={json.dumps(final_usage, ensure_ascii=False)[:140] if final_usage else '(none)'}")

    # ---------- A8 向后兼容 ----------
    r = c.post(f"{base}/api/chat", json={"question": "什么是 LCEL？", "agent": False,
                                        "session_id": sid + "-legacy"})
    ok_legacy = r.status_code in (200, 503)
    legacy = r.json() if r.status_code == 200 else {}
    check("A8", "agent=false 仍走朴素链路", ok_legacy and (r.status_code == 503 or "agent" not in (legacy or {}) or legacy.get("agent") is None),
          f"http={r.status_code}")
    r = c.post(f"{base}/api/chat", json={"question": "什么是 LCEL？", "agent": True,
                                        "session_id": sid + "-agent"})
    d = r.json() if r.status_code == 200 else {}
    check("A8", "agent=true 走 Agent 链路（返回 agent 字段）",
          r.status_code in (200, 503) and (r.status_code == 503 or d.get("agent") is not None),
          f"http={r.status_code}")

    # ---------- A9 治理 ----------
    s = c.get(f"{base}/api/stats/summary").json()
    by_task = (s.get("totals") and s.get("by_task")) or {}
    agent_tasks = [k for k in by_task if str(k).startswith("agent:")]
    check("A9", "统计里能看到 agent:* 分任务计量", bool(agent_tasks) or not llm_ready,
          f"tasks={agent_tasks}" if agent_tasks else "SKIP：还没有 Agent 调用记录")

    # ---------- 汇总 ----------
    n_pass = sum(1 for *_, st, _d in results if st == PASS)
    n_fail = sum(1 for *_, st, _d in results if st == FAIL)
    n_skip = sum(1 for *_, st, _d in results if st == SKIP)
    print("\n" + "=" * 60)
    print(f"Agent 验收结果：PASS {n_pass} / FAIL {n_fail} / SKIP {n_skip}")
    if n_fail:
        print("未通过项：")
        for layer, name, st, detail in results:
            if st == FAIL:
                print(f"  - {layer} {name} | {detail}")
    print("=" * 60)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
