"""Word 教程构建入口。

用法：
    rag-qa-system\\docs\\.venv-doc\\Scripts\\python rag-qa-system\\docs\\gen\\build.py
"""
from __future__ import annotations

import datetime
import os
import sys

GEN_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(GEN_DIR, "..", ".."))
# 导入路径必须在 import 之前就绪：① 同目录（各 part 模块与排版 style）；
# ② 项目 scripts/（改造后新增的 Agentic 章节模块放在这里，便于独立维护与两份文档共用）
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, GEN_DIR)

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402

import style as S  # noqa: E402
from content_p1 import add as add_p1  # noqa: E402
from content_p2a import add as add_p2a  # noqa: E402
from content_p2b import add as add_p2b  # noqa: E402
from content_p2c import add as add_p2c  # noqa: E402
from content_p2d import add as add_p2d  # noqa: E402
from content_p3 import add as add_p3  # noqa: E402
from content_p4 import add as add_p4  # noqa: E402
from content_p5 import add as add_p5  # noqa: E402
from content_p6 import add as add_p6  # noqa: E402
# 第八部分（Agentic RAG 验收章节）。原先这个模块放在 scripts/ 下，但它同时被
# "面试题库"生成器复用，而题库属于个人求职材料、已移出本仓库，所以正文内联回
# docs/gen/，让本目录成为自洽、可独立运行的文档生成目录（新克隆即可跑）。
from content_p7_agentic import add as add_p7  # noqa: E402

OUT = os.path.join(ROOT, "docs", "RAG知识库问答系统_学习巩固教程.docx")

DOC_NAME = "RAG 知识库问答系统 —— 学习巩固教程"
DOC_SUB = ("从零实现：文档上传 · 解析 · 分块 · 向量化 · 混合检索 · 重排序 · "
           "带引用来源的多轮问答 · 部署成 Web 服务 ·（附）升级为 Agentic RAG 与双层验收")


def cover(doc):
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    S._set_run_fonts(p.add_run(DOC_NAME), ascii_font="Calibri", ea_font="微软雅黑",
                     size=26, bold=True, color=S.C_BLUE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    S._set_run_fonts(p.add_run(DOC_SUB), ascii_font="Calibri", ea_font="宋体",
                     size=12, color=S.C_GRAY)
    doc.add_paragraph()
    meta = [
        ("适用对象", "大四学生 · 求职 AI 应用开发实习 · 已学完 LangChain 与 FastAPI"),
        ("配套代码", "rag-qa-system/（FastAPI + LangChain 1.2 + FAISS + sentence-transformers）"),
        ("核心亮点", "混合检索 · 重排序 · 引用来源 · 对话历史 · 流式输出 · Docker 部署"),
        ("文档定位", "分步实现详解 + 代码知识点总结 + 避坑清单 + 面试/简历素材 + 进阶路线"),
        ("生成日期", datetime.date.today().strftime("%Y-%m-%d")),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in meta:
        cells = t.add_row().cells
        S._set_run_fonts(cells[0].paragraphs[0].add_run(k),
                         ascii_font="Calibri", ea_font="微软雅黑", size=11, bold=True)
        cells[1].paragraphs[0].add_run(v)
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    S._set_run_fonts(p.add_run("建议与项目代码对照阅读 · 先跑通，再精读，最后用它准备面试"),
                     ascii_font="Calibri", ea_font="宋体", size=10, color=S.C_GRAY)


def main() -> None:
    doc = S.new_document()
    cover(doc)
    doc.add_page_break()

    S.add_toc(
        doc,
        "提示：目录为 Word 域。打开文档后按 Ctrl+A 全选，再按 F9（或右键 → 更新域）即可生成页码目录。",
    )

    for fn in (add_p1, add_p2a, add_p2b, add_p2c, add_p2d, add_p3, add_p4, add_p5, add_p6, add_p7):
        fn(doc)

    S.add_page_number_footer(doc, "RAG 知识库问答系统 · 学习巩固教程")

    out = OUT
    if "--out" in sys.argv:                     # 受限环境可先写到有权限的目录再拷回
        idx = sys.argv.index("--out")
        if idx + 1 < len(sys.argv):
            out = os.path.abspath(sys.argv[idx + 1])
    doc.save(out)
    # 统计
    heads = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    print(f"OK -> {out}")
    print(f"headings={len(heads)} paragraphs={len(doc.paragraphs)} "
          f"tables={len(doc.tables)} size={os.path.getsize(out)} bytes")
    h1 = [h for h in heads if True]
    print("last H1s:", " / ".join([h for h in heads if h.startswith(("第", "使用"))][-10:]))


if __name__ == "__main__":
    main()
