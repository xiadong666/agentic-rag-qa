"""BM25 稀疏检索（自实现，教学友好）。

为什么“稀疏检索”还有存在价值（关键取舍）：
1. 稠密向量擅长“语义相似”，但会漏掉精确词匹配 —— 人名、产品名、型号、
   专有缩写（如 "FastAPI"、"RAG"、"CHUNK_SIZE"）这种字面命中最可靠。
2. BM25 是关键词检索的经典算法：它是 TF-IDF 的升级版，引入文档长度归一化
   和词频饱和，效果稳定、可解释、零成本。
3. 与稠密检索做“混合检索 + RRF 融合”可同时吃到两者优点（见 retrieval.py）。

公式（BM25 经典形式）：
    score(q, d) = Σ_idf(t) * (f(t,d)*(k1+1)) / (f(t,d) + k1*(1 - b + b*|d|/avgdl))
    idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
    k1≈1.5 词频饱和，b≈0.75 长度惩罚强度。

知识点：
1. 中文检索前必须先分词：中文没有天然空格，直接按字符匹配会支离破碎。
   用 jieba 分词（本文件 tokenize 处理中英混排）。
2. 分词结果可缓存 —— 一个词只切一次（真实项目常用倒排索引 + 内存缓存）。
"""
from __future__ import annotations

import math
import re
from collections import Counter

import jieba

# re.compile(r"[\u4e00-\u9fff]+|[a-z0-9_]+")是把正则表达式编译成一个正则表达式对象，方便后续使用
# 中英混排 tokenizer：中文段交给 jieba，英文/数字按词切
_WORD_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """将文本按词切分，并转换为小写。"""
    text = text.lower()
    tokens: list[str] = []
    for seg in _WORD_RE.findall(text):
        if "\u4e00" <= seg[0] <= "\u9fff":
            tokens.extend(t for t in jieba.lcut(seg) if t.strip())
        else:
            tokens.append(seg)
    return tokens


class BM25Index:
    """极简 BM25 索引：全内存、重建式（演示规模足够；生产换 Elasticsearch/OpenSearch）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._ids: list[str] = []  # 与 _tokenized 平行
        self._tokenized: list[list[str]] = []  # 文档分词结果
        self._doc_lens: list[int] = []  # 文档长度
        self._doc_freq: Counter[str] = Counter()  # 文档词频统计
        self._avgdl = 0.0  # 平均文档长度
        self._built = False  # 是否已构建统计量

    def add(self, chunk_id: str, text: str) -> None:
        """加入一个文档（可重复调用；build() 前 add 都行）。"""
        toks = tokenize(text)  # 分词
        self._ids.append(chunk_id)  # 记录文档ID
        self._tokenized.append(toks)  # 记录分词结果
        self._doc_lens.append(len(toks))  # 记录文档长度
        self._built = False  # 标记为未构建统计量，后续调用 rebuild_stats 会重新计算

    def rebuild_stats(self) -> None:
        """构建统计量（增删后调用一次即可）。"""
        if not self._tokenized:  # 空库
            self._avgdl = 0.0  # 空库平均文档长度为0
            self._doc_freq = Counter()  # 空库词频统计为0
            self._built = True
            return
        self._avgdl = sum(self._doc_lens) / len(self._doc_lens)  # 计算平均文档长度
        df: Counter[str] = Counter()  # 文档词频统计
        for toks in self._tokenized:
            for t in set(toks):  # 每篇文档一个词只计一次（df 定义）
                df[t] += 1  # 统计文档词频
        self._doc_freq = df  # 记录文档词频统计
        self._built = True  # 标记为已构建统计量，后续调用 search 会使用这些统计量

    def clear(self) -> None:
        self._ids.clear()
        self._tokenized.clear()
        self._doc_lens.clear()
        self._doc_freq.clear()
        self._avgdl = 0.0
        self._built = False

    @property
    def size(self) -> int:
        return len(self._ids)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """返回 [(chunk_id, score)] 按分数降序。空库/空查询返回 []。"""
        if not self._built:
            self.rebuild_stats()
        q_tokens = tokenize(query)
        if not q_tokens or self.size == 0:
            return []
        n = self.size
        # 统计查询词频
        q_tf = Counter(q_tokens)
        scores: dict[int, float] = {}
        for term, q_count in q_tf.items():
            df = self._doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            # 只扫出现过该词的文档（倒排思想；这里直接全扫 + 提前跳过）
            for i, toks in enumerate(self._tokenized):
                # 词频统计
                f = 0
                for t in toks:
                    if t == term:
                        f += 1
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self._doc_lens[i] / max(self._avgdl, 1e-9))
                scores[i] = scores.get(i, 0.0) + idf * (f * (self.k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [(self._ids[i], s) for i, s in ranked[:top_k]]
