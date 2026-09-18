# -*- coding: utf-8 -*-
"""把 docx 的段落/表格文字打出来，用于校对（比 Word 导出 PDF 再抽取可靠）。"""
import sys

from docx import Document


def iter_block_text(doc):
    """按文档顺序输出段落与表格。"""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield "P", Paragraph(child, doc).text
        elif child.tag == qn("w:tbl"):
            tbl = Table(child, doc)
            for row in tbl.rows:
                yield "T", " | ".join(c.text.replace("\n", " ") for c in row.cells)


path = sys.argv[1]
pattern = sys.argv[2] if len(sys.argv) > 2 else None
ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 40

blocks = list(iter_block_text(Document(path)))

if pattern:
    hits = [i for i, (_, t) in enumerate(blocks) if pattern in t]
    if not hits:
        print(f"未找到包含 {pattern!r} 的段落")
        sys.exit(1)
    start = hits[-1] if len(hits) > 1 else hits[0]
    for kind, text in blocks[start:start + ctx]:
        if text.strip():
            print(f"[{kind}] {text}")
else:
    for kind, text in blocks:
        if text.strip():
            print(f"[{kind}] {text}")
