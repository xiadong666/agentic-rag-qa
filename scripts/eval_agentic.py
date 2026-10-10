"""Agentic RAG 量化评测：检索准确率 / 应答准确率 / 幻觉率（前后对比）。

为什么写这个脚本（面试必答）：
    "我感觉改完更准了"不是证据。Agentic RAG 相对朴素 RAG 的收益必须量化：
    ① 检索层：期望文档是否进上下文、排在第几（Hit@1 / Recall@k / MRR）；
    ② 应答层：回答是否切题且被资料支持（LLM-as-Judge 三分类）；
    ③ 幻觉层：无答案问题上是否"编造"或"硬答"，有答案问题上是否"编造引用/无依据陈述"。

评测口径（三层，互不混淆）：
    - retrieval_accuracy@k = 期望文档出现在 top-k 来源里的比例      → 检索准确率
    - correctness          = 回答正确/正确拒答的比例                → 应答准确率
    - hallucination_rate   = 有依据问题上出现"无依据陈述/编造引用"
                             + 无答案问题上"编造答案"
                             + 有答案问题上"错误拒答" 的比例        → 幻觉率
      （错误拒答计入幻觉侧是刻意的：RAG 里"该答不答"和"不该答乱答"
        都是"答案与事实不符"，工程上必须一起看，否则可以把幻觉率刷成 0。）

用法：
    # 1) 基线（现有朴素 RAG 链路，进程内直调 engine，不依赖 HTTP）
    .venv\\Scripts\\python scripts\\eval_agentic.py --mode baseline

    # 2) Agentic RAG（改造后的 Agent 编排）
    .venv\\Scripts\\python scripts\\eval_agentic.py --mode agentic

    # 3) 前后对比（一次跑完，输出对比表 + JSON 报告）
    .venv\\Scripts\\python scripts\\eval_agentic.py --mode both

    # 4) 换个标注集 / 只跑前 N 题（省时间）
    .venv\\Scripts\\python scripts\\eval_agentic.py --mode both --limit 8

产出：
    data/eval_report_<mode>.json   逐题明细（问题/检索排名/回答/判定/耗时），可复现证据链
    data/eval_compare.json         两次运行的关键指标对比（供文档与简历引用）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402

DEFAULT_SET = ROOT / "data" / "eval_set_agentic.json"

# ----------------------------------------------------------------- 判定提示词
JUDGE_SYSTEM = """你是严格的 RAG 答案评审员。你会收到：问题、检索到的资料（可能为空）、系统回答。
请判断回答是否"忠于资料且切题"，只输出一个 JSON 对象，不要输出任何解释性文字。

判定标签 verdict 只能取以下四个值之一：
- "correct"       : 回答切题，事实性内容都有资料依据（允许合理概括与归纳），或正确地说明了资料不足。
- "fabricated"    : 存在**资料中找不到依据的事实性陈述**（具体数字、人名、时间、型号、引用编号指向的内容），
                    或引用了不存在的资料编号 [n]。
- "false_refusal" : 资料中本来有足够信息可以回答，但回答却声称"资料库中没有找到/无法回答"。
- "should_refuse" : 资料中确实没有足够信息，回答正确地说明了无法作答（这是正确行为，不算幻觉）。

必须区分以下三类，只有第一类才算 fabricated：
① 事实性断言：可以被资料证实或证伪的具体事实（数字、名称、时间、结论、引用的内容）→ 无依据即 fabricated；
② 由资料原则合理推出的操作性建议（如"建议记录告警""建议补充文档""建议先降级再排查"）→ 不算 fabricated；
③ 回答中主动声明的局限与提示（如"资料中未涉及 X，无法给出"）→ 不算 fabricated。

输出 JSON 字段：
{"verdict": "...", "reason": "一句话理由", "unsupported": ["无依据的事实性陈述原文，最多3条"]}
"""

JUDGE_TEMPLATE = """【问题】
{question}

【检索到的资料】
{context}

【系统回答】
{answer}

请只输出 JSON。"""


# ----------------------------------------------------------------- 数据结构
@dataclass
class CaseResult:
    id: str
    type: str
    question: str
    answerable: bool
    expect_docs: list[str]
    rank: int = 0                 # 期望文档在来源里的最好名次，0 = 未命中
    hit1: bool = False
    hitk: bool = False
    rr: float = 0.0
    n_sources: int = 0
    answer: str = ""
    elapsed_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    verdict: str = ""
    judge_reason: str = ""
    unsupported: list[str] = field(default_factory=list)
    keyword_hits: list[str] = field(default_factory=list)
    # 证据层诊断：期望文档只有 1 篇时"按文档算命中"没有区分度，
    # 必须看"检索到的正文里到底有没有回答所需的关键信息"
    evidence_chars: int = 0
    evidence_kw_recall: float = 0.0
    evidence_kw_missing: list[str] = field(default_factory=list)
    llm_calls: int = 0
    rounds: int = 0
    stop_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "question": self.question,
            "answerable": self.answerable, "expect_docs": self.expect_docs,
            "rank": self.rank, "hit1": self.hit1, "hitk": self.hitk, "rr": round(self.rr, 4),
            "n_sources": self.n_sources, "elapsed_ms": self.elapsed_ms,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "cost": round(self.cost, 8), "verdict": self.verdict, "judge_reason": self.judge_reason,
            "unsupported": self.unsupported, "keyword_hits": self.keyword_hits,
            "evidence_chars": self.evidence_chars,
            "evidence_kw_recall": round(self.evidence_kw_recall, 4),
            "evidence_kw_missing": self.evidence_kw_missing,
            "llm_calls": self.llm_calls, "rounds": self.rounds, "stop_reason": self.stop_reason,
            "answer": self.answer, "error": self.error,
        }


def _load_cases(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("meta", {}), data.get("cases", [])


def _rank_of(expect: list[str], titles: list[str]) -> int:
    best = 0
    for i, t in enumerate(titles, start=1):
        if t in expect and (best == 0 or i < best):
            best = i
    return best


def _keyword_recall(keywords: list[str], text: str) -> tuple[list[str], list[str]]:
    hit = [k for k in keywords if k and k in text]
    miss = [k for k in keywords if k and k not in text]
    return hit, miss


def _parse_json_loose(text: str) -> dict | None:
    """从模型输出里抠出第一个 JSON 对象（模型偶尔会包 ```json 或加前缀）。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _fill_evidence_metrics(res: CaseResult, case: dict, contexts: list[str]) -> None:
    """把"检索到的正文"折算成可量化的检索准确率：关键要点覆盖度。

    为什么用这个口径：知识库里期望文档只有 1 篇时，"期望文档是否进 top-k"
    恒为真，指标失去区分度；真正决定能不能答对的是
    **进去的正文里有没有回答所需的关键信息**。
    """
    res.evidence_chars = sum(len(c or "") for c in contexts)
    kws = [k for k in (case.get("ref_keywords") or []) if k]
    if not kws:
        res.evidence_kw_recall = 1.0
        return
    blob = "\n".join(contexts)
    found = [k for k in kws if k in blob]
    res.evidence_kw_missing = [k for k in kws if k not in blob]
    res.evidence_kw_recall = len(found) / len(kws)


# ----------------------------------------------------------------- 评测主逻辑
class Evaluator:
    def __init__(self, settings: Settings, *, limit: int | None = None, top_k: int = 4,
                 use_history: bool = True, scope_docs: list[str] | None = None) -> None:
        self.settings = settings
        self.top_k = top_k
        self.use_history = use_history
        self.limit = limit
        self.scope_docs = scope_docs or []
        self._judge_llm = None

    # ---- 检索口径：只看评测范围内的文档 ----
    def rank_in_scope(self, expect: list[str], titles: list[str]) -> tuple[int, list[str]]:
        """在"评测范围内"计算名次。

        为什么需要它：困难集里 3 篇速查文档是**干扰项**（同一知识库、话题相近），
        期望文档只有 1 篇 66 分块的长文档。若不在范围内排名，
        干扰文档会把名次挤掉，指标反映的就不是"能不能找到那篇长文档"了。
        """
        scoped = [t for t in titles if not self.scope_docs or t in self.scope_docs]
        return _rank_of(expect, scoped), scoped

    # ---- 判官模型（用 answer 档模型，独立于被测链路） ----
    def judge_llm(self):
        if self._judge_llm is None:
            from app.core.llm import create_chat_model

            self._judge_llm = create_chat_model(self.settings, model=self.settings.llm_model)
        return self._judge_llm

    async def judge(self, question: str, contexts: list[str], answer: str) -> tuple[str, str, list[str]]:
        if not answer.strip():
            return "false_refusal", "回答为空", []
        ctx = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(contexts, 1)) or "（无检索资料）"
        msg = JUDGE_TEMPLATE.format(question=question, context=ctx, answer=answer)
        from langchain_core.messages import HumanMessage, SystemMessage

        for attempt in range(2):
            try:
                resp = await self.judge_llm().ainvoke(
                    [SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=msg)]
                )
                text = resp.content if isinstance(resp.content, str) else str(resp.content)
                obj = _parse_json_loose(text)
                if obj and obj.get("verdict") in {"correct", "fabricated", "false_refusal", "should_refuse"}:
                    return (
                        obj["verdict"],
                        str(obj.get("reason", ""))[:200],
                        [str(x)[:160] for x in (obj.get("unsupported") or [])][:3],
                    )
            except Exception as e:  # noqa: BLE001
                if attempt == 1:
                    return "unknown", f"judge 调用失败：{type(e).__name__}: {e}", []
            await asyncio.sleep(0.5)
        return "unknown", "judge 输出无法解析", []

    # ---- 单题执行（由子类实现：朴素链路 / Agent 链路） ----
    async def run_case(self, case: dict) -> CaseResult:  # pragma: no cover - 抽象
        raise NotImplementedError

    async def run(self, cases: list[dict]) -> dict:
        results: list[CaseResult] = []
        total = len(cases)
        for i, case in enumerate(cases, start=1):
            t0 = time.perf_counter()
            try:
                res = await self.run_case(case)
            except Exception as e:  # noqa: BLE001
                res = CaseResult(id=case["id"], type=case.get("type", ""), question=case["question"],
                                 answerable=bool(case.get("answerable", True)),
                                 expect_docs=case.get("expect_docs", []),
                                 error=f"{type(e).__name__}: {e}")
            res.elapsed_ms = res.elapsed_ms or int((time.perf_counter() - t0) * 1000)
            results.append(res)
            flag = "✓" if res.verdict in ("correct", "should_refuse") else ("…" if res.verdict in ("", "unknown") else "✗")
            print(f"[{i:>2}/{total}] {res.id:<3} rank={res.rank or '-':<2} {flag} {res.verdict or res.error or '?':<13} "
                  f"{res.elapsed_ms:>6}ms  {case['question'][:34]}")
        return self.summarize(results)

    # ---- 指标聚合 ----
    @staticmethod
    def summarize(results: list[CaseResult]) -> dict:
        answerable = [r for r in results if r.answerable and not r.error]
        unanswerable = [r for r in results if not r.answerable and not r.error]
        judged = [r for r in results if r.verdict and r.verdict != "unknown"]

        def rate(num: int, den: int) -> float:
            return round(num / den, 4) if den else 0.0

        hit1 = sum(1 for r in answerable if r.hit1)
        hitk = sum(1 for r in answerable if r.hitk)
        mrr = statistics.fmean([r.rr for r in answerable]) if answerable else 0.0

        # --- 证据内容命中率：检索到的正文是否包含回答所需的要点 ---
        # 期望文档只有 1 篇时"按文档算命中"没有区分度，必须下沉到内容层。
        kw_ok = [r for r in answerable if r.evidence_kw_recall >= 1.0]
        kw_mean = statistics.fmean([r.evidence_kw_recall for r in answerable]) if answerable else 0.0

        # --- 应答准确率：答对 + 正确拒答 ---
        correct = [r for r in judged if r.verdict == "correct"]
        should_refuse = [r for r in judged if r.verdict == "should_refuse"]
        correctness = rate(len(correct) + len(should_refuse), len(judged))

        # --- 生成层准确率：只在"检索到了资料"的前提下看生成质量 ---
        # 全链路准确率会被"检索不到 → 拒答"拉低；把这一层拆出来才能定位问题出在哪一层。
        gen_scope = [r for r in judged if r.evidence_chars > 0]
        gen_ok = [r for r in gen_scope if r.verdict == "correct"]

        # --- 幻觉率：编造 + 无答案却硬答 + 有答案却拒答 ---
        fabricated = [r for r in judged if r.verdict == "fabricated"]
        false_refusal = [r for r in judged if r.verdict == "false_refusal"]
        halluc = len(fabricated) + len(false_refusal)
        hallucination_rate = rate(halluc, len(judged))

        # 无答案问题上的"幻觉性回答"（本该拒答却作答）
        ua_bad = [r for r in unanswerable if r.verdict in ("correct", "fabricated")]
        false_answer_rate = rate(len(ua_bad), len(unanswerable))
        ua_refused = [r for r in unanswerable if r.verdict == "should_refuse"]
        refusal_rate = rate(len(ua_refused), len(unanswerable))

        lat = [r.elapsed_ms for r in results if r.elapsed_ms]
        pt = sum(r.prompt_tokens for r in results)
        ct = sum(r.completion_tokens for r in results)
        cost = sum(r.cost for r in results)
        calls = [r.llm_calls for r in results if r.llm_calls]
        return {
            "n_cases": len(results),
            "n_answerable": len(answerable),
            "n_unanswerable": len(unanswerable),
            "retrieval": {
                "hit_at_1": rate(hit1, len(answerable)),
                "recall_at_k": rate(hitk, len(answerable)),
                "mrr": round(mrr, 4),
                "evidence_kw_recall": round(kw_mean, 4),
                "evidence_kw_full_hit": rate(len(kw_ok), len(answerable)),
                "avg_evidence_chars": int(statistics.fmean([r.evidence_chars for r in answerable]))
                if answerable else 0,
            },
            "answer": {
                "correctness": correctness,
                "generation_accuracy": rate(len(gen_ok), len(gen_scope)),
                "n_correct": len(correct),
                "n_should_refuse": len(should_refuse),
                "n_fabricated": len(fabricated),
                "n_false_refusal": len(false_refusal),
                "n_unknown": sum(1 for r in results if r.verdict == "unknown"),
                "n_no_evidence": sum(1 for r in judged if r.evidence_chars == 0),
            },
            "hallucination": {
                "rate": hallucination_rate,
                "n": halluc,
                "denominator": len(judged),
                "false_answer_rate_on_unanswerable": false_answer_rate,
                "refusal_rate_on_unanswerable": refusal_rate,
                "n_false_answer": len(ua_bad),
                "n_correct_refusal": len(ua_refused),
            },
            "cost": {
                "avg_latency_ms": int(statistics.fmean(lat)) if lat else 0,
                "p50_latency_ms": int(statistics.median(lat)) if lat else 0,
                "total_prompt_tokens": pt,
                "total_completion_tokens": ct,
                "total_tokens": pt + ct,
                "total_cost": round(cost, 6),
                "avg_cost_per_query": round(cost / len(results), 8) if results else 0.0,
                "avg_llm_calls": round(statistics.fmean(calls), 2) if calls else 0.0,
            },
            "cases": [r.to_dict() for r in results],
        }


# ----------------------------------------------------------------- 朴素 RAG 评测器
class BaselineEvaluator(Evaluator):
    """现有链路：rewrite → 混合检索 → 重排 → 拼上下文 → 生成（无自我反思）。"""

    def __init__(self, engine, **kw) -> None:
        super().__init__(engine.settings, **kw)
        self.engine = engine

    async def run_case(self, case: dict) -> CaseResult:
        res = CaseResult(id=case["id"], type=case.get("type", ""), question=case["question"],
                         answerable=bool(case.get("answerable", True)),
                         expect_docs=case.get("expect_docs", []))
        sid = f"eval-baseline-{case['id']}"
        # 多轮：先跑一轮"前序问题"把历史灌进会话
        pre = case.get("pre_question")
        if pre and self.use_history:
            await self.engine.answer(pre, sid, use_history=True)

        t0 = time.perf_counter()
        out = await self.engine.answer(case["question"], sid, use_history=self.use_history)
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        res.answer = out.get("answer", "")
        sources = out.get("sources", [])
        res.n_sources = len(sources)
        ranked = await self.engine._search_ranked(
            out.get("rewritten_question") or case["question"], self.top_k
        )
        titles = [s.doc_title for s in ranked[0]]
        res.n_sources = len(titles)
        res.rank, scoped = self.rank_in_scope(res.expect_docs, titles)
        res.n_sources = len(scoped)
        res.hit1 = res.rank == 1
        res.hitk = 1 <= res.rank <= self.top_k
        res.rr = (1.0 / res.rank) if res.rank else 0.0
        contexts = [r.chunk.text for r in ranked[1]]
        _fill_evidence_metrics(res, case, contexts)
        if case.get("ref_keywords"):
            res.keyword_hits, _miss = _keyword_recall(case["ref_keywords"], res.answer)
        usage = out.get("usage") or {}
        res.prompt_tokens = usage.get("prompt_tokens", 0)
        res.completion_tokens = usage.get("completion_tokens", 0)
        res.cost = usage.get("cost", 0.0)
        # 朴素链路的模型调用次数 = 生成 + 可能的"问题改写"（改写走 rewrite 档）。
        # 不统计的话对比表会显示"0 次/问"，那是失真而不是优势。
        res.llm_calls = 1 + (1 if out.get("rewritten_question") else 0)
        res.verdict, res.judge_reason, res.unsupported = await self.judge(
            case["question"], contexts, res.answer
        )
        return res


# ----------------------------------------------------------------- Agent 评测器
class AgenticEvaluator(Evaluator):
    """改造后链路：Agent 编排（plan → act → grade → reflect/rewrite → verify → answer）。"""

    def __init__(self, engine, **kw) -> None:
        super().__init__(engine.settings, **kw)
        self.engine = engine

    async def run_case(self, case: dict) -> CaseResult:
        res = CaseResult(id=case["id"], type=case.get("type", ""), question=case["question"],
                         answerable=bool(case.get("answerable", True)),
                         expect_docs=case.get("expect_docs", []))
        sid = f"eval-agentic-{case['id']}"
        pre = case.get("pre_question")
        if pre and self.use_history:
            await self.engine.agent_answer(pre, sid, use_history=True)

        t0 = time.perf_counter()
        out = await self.engine.agent_answer(case["question"], sid, use_history=self.use_history)
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        res.answer = out.get("answer", "")
        hits = out.get("agent", {}).get("evidence", []) or []
        titles = [h["doc_title"] for h in hits]
        res.rank, scoped = self.rank_in_scope(res.expect_docs, titles)
        res.n_sources = len(scoped)
        res.hit1 = res.rank == 1
        res.hitk = 1 <= res.rank <= self.top_k
        res.rr = (1.0 / res.rank) if res.rank else 0.0
        contexts = [h.get("text", "") for h in hits]
        _fill_evidence_metrics(res, case, contexts)
        agent_info = out.get("agent") or {}
        res.llm_calls = int((out.get("usage") or {}).get("llm_calls") or 0)
        res.rounds = int(agent_info.get("rounds") or 0)
        res.stop_reason = str(agent_info.get("stop_reason") or "")
        if case.get("ref_keywords"):
            res.keyword_hits, _miss = _keyword_recall(case["ref_keywords"], res.answer)
        usage = out.get("usage") or {}
        res.prompt_tokens = usage.get("prompt_tokens", 0)
        res.completion_tokens = usage.get("completion_tokens", 0)
        res.cost = usage.get("cost", 0.0)
        res.verdict, res.judge_reason, res.unsupported = await self.judge(
            case["question"], contexts, res.answer
        )
        return res


# ----------------------------------------------------------------- 报告
def print_report(title: str, rep: dict) -> None:
    r, a, h, c = rep["retrieval"], rep["answer"], rep["hallucination"], rep["cost"]
    print("\n" + "=" * 78)
    print(f"【{title}】样本 {rep['n_cases']}（可答 {rep['n_answerable']} / 不可答 {rep['n_unanswerable']}）")
    print("-" * 78)
    print(f"检索准确率   Hit@1 = {r['hit_at_1']:.2%}   Recall@k = {r['recall_at_k']:.2%}   MRR = {r['mrr']:.3f}")
    print(f"证据命中率   要点全覆盖 = {r['evidence_kw_full_hit']:.2%}   "
          f"要点平均覆盖 = {r['evidence_kw_recall']:.2%}   平均证据 {r['avg_evidence_chars']} 字")
    print(f"应答准确率   correctness = {a['correctness']:.2%}"
          f"（答对 {a['n_correct']} + 正确拒答 {a['n_should_refuse']}）"
          f"   生成层准确率 = {a['generation_accuracy']:.2%}")
    print(f"幻觉率       {h['rate']:.2%} = (编造 {a['n_fabricated']} + 错误拒答 {a['n_false_refusal']}) "
          f"/ 已判定 {h['denominator']}")
    print(f"无答案问题   正确拒答率 = {h['refusal_rate_on_unanswerable']:.2%}   "
          f"误答率 = {h['false_answer_rate_on_unanswerable']:.2%}（{h['n_false_answer']} 例）")
    print(f"成本延迟     平均 {c['avg_latency_ms']}ms / 中位 {c['p50_latency_ms']}ms / "
          f"模型调用 {c['avg_llm_calls']} 次/问 / 总 token {c['total_tokens']} / "
          f"单问 {c['avg_cost_per_query']:.6f} 元")
    print("=" * 78)


def print_compare(base: dict, ag: dict) -> None:
    print("\n" + "#" * 78)
    print("# 前后对比：朴素 RAG → Agentic RAG")
    print("#" * 78)
    rows: list[tuple[str, float, float, str]] = [
        ("检索 Hit@1", base["retrieval"]["hit_at_1"], ag["retrieval"]["hit_at_1"], "pct"),
        ("检索 Recall@k", base["retrieval"]["recall_at_k"], ag["retrieval"]["recall_at_k"], "pct"),
        ("检索 MRR", base["retrieval"]["mrr"], ag["retrieval"]["mrr"], "num"),
        ("证据要点全覆盖率", base["retrieval"]["evidence_kw_full_hit"],
         ag["retrieval"]["evidence_kw_full_hit"], "pct"),
        ("证据要点平均覆盖", base["retrieval"]["evidence_kw_recall"],
         ag["retrieval"]["evidence_kw_recall"], "pct"),
        ("应答准确率", base["answer"]["correctness"], ag["answer"]["correctness"], "pct"),
        ("生成层准确率", base["answer"]["generation_accuracy"],
         ag["answer"]["generation_accuracy"], "pct"),
        ("幻觉率", base["hallucination"]["rate"], ag["hallucination"]["rate"], "pct"),
        ("无答案误答率", base["hallucination"]["false_answer_rate_on_unanswerable"],
         ag["hallucination"]["false_answer_rate_on_unanswerable"], "pct"),
        ("无答案正确拒答率", base["hallucination"]["refusal_rate_on_unanswerable"],
         ag["hallucination"]["refusal_rate_on_unanswerable"], "pct"),
    ]
    print(f"{'指标':<20}{'朴素 RAG':>12}{'Agentic RAG':>14}{'变化':>14}")
    print("-" * 78)
    for name, b, t, kind in rows:
        if kind == "num":
            print(f"{name:<20}{b:>12.3f}{t:>14.3f}{t - b:>+14.3f}")
        else:
            print(f"{name:<20}{b:>11.2%}{t:>13.2%}{(t - b):>+13.2%}")
    lb, la = base["cost"]["avg_latency_ms"], ag["cost"]["avg_latency_ms"]
    cb, ca = base["cost"]["avg_cost_per_query"], ag["cost"]["avg_cost_per_query"]
    print(f"{'平均延迟(ms)':<20}{lb:>12}{la:>14}{la - lb:>+14}")
    print(f"{'单问成本(元)':<20}{cb:>12.6f}{ca:>14.6f}{ca - cb:>+14.6f}")
    print(f"{'平均模型调用次数':<20}{'—':>12}{ag['cost']['avg_llm_calls']:>14}")
    print("#" * 78)


# ----------------------------------------------------------------- main
async def build_engine(settings: Settings):
    from app.core.engine import RAGEngine

    settings.ensure_dirs()
    engine = RAGEngine(settings)
    await engine.initialize()
    return engine


async def seed_if_empty(engine, sample_dir: Path, titles: dict[str, str] | None = None,
                        extra_docs: list[str] | None = None) -> None:
    """评测库为空时自动灌入语料：让评测与"固定语料"这个前提强绑定。

    为什么必须固定语料：Recall@k / MRR 依赖"答案在哪篇文档里"，
    知识库一变，同一套标注集的期望文档就对不上了，指标也就不可比。
    extra_docs 用于把真实长文档（如 66 分块的面试题库）也灌进来当干扰项/主语料。
    """
    if engine.store.total_chunks() > 0:
        print(f"评测库已有 {len(engine.store.docs)} 篇文档 / {engine.store.total_chunks()} 分块，跳过灌库")
        return
    files = sorted(p for p in sample_dir.glob("*") if p.is_file())
    for p in extra_docs or []:
        f = Path(p) if Path(p).is_absolute() else (ROOT / p)
        if f.is_file():
            files.append(f)
        else:
            print(f"  [warn] 额外语料不存在，跳过：{f}")
    if not files:
        raise SystemExit(f"没有可用语料：{sample_dir}")
    for f in files:
        title = (titles or {}).get(f.stem, f.stem)
        info = await engine.ingest_file(str(f), f.name, title)
        print(f"  灌库 {f.name}: {info['chunk_count']} chunks")
    print(f"评测库就绪：{len(engine.store.docs)} 篇文档 / {engine.store.total_chunks()} 分块")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "agentic", "both"], default="both")
    ap.add_argument("--set", default=str(DEFAULT_SET), help="标注集 JSON 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0 = 全部）")
    ap.add_argument("--top-k", type=int, default=4, help="检索准确率按 top-k 计算（默认 4，与 rerank_top_k 对齐）")
    ap.add_argument("--out-dir", default=str(ROOT / "data"))
    ap.add_argument("--data-dir", default="", help="评测用数据目录（留空 = 用 .env/DATA_DIR；建议传绝对路径）")
    ap.add_argument("--tag", default="", help="报告文件后缀，用于区分不同评测集（如 easy / hard）")
    args = ap.parse_args()

    settings = get_settings()
    if args.data_dir:
        settings = settings.model_copy(update={"data_dir": Path(args.data_dir).resolve()})
    if not settings.llm_ready:
        print("未配置 LLM_API_KEY：评测需要 LLM 判官，无法运行。")
        return 2

    meta, cases = _load_cases(Path(args.set))
    if args.limit:
        cases = cases[: args.limit]
    print(f"评测集：{meta.get('name', args.set)}（{len(cases)} 题）| 判官模型 {settings.llm_model}")
    print(f"数据目录：{settings.data_dir}")

    engine = await build_engine(settings)
    await seed_if_empty(engine, ROOT / "sample_docs", extra_docs=meta.get("extra_docs") or [])
    print(f"知识库：{len(engine.store.docs)} docs / {engine.store.total_chunks()} chunks | "
          f"rerank={'on' if engine.reranker is not None else 'off'}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: dict[str, dict] = {}
    scope = meta.get("scope_docs") or []
    suffix = f"_{args.tag}" if args.tag else ""

    if args.mode in ("baseline", "both"):
        ev = BaselineEvaluator(engine, limit=args.limit, top_k=args.top_k, scope_docs=scope)
        rep = await ev.run(cases)
        print_report("基线：朴素 RAG", rep)
        (out_dir / f"eval_report_baseline{suffix}.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        reports["baseline"] = rep

    if args.mode in ("agentic", "both"):
        if not hasattr(engine, "agent_answer"):
            print("当前代码还没有 agent_answer（Agentic RAG 尚未接入），跳过 agentic 评测。")
            return 1
        ev = AgenticEvaluator(engine, limit=args.limit, top_k=args.top_k, scope_docs=scope)
        rep = await ev.run(cases)
        print_report("改造后：Agentic RAG", rep)
        (out_dir / f"eval_report_agentic{suffix}.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        reports["agentic"] = rep

    if len(reports) == 2:
        base, ag = reports["baseline"], reports["agentic"]
        print_compare(base, ag)
        compare = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_cases": base["n_cases"],
            "baseline": {k: base[k] for k in ("retrieval", "answer", "hallucination", "cost")},
            "agentic": {k: ag[k] for k in ("retrieval", "answer", "hallucination", "cost")},
            "delta": {
                "hit_at_1": round(ag["retrieval"]["hit_at_1"] - base["retrieval"]["hit_at_1"], 4),
                "recall_at_k": round(ag["retrieval"]["recall_at_k"] - base["retrieval"]["recall_at_k"], 4),
                "mrr": round(ag["retrieval"]["mrr"] - base["retrieval"]["mrr"], 4),
                "correctness": round(ag["answer"]["correctness"] - base["answer"]["correctness"], 4),
                "hallucination_rate": round(ag["hallucination"]["rate"] - base["hallucination"]["rate"], 4),
                "avg_latency_ms": ag["cost"]["avg_latency_ms"] - base["cost"]["avg_latency_ms"],
                "avg_cost_per_query": round(ag["cost"]["avg_cost_per_query"] - base["cost"]["avg_cost_per_query"], 8),
            },
        }
        (out_dir / f"eval_compare{suffix}.json").write_text(
            json.dumps(compare, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入：{out_dir}\\eval_report_baseline{suffix}.json / "
              f"eval_report_agentic{suffix}.json / eval_compare{suffix}.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
