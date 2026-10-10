"""Word 文档生成工具：把"内容块"渲染成排版良好的 docx。

为什么单独抽一个 builder（而不是堆 docx 样板代码）：
    技术教程的排版要处理中英混排字体（eastAsia）、标题层级、代码块底色、
    表格边框、页眉页脚……这些和"写什么内容"是两件事。
    把排版抽成 builder 后，内容层只描述"我要一个 H2 / 一段代码 / 一张表"，
    既好维护，也方便复用去生成简历或验收报告。

能力：
    - 中英混排字体（正文 Calibri + 东亚 微软雅黑；代码 Consolas）
    - H1/H2/H3 标题（带下边框/色块）、正文、项目符号、编号列表
    - 代码块（灰底 + 等宽字体 + 不换行缩放保护）
    - 表格（表头底色、斑马纹、自适应列宽）
    - 提示框（💡知识点 / ⚠️注意 / 🎯面试点 三类彩色段落）
    - 页眉页脚、页码域
"""
from __future__ import annotations

import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

EA = "微软雅黑"
LATIN = "Calibri"
MONO = "Consolas"

# 行内 Markdown：**粗体** 与 `代码`（够用即可，不做完整 Markdown 解析）。
# 粗体右边界用 (?<!\*)\*\*(?!\*)，以支持"粗体里嵌代码"（**改 `参数` 就行**）这种常见写法。
INLINE_MD_RE = re.compile(r"(\*\*.+?(?<!\*)\*\*(?!\*)|`[^`\n]+`)")


def parse_inline(text: str, *, size: float = 10.5,
                 base: dict | None = None) -> list[tuple[str, dict]]:
    """把行内 Markdown 解析成 (文本, 样式) 段列表 —— 手写扫描器，不用正则。

    为什么手写：教程类文本里经常出现「粗体里嵌代码」（如 **改 `参数` 就行**）
    以及「相邻的粗体」（如 `**看什么：**启动直接失败`）。用正则做嵌套匹配要么漏、要么吞，
    单遍扫描反而最简单也最稳：
        - `code`   → 等宽 + 代码色
        - **text** → 粗体（其内部的 `code` 仍然按代码样式渲染，实现"粗体里嵌代码"）
        - \\` \\*  → 转义，输出字面量
    """
    base = dict(base or {})
    base.setdefault("size", size)
    code_style = dict(base)
    code_style.update({"latin": MONO, "color": C_CODE, "size": max(8.5, size - 0.5)})
    bold_style = dict(base)
    bold_style["bold"] = True

    out: list[tuple[str, dict]] = []
    buf: list[str] = []
    i, n = 0, len(text or "")
    bold = False
    code = False

    def flush() -> None:
        if buf:
            style = code_style if code else (bold_style if bold else dict(base))
            out.append(("".join(buf), style))
            buf.clear()

    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "`*":
            buf.append(text[i + 1])
            i += 2
            continue
        if not code and text.startswith("**", i):
            flush()
            bold = not bold
            i += 2
            continue
        if ch == "`":
            flush()
            code = not code
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return out or [("", dict(base))]

# 主题色
C_PRIMARY = RGBColor(0x1E, 0x4B, 0x8F)     # 深蓝：一级标题
C_SECOND = RGBColor(0x2C, 0x3E, 0x50)      # 深灰蓝：二级标题
C_BODY = RGBColor(0x22, 0x22, 0x33)
C_MUTED = RGBColor(0x77, 0x7F, 0x8C)
C_CODE = RGBColor(0x0B, 0x3D, 0x2E)
C_WARN = RGBColor(0xA3, 0x33, 0x33)
C_TIP = RGBColor(0x1E, 0x6B, 0x3A)
C_KEY = RGBColor(0x8A, 0x4B, 0x08)

BOX_STYLES = {
    "tip": ("💡 知识点  ", C_TIP, "F2FBF5"),
    "warn": ("⚠️ 注意  ", C_WARN, "FDF3F2"),
    "key": ("🎯 面试点  ", C_KEY, "FFF9EC"),
    "star": ("✨ 亮点  ", C_PRIMARY, "F2F7FF"),
    # note 与 tip 同色系，但标签是「说明」——用于"使用规则/前置条件"这类中性提示
    "note": ("📌 说明  ", C_MUTED, "F4F6F9"),
}


def set_run_font(run, *, size=10.5, bold=False, italic=False,
                 latin=LATIN, ea=EA, color: RGBColor | None = None) -> None:
    run.font.name = latin
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), latin)
    rFonts.set(qn("w:hAnsi"), latin)
    rFonts.set(qn("w:eastAsia"), ea)


def shade(element, hex_fill: str) -> None:
    """给段落或单元格加底色。"""
    pr = element.get_or_add_pPr() if hasattr(element, "get_or_add_pPr") else element
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr.append(shd)


def shade_cell(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def add_border(paragraph, *, bottom: bool = False, left: bool = False,
               color: str = "D6DEE8", sz: str = "6") -> None:
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    for name, on in (("bottom", bottom), ("left", left)):
        if not on:
            continue
        el = OxmlElement(f"w:{name}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), sz)
        el.set(qn("w:space"), "3")
        el.set(qn("w:color"), color)
        borders.append(el)
    pPr.append(borders)


class Doc:
    """教程文档构建器。"""

    def __init__(self, *, title: str = "", subtitle: str = "",
                 page: str = "A4", margin_cm: float = 2.0) -> None:
        self.doc = Document()
        sec = self.doc.sections[0]
        if page == "A4":
            sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.top_margin = sec.bottom_margin = Cm(margin_cm)
        sec.left_margin = sec.right_margin = Cm(margin_cm * 0.9)
        self._usable_w = (sec.page_width.cm - sec.left_margin.cm - sec.right_margin.cm)

        normal = self.doc.styles["Normal"]
        normal.font.name = LATIN
        normal.font.size = Pt(10.5)
        normal.font.color.rgb = C_BODY
        rPr = normal.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        rFonts.set(qn("w:eastAsia"), EA)

        if title:
            self.cover_title(title, subtitle)

    # ------------------------------------------------------------ 基础排版
    def para(self, text: str = "", *, size=10.5, bold=False, italic=False,
             color: RGBColor | None = None, indent=0.0, before=0, after=3,
             line=1.35, align=None, latin=LATIN, md: bool = True) -> object:
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = line
        if indent:
            pf.left_indent = Cm(indent)
        if align is not None:
            p.alignment = align
        if text:
            if md:
                # md=True：解析 **粗体** 与 `代码`，其余沿用本段的基础样式
                base = {"size": size, "bold": bold, "italic": italic,
                        "color": color or C_BODY, "latin": latin}
                for seg, style in parse_inline(text, size=size, base=base):
                    set_run_font(p.add_run(seg), size=style.get("size", size),
                                 bold=style.get("bold", bold),
                                 italic=style.get("italic", italic),
                                 color=style.get("color", C_BODY),
                                 latin=style.get("latin", latin))
            else:
                set_run_font(p.add_run(text), size=size, bold=bold, italic=italic,
                             color=color or C_BODY, latin=latin)
        return p

    def rich(self, segments: list[tuple[str, dict]], *, indent=0.0, before=0, after=3,
             line=1.35) -> object:
        """一段里混排多种样式：segments = [(文本, {bold/color/size/latin}), ...]"""
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = line
        if indent:
            pf.left_indent = Cm(indent)
        for text, style in segments:
            set_run_font(p.add_run(text), size=style.get("size", 10.5),
                         bold=style.get("bold", False), italic=style.get("italic", False),
                         color=style.get("color", C_BODY), latin=style.get("latin", LATIN))
        return p

    def cover_title(self, title: str, subtitle: str = "") -> None:
        p = self.para(title, size=20, bold=True, color=C_PRIMARY, before=6, after=4,
                      align=WD_ALIGN_PARAGRAPH.CENTER)
        add_border(p, bottom=True, color="1E4B8F", sz="12")
        if subtitle:
            self.para(subtitle, size=11, color=C_MUTED, after=14,
                      align=WD_ALIGN_PARAGRAPH.CENTER)

    def h1(self, text: str, *, number: str = "") -> None:
        label = f"{number}　{text}" if number else text
        p = self.para(label, size=15, bold=True, color=C_PRIMARY, before=16, after=6)
        add_border(p, bottom=True, color="1E4B8F", sz="10")

    def h2(self, text: str) -> None:
        p = self.para(text, size=12.5, bold=True, color=C_SECOND, before=11, after=4)
        add_border(p, left=True, color="3B82F6", sz="18")

    def h3(self, text: str) -> None:
        self.para(text, size=11, bold=True, color=C_SECOND, before=7, after=3)

    def bullet(self, text: str, *, indent=0.5, size=10.5) -> None:
        self.para("• " + text, size=size, indent=indent, after=2, line=1.3, md=True)

    def numbered(self, idx: int, text: str, *, indent=0.5, size=10.5) -> None:
        self.para(f"{idx}. {text}", size=size, indent=indent, after=2, line=1.3, md=True)

    def code(self, text: str, *, caption: str = "") -> None:
        if caption:
            self.para(caption, size=9.5, color=C_MUTED, italic=True, after=2, before=4)
        for line in text.strip("\n").split("\n"):
            p = self.doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before, pf.space_after = Pt(0), Pt(0)
            pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pf.line_spacing = 1.12
            pf.left_indent = Cm(0.3)
            set_run_font(p.add_run(line if line else " "), size=9.0, latin=MONO, color=C_CODE)
            shade(p._p, "F5F7FA")
        self.para("", after=3, size=4)

    def box(self, kind: str, text: str) -> None:
        """彩色提示框。text 支持行内 Markdown（**粗体** 与 `代码`）。"""
        label, color, fill = BOX_STYLES[kind]
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(4), Pt(5)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.3
        pf.left_indent = Cm(0.2)
        set_run_font(p.add_run(label), size=10.5, bold=True, color=color)
        for seg, style in parse_inline(text, size=10.5, base={"color": C_BODY}):
            set_run_font(p.add_run(seg), size=style.get("size", 10.5),
                         bold=style.get("bold", False), color=style.get("color", C_BODY),
                         latin=style.get("latin", LATIN))
        shade(p._p, fill)

    def table(self, headers: list[str], rows: list[list[str]], *,
              widths: list[float] | None = None, caption: str = "",
              font_size: float = 9.5) -> None:
        if caption:
            self.para(caption, size=9.5, color=C_MUTED, italic=True, after=3, before=4)
        t = self.doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        if widths:
            total = sum(widths)
            for i, w in enumerate(widths):
                for row in t.rows:
                    row.cells[i].width = Cm(self._usable_w * w / total)
        hdr = t.rows[0].cells
        for i, h in enumerate(headers):
            hdr[i].text = ""
            p = hdr[i].paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            set_run_font(p.add_run(h), size=font_size, bold=True,
                         color=RGBColor(0xFF, 0xFF, 0xFF))
            shade_cell(hdr[i], "2C5FA8")
        for ri, row in enumerate(rows):
            cells = t.add_row().cells
            for ci, val in enumerate(row):
                cells[ci].text = ""
                p = cells[ci].paragraphs[0]
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing = 1.15
                # 单元格内容同样支持行内 Markdown（表格里 `参数名` 很常见）
                for seg, style in parse_inline(str(val), size=font_size,
                                               base={"color": C_BODY}):
                    set_run_font(p.add_run(seg), size=style.get("size", font_size),
                                 bold=style.get("bold", False),
                                 color=style.get("color", C_BODY),
                                 latin=style.get("latin", LATIN))
                if ri % 2 == 1:
                    shade_cell(cells[ci], "F4F7FB")
        self.para("", after=5, size=5)

    def page_break(self) -> None:
        self.doc.add_page_break()

    def footer_page_number(self, text: str = "Agentic RAG 改造全流程 · 学习巩固教程") -> None:
        sec = self.doc.sections[0]
        p = sec.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run_font(p.add_run(text + "　—　第 "), size=8, color=C_MUTED)
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), "PAGE")
        run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "16")
        rPr.append(sz)
        run.append(rPr)
        fld.append(run)
        p._p.append(fld)
        set_run_font(p.add_run(" 页"), size=8, color=C_MUTED)

    def save(self, path: str) -> None:
        self.doc.save(path)
