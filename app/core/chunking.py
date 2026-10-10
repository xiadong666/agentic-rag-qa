"""文本分块。

为什么必须分块？
1. 上下文窗口有限；2. 检索的“粒度”决定命中质量——整篇文档没法按相关性切片；
   一段几百字的小节最容易命中语义。3. 分块是 RAG 里影响效果的第一大超参数。

知识点：
1. RecursiveCharacterTextSplitter：按分隔符优先级递归切分（先大块后小块），
   尽量保住语义完整的句子/段落——比固定长度硬切更聪明。
2. 分隔符列表针对中文调整：中文没有空格分词，必须加入 。！？；等标点，
   否则 500 字一块会把句子拦腰砍断。
3. chunk_overlap 重叠：让切在边界的上下文在下个块里也能被检索到，
   但 overlap 过大 = 冗余重复、涨 token 成本，需要权衡。
4. 我们按“页”切片：先按页拆、再对每页分块，从而让每个 chunk 都能准确
   记录它来自第几页 → “引用来源”可以精确到页码。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 中文友好的分隔符优先级：段落 > 换行 > 句末标点 > 分号/逗号 > 兜底
ZH_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

# @dataclass 定义一个数据类，用于存储每个知识块的元数据
@dataclass
class Chunk:
    """一个入库的知识块。id 全局唯一（doc_id:页码:块内序号）。"""

    chunk_id: str
    doc_id: str
    doc_title: str
    page: int | None
    text: str
    meta: dict = field(default_factory=dict)   # 预留扩展位（章节标题、更新时间等）default_factory=dict 用于初始化一个空字典


def split_pages_into_chunks(
    pages: list[tuple[int | None, str]],
    *,
    doc_id: str,
    doc_title: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    """把 (页码, 文本) 列表切成 Chunk 列表。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,      # chunk_size=chunk_size 表示每个块的最大长度
        chunk_overlap=chunk_overlap,  # chunk_overlap=chunk_overlap 表示块之间的重叠部分
        separators=ZH_SEPARATORS,   # separators=ZH_SEPARATORS 表示使用中文友好的分隔符优先级
        length_function=len,        # 按字符数计长（中文场景：len 即可，不必按 token）length_function=len 表示按字符数计长
        keep_separator=True,        # 保留句末标点，块尾更自然keep_separator=True 保留句末标点，块尾更自然
    )
    chunks: list[Chunk] = [] # chunks: list[Chunk] = [] 定义一个空列表用于存储切分后的块，Chunk 是数据类，用于存储每个块的元数据
    for page_no, text in pages: # 遍历每个页面，每个页面包含页码和文本内容
        for i, piece in enumerate(splitter.split_text(text)): # 遍历每个块，每个块包含文本内容
            piece = piece.strip() # 移除块首尾的空白字符
            if not piece: # 如果块为空，则跳过当前循环
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}:p{page_no if page_no is not None else 0}:{i}",
                    doc_id=doc_id,
                    doc_title=doc_title,
                    page=page_no,
                    text=piece,
                )
            )
    return chunks
