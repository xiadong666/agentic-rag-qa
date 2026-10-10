"""对话历史与会话管理。

设计取舍（多轮对话与 RAG 的结合方式）：
A. 简单法：把最近 N 轮问答原文拼进 System/历史区 —— 直白，但占用窗口、
   且用户问“它呢？”时检索词仍然是“它”，召回会偏；
B. 改进法（本项目）：先把“原始问题 + 最近历史”交给 LLM 改写成一条
   “独立问题”（如 “它呢？”→“LangChain 的 LCEL 怎么流式输出？”），
   再用改写后的问题去检索 —— 召回的 query 永远完整可检索；
   改写前的原文历史仍保留在消息里供模型理解上下文。
   代价：改写要多一次 LLM 调用；本地/无 key 环境可关闭（QUERY_REWRITE=false）。

本文件只管“历史存取”；改写逻辑见 engine.py。
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path


class ChatTurn:
    __slots__ = ("question", "answer", "rewritten", "sources_titles", "ts")

    def __init__(self, question: str, answer: str, rewritten: str | None = None,
                 sources_titles: list[str] | None = None):
        self.question = question
        self.answer = answer
        self.rewritten = rewritten
        self.sources_titles = sources_titles or []
        self.ts = ""  # 占位，避免每次实例化都引 datetime

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "rewritten": self.rewritten,
            "sources_titles": self.sources_titles,
        }


class ChatMemory:
    """内存会话表 + JSONL 持久化。会话上限 LRU 淘汰（dict 保序特性）。"""

    def __init__(self, path: Path | None = None, max_sessions: int = 100) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._sessions: "OrderedDict[str, list[ChatTurn]]" = OrderedDict()
        self._max_sessions = max_sessions
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                sid = row.get("session_id", "")
                turns = row.get("turns", [])
                self._sessions[sid] = [
                    ChatTurn(t["question"], t["answer"], t.get("rewritten"), t.get("sources_titles"))
                    for t in turns
                ]
        self._touch_order()  # 维持 LRU 顺序

    def _touch_order(self) -> None:
        for sid in list(self._sessions):
            self._sessions.move_to_end(sid)

    def _append_row(self, session_id: str) -> None:
        if self._path is None:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "session_id": session_id,
                "turns": [t.to_dict() for t in self._sessions[session_id]],
            }, ensure_ascii=False) + "\n")

    def get_or_create(self, session_id: str | None) -> str:
        with self._lock:
            sid = session_id or f"session-{len(self._sessions) + 1}"
            if sid not in self._sessions:
                self._sessions[sid] = []
                # 超限淘汰最旧会话（LRU）
                while len(self._sessions) > self._max_sessions:
                    self._sessions.popitem(last=False)
            self._sessions.move_to_end(sid)
            return sid

    def recent_turns(self, session_id: str, max_turns: int) -> list[ChatTurn]:
        with self._lock:
            turns = self._sessions.get(session_id, [])
            return turns[-max_turns:] if max_turns > 0 else turns

    def add_turn(self, session_id: str, turn: ChatTurn) -> None:
        with self._lock:
            self._sessions.setdefault(session_id, []).append(turn)
            self._append_row(session_id)

    def format_history(self, session_id: str, max_turns: int) -> str:
        """把最近几轮渲染成给 LLM 看的文本。"""
        lines: list[str] = []
        for t in self.recent_turns(session_id, max_turns):
            lines.append(f"用户：{t.question}")
            lines.append(f"助手：{t.answer[:300]}")
        return "\n".join(lines)
