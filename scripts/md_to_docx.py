"""Markdown → Word 渲染器（面向技术教程排版）。

为什么要有这一层：
    直接用 Python 拼 docx 写长文档，会被“中文引号嵌套”反复咬（字符串定界符冲突，
    语法错误还难定位）。把内容降级成 Markdown、排版交给渲染器，两个问题一起消失：
    写内容时不用担心引号，调排版时不用碰内容。

支持的语法（刻意只支持够用的子集）：
    # / ## / ###        标题
    - 或 *              项目符号
    1. 2. 3.            有序列表
    ```lang ... ```     代码块（灰底等宽）
    | a | b |           表格（第二行 --- 决定表头）
    > [tip] 文本        提示框（tip/warn/key/star 四种着色）
    **粗体** `代码`     行内样式
    ---                 分隔线
    普通行              正文
"""
from __future__ import annotations

import re

from scripts.docx_builder import (
    C_CODE,
    C_KEY,
    C_MUTED,
    C_PRIMARY,
    C_SECOND,
    C_TIP,
    C_WARN,
    Doc,
    parse_inline,
)

BOX_TAG_RE = re.compile(r"^>\s*\[(tip|warn|key|star|note)\]\s*(.*)$")
LIST_RE = re.compile(r"^\s*[-*]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def render_inline(d: Doc, text: str, *, indent: float = 0.0, size: float = 10.5) -> None:
    """把带行内 Markdown 的文本渲染成一段富文本。

    复用 docx_builder.parse_inline 的手写扫描器（支持"粗体里嵌代码"与相邻粗体），
    这样 Markdown 渲染路径与直接调用 Doc 的生成器共用同一套解析规则，避免两处行为不一致。
    """
    d.rich(parse_inline(text, size=size), indent=indent, after=3)


def render(d: Doc, markdown: str) -> None:
    """把整篇 Markdown 渲染进 Doc。"""
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # ---- 代码块 ----
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            d.code("\n".join(buf))
            continue

        # ---- 表格 ----
        if TABLE_ROW_RE.match(line) and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = [c.strip() for c in TABLE_ROW_RE.match(line).group(1).split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < n and TABLE_ROW_RE.match(lines[i]):
                rows.append([c.strip() for c in TABLE_ROW_RE.match(lines[i]).group(1).split("|")])
                i += 1
            widths = [max(len(str(r[c])) if c < len(r) else 0 for r in ([header] + rows))
                      for c in range(len(header))]
            d.table(header, rows, widths=widths, font_size=9.5 if len(header) < 5 else 9)
            continue

        # ---- 提示框 ----
        m = BOX_TAG_RE.match(line)
        if m:
            kind, first = m.group(1), m.group(2)
            buf = [first]
            i += 1
            while i < n and lines[i].strip().startswith(">") and not BOX_TAG_RE.match(lines[i]):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            d.box(kind, " ".join(x for x in buf if x))
            continue

        # ---- 标题 ----
        if stripped.startswith("### "):
            d.h3(re.sub(r"\*\*(.+?)\*\*", r"\1", stripped[4:]))
            i += 1
            continue
        if stripped.startswith("## "):
            d.h2(re.sub(r"\*\*(.+?)\*\*", r"\1", stripped[3:]))
            i += 1
            continue
        if stripped.startswith("# "):
            d.h1(re.sub(r"\*\*(.+?)\*\*", r"\1", stripped[2:]))
            i += 1
            continue

        # ---- 分隔线 ----
        if stripped in ("---", "***", "___"):
            d.para("─" * 46, size=8, color=C_MUTED, before=4, after=6)
            i += 1
            continue

        # ---- 列表 ----
        m = LIST_RE.match(line)
        if m:
            d.bullet(m.group(1))
            i += 1
            continue
        m = ORDERED_RE.match(line)
        if m:
            d.numbered(int(m.group(1)), m.group(2))
            i += 1
            continue

        # ---- 空行 ----
        if not stripped:
            i += 1
            continue

        # ---- 正文（连续行合并成一段）----
        buf = [stripped]
        i += 1
        while (i < n and lines[i].strip()
               and not lines[i].strip().startswith(("#", "```", "|", ">", "-", "*"))
               and not ORDERED_RE.match(lines[i])):
            buf.append(lines[i].strip())
            i += 1
        render_inline(d, " ".join(buf))
