"""知识库持久层（JSONL 双文件）。

docs.jsonl      —— 文档级元信息
kb.jsonl        —— 分块记录（原文 + 出处），数组下标与 FAISS 向量位置一一对应

知识点：
1. JSONL = 每行一个 JSON：追加写 O(1)、可用文本工具查看、可 diff，适合中小规模。
2. “向量库(FAISS) 存向量、JSONL 存原文” 的分工是向量检索系统的经典套路；
   向量库负责“相似度排序”，元数据层负责“溯源、增删、展示”。
3. 全量重写（delete 后 write back）用于演示；生产一般用数据库 + 向量库事务。
4. dataclass 当“行模型”，与 API 层的 Pydantic 各司其职：内层轻、外层严。
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class DocRecord:
    doc_id: str
    title: str
    filename: str
    char_count: int = 0
    chunk_count: int = 0
    uploaded_at: str = ""

    @classmethod
    def new(cls, doc_id: str, title: str, filename: str, char_count: int = 0) -> "DocRecord":
        return cls(
            doc_id=doc_id,
            title=title,
            filename=filename,
            char_count=char_count,
            uploaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    doc_title: str
    page: int | None
    text: str
    meta: dict = field(default_factory=dict)


class KnowledgeStore:
    """知识库：文档注册表 + 分块记录。线程安全（演示场景足够）。"""

    def __init__(self, kb_path: Path) -> None:
        self._kb_path = kb_path
        self._lock = threading.RLock()
        self.docs: dict[str, DocRecord] = {}
        self.chunks: list[ChunkRecord] = []   # 下标 == FAISS 向量位置
        self._load()

    # ---------- 加载 / 落盘 ----------
    def _load(self) -> None:
        if not self._kb_path.exists():
            return
        with open(self._kb_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("kind") == "doc":
                    row.pop("kind", None)
                    rec = DocRecord(**row)
                    self.docs[rec.doc_id] = rec
                elif row.get("kind") == "chunk":
                    row.pop("kind", None)
                    self.chunks.append(ChunkRecord(**row))

    def _append_line(self, row: dict) -> None:
        with open(self._kb_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _rewrite_all(self) -> None:
        rows: list[dict] = []
        for rec in self.docs.values():
            row = asdict(rec)
            row["kind"] = "doc"
            rows.append(row)
        for c in self.chunks:
            row = asdict(c)
            row["kind"] = "chunk"
            rows.append(row)
        with open(self._kb_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------- 写操作（引擎在 asyncio.Lock 内调用，这里再加 RLock 双保险）----------
    def add_doc_with_chunks(self, doc: DocRecord, chunks: list[ChunkRecord]) -> None:
        with self._lock:
            self.docs[doc.doc_id] = doc # 添加文档记录
            start = len(self.chunks)  # 记录起始位置，后续分块的向量位置会基于此偏量位置
            self.chunks.extend(chunks)  # 扩量添加分块
            doc.chunk_count = len(chunks)  # 更新分块数量
            doc_row = asdict(doc)  # 转换为字典
            doc_row["kind"] = "doc"
            self._append_line(doc_row)  # 追加文档记录
            for c in chunks:
                row = asdict(c)  # 转换为字典
                row["kind"] = "chunk"  # 添加记录类型标识
                self._append_line(row)  # 追加分块记录
            return start  # 起始向量位置（此处返回值其实不需要，记录对齐即可）

    def delete_doc(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self.docs:
                return False
            del self.docs[doc_id]
            self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
            self._rewrite_all()
            return True

    # ---------- 读操作 ----------
    def get_chunk(self, pos: int) -> ChunkRecord | None:
        if 0 <= pos < len(self.chunks):
            return self.chunks[pos]
        return None

    def doc_list(self) -> list[DocRecord]:
        return list(self.docs.values())

    def total_chunks(self) -> int:
        return len(self.chunks)
