"""Token 统计与成本核算（AI 中台能力之二）。

为什么要做（设计要点）：
    线上 LLM 应用最大的可变成本就是 token。没有统计就没有治理：
    你不知道哪个任务最贵、哪个用户最能烧、缓存/小模型到底省了多少。

实现要点：
1. **统一记录点**：所有 LLM 调用都经过 `UsageStats.record(...)`，字段含
   任务、模型、输入/输出 token、估算成本、会话 id、时间；
2. **游标式取用量**：非流式从 `AIMessage.usage_metadata` 直接取；
   流式在 `stream_usage=True` 下由最后一个 chunk 带回用量；拿不到时按字数估算并标记 `estimated`；
3. **内存聚合 + JSONL 落盘**：接口查询快，进程重启不丢历史（追加写，简单可靠）；
4. **线程安全**：LLM 调用发生在线程池里，用锁保护聚合结构。
"""
from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class UsageRecord:
    ts: str
    task: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    session_id: str = ""
    estimated: bool = False


def extract_usage(obj) -> tuple[int, int] | None:
    """从 LangChain 消息对象里取 (input_tokens, output_tokens)。取不到返回 None。"""
    meta = getattr(obj, "usage_metadata", None)
    if not meta:
        return None
    if isinstance(meta, dict):
        inp = meta.get("input_tokens") or meta.get("prompt_tokens") or 0
        out = meta.get("output_tokens") or meta.get("completion_tokens") or 0
        if inp or out:
            return int(inp), int(out)
    return None


def estimate_tokens(text: str) -> int:
    """粗略估算：中文约 1 字 ≈ 0.7 token，取 len/1.5 作为保守近似。"""
    return max(1, int(len(text) / 1.5))


class UsageStats:
    def __init__(self, path: Path, *, recent_size: int = 500) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._recent: deque[UsageRecord] = deque(maxlen=recent_size)
        self._totals = {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }
        self._by_model: dict[str, dict] = {}
        self._by_task: dict[str, dict] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = UsageRecord(**json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
                self._accumulate(rec, persist=False)
                self._recent.append(rec)

    def _append(self, rec: UsageRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    # ---------- 聚合 ----------
    def _accumulate(self, rec: UsageRecord, *, persist: bool = True) -> None:
        self._totals["calls"] += 1
        self._totals["prompt_tokens"] += rec.prompt_tokens
        self._totals["completion_tokens"] += rec.completion_tokens
        self._totals["total_tokens"] += rec.total_tokens
        self._totals["cost"] = round(self._totals["cost"] + rec.cost, 6)
        for bucket, key in ((self._by_model, rec.model), (self._by_task, rec.task)):
            item = bucket.setdefault(
                key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0}
            )
            item["calls"] += 1
            item["prompt_tokens"] += rec.prompt_tokens
            item["completion_tokens"] += rec.completion_tokens
            item["total_tokens"] += rec.total_tokens
            item["cost"] = round(item["cost"] + rec.cost, 6)
        if persist:
            self._append(rec)

    def record(
        self,
        *,
        task: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        price_input_per_m: float,
        price_output_per_m: float,
        session_id: str = "",
        estimated: bool = False,
    ) -> UsageRecord:
        cost = prompt_tokens / 1_000_000 * price_input_per_m + completion_tokens / 1_000_000 * price_output_per_m
        rec = UsageRecord(
            ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            task=task,
            model=model,
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens) + int(completion_tokens),
            cost=round(cost, 6),
            session_id=session_id,
            estimated=estimated,
        )
        with self._lock:
            self._accumulate(rec)
            self._recent.append(rec)
        return rec

    # ---------- 查询 ----------
    def summary(self) -> dict:
        with self._lock:
            return {
                "totals": dict(self._totals),
                "by_model": {k: dict(v) for k, v in self._by_model.items()},
                "by_task": {k: dict(v) for k, v in self._by_task.items()},
                "recent_calls": len(self._recent),
                "storage": str(self._path),
            }

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            items = list(self._recent)[-limit:]
        return [asdict(r) for r in reversed(items)]

    def reset(self) -> None:
        with self._lock:
            self._recent.clear()
            self._totals = dict.fromkeys(self._totals, 0)  # type: ignore[arg-type]
            self._totals["cost"] = 0.0
            self._by_model.clear()
            self._by_task.clear()
