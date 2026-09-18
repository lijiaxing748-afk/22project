#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 Markdown 转成 Word（.docx），中文字体与图片都处理到位。

为什么不用 pandoc：
  1. 本机没装 pandoc，装它要下载几十 MB 二进制；
  2. 这份文档结构规整（标题/表格/代码块/引用/图片/列表），手写解析反而能把
     **中文字体**和**图片宽度**控制到位 —— pandoc 的默认样式在中文 Word 里
     常常字体不对、表格挤成一团。

用法：
    python md2docx.py <输入.md> <输出.docx>

约定：
  - 图片按 15.6 cm 宽等比缩放（A4 去掉页边距后的可用宽度）
  - 页脚自动加"第 X 页 / 共 Y 页"
  - 中文正文用宋体、标题用微软雅黑、代码用 Consolas
"""
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

CN_FONT = "微软雅黑"
CN_FONT_BODY = "宋体"
MONO_FONT = "Consolas"
CODE_BG = "F5F5F5"
TABLE_HEAD_BG = "E8EEF7"
LINK_COLOR = RGBColor(0x0B, 0x57, 0xD0)
BACKTICK = chr(96)

# 行内语法：**粗体** / `代码` / [文字](链接)
INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|" + BACKTICK + r"[^" + BACKTICK + r"]+" + BACKTICK + r"|\[[^\]]+\]\([^)]+\))"
)


def set_run_font(run, cn=CN_FONT_BODY, en=CN_FONT_BODY, size=None, bold=None, color=None):
    """python-docx 设中文字体要同时写 rFonts 的 eastAsia，只设 font.name 对中文无效。"""
    run.font.name = en
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), cn)
    rfonts.set(qn("w:ascii"), en)
    rfonts.set(qn("w:hAnsi"), en)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade_cell(cell, fill):
    pr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def shade_paragraph(par, fill):
    pr = par._element.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def para_border(par, color="DDDDDD", size=6):
    pr = par._element.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(size))
        el.set(qn("w:space"), "4")
        el.set(qn("w:color"), color)
        borders.append(el)
    pr.append(borders)


def add_inline(par, text, size=10.5, base_bold=False, color=None):
    """把 **粗体** / `代码` / [文字](链接) 混排进一个段落。"""
    for piece in INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            # 粗体里常套着反引号（如 **`/predict` 接口**），反引号是 Markdown 语法，
            # 不能让它在 Word 里原样显示
            r = par.add_run(piece[2:-2].replace(BACKTICK, ""))
            set_run_font(r, cn=CN_FONT, en=CN_FONT, size=size, bold=True, color=color)
        elif piece.startswith(BACKTICK) and piece.endswith(BACKTICK) and len(piece) > 2:
            r = par.add_run(piece[1:-1])
            set_run_font(r, cn=MONO_FONT, en=MONO_FONT, size=size - 0.5,
                         color=RGBColor(0xC7, 0x25, 0x4E))
        elif piece.startswith("[") and "](" in piece:
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", piece)
            label, url = m.group(1), m.group(2)
            r = par.add_run(label)
            set_run_font(r, size=size, color=LINK_COLOR)
            if not url.startswith("images/"):
                r2 = par.add_run(f"（{url}）")
                set_run_font(r2, size=size - 1, color=LINK_COLOR)
        else:
            # 兜底：孤立的反引号也清掉，否则正文里会留一堆 ` 符号
            r = par.add_run(piece.replace(BACKTICK, ""))
            set_run_font(r, size=size, bold=base_bold, color=color)


def add_page_number_footer(doc):
    """页脚居中插入"第 X 页 / 共 Y 页"。"""
    footer = doc.sections[0].footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def field(instr):
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), instr)
        run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        rf = OxmlElement("w:rFonts")
        rf.set(qn("w:eastAsia"), CN_FONT)
        rf.set(qn("w:ascii"), CN_FONT)
        rpr.append(rf)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "18")
        rpr.append(sz)
        run.append(rpr)
        t = OxmlElement("w:t")
        t.text = "1"
        run.append(t)
        fld.append(run)
        return fld

    grey = RGBColor(0x80, 0x80, 0x80)
    r = p.add_run("第 ")
    set_run_font(r, cn=CN_FONT, en=CN_FONT, size=9, color=grey)
    p._element.append(field("PAGE"))
    r = p.add_run(" 页 / 共 ")
    set_run_font(r, cn=CN_FONT, en=CN_FONT, size=9, color=grey)
    p._element.append(field("NUMPAGES"))
    r = p.add_run(" 页")
    set_run_font(r, cn=CN_FONT, en=CN_FONT, size=9, color=grey)


def convert(md_path, docx_path):
    base_dir = os.path.dirname(os.path.abspath(md_path))
    lines = open(md_path, encoding="utf-8").read().split("\n")

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.4)
    sec.top_margin = sec.bottom_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = CN_FONT_BODY
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT_BODY)

    i, n = 0, len(lines)
    in_code, code_buf, first_h1_done = False, [], False

    def flush_code():
        if not code_buf:
            return
        code = "\n".join(code_buf)
        # 代码块装进单格表格：灰底 + 等宽字体，跨页也不会断得难看
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = tbl.rows[0].cells[0]
        shade_cell(cell, CODE_BG)
        cell.text = ""
        for idx, cl in enumerate(code.split("\n")):
            p = cell.paragraphs[0] if idx == 0 else cell.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(cl if cl else " ")
            set_run_font(r, cn=MONO_FONT, en=MONO_FONT, size=8.5,
                         color=RGBColor(0x24, 0x29, 0x2E))
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
        code_buf.clear()

    while i < n:
        line = lines[i]
        s = line.strip()

        # 代码块围栏
        if s.startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if not s:
            i += 1
            continue

        # 表格
        if s.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            strip_anchor = lambda c: re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", c.strip()).strip()
            header = [strip_anchor(c) for c in s.strip("|").split("|")]
            rows, j = [], i + 2
            while j < n and lines[j].strip().startswith("|"):
                rows.append([strip_anchor(c) for c in lines[j].strip().strip("|").split("|")])
                j += 1
            tbl = doc.add_table(rows=1, cols=len(header))
            tbl.style = "Table Grid"
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for k, h in enumerate(header):
                cell = tbl.rows[0].cells[k]
                cell.text = ""
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                add_inline(p, h, size=9, base_bold=True)
                for r in p.runs:
                    r.font.bold = True
                shade_cell(cell, TABLE_HEAD_BG)
            for row in rows:
                cells = tbl.add_row().cells
                for k in range(len(header)):
                    cells[k].text = ""
                    p = cells[k].paragraphs[0]
                    p.paragraph_format.space_before = Pt(1.5)
                    p.paragraph_format.space_after = Pt(1.5)
                    add_inline(p, row[k] if k < len(row) else "", size=8.5)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
            i = j
            continue

        # 分隔线
        if re.match(r"^-{3,}$", s):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            para_border(p, "BBBBBB", 4)
            i += 1
            continue

        # 图片
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
        if m:
            alt, src = m.group(1), m.group(2)
            img_path = os.path.join(base_dir, src)
            if os.path.exists(img_path):
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(2)
                p.add_run().add_picture(img_path, width=Cm(15.6))
                if alt:
                    c = doc.add_paragraph()
                    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    c.paragraph_format.space_after = Pt(8)
                    r = c.add_run(f"图：{alt}")
                    set_run_font(r, cn=CN_FONT, en=CN_FONT, size=9,
                                 color=RGBColor(0x66, 0x66, 0x66))
            else:
                add_inline(doc.add_paragraph(), f"[缺失图片：{src}]", size=10)
            i += 1
            continue

        # 标题（也要走行内解析，否则 `code` 的反引号会原样显示）
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lv, text = len(m.group(1)), m.group(2)
            if lv == 1 and not first_h1_done:
                first_h1_done = True
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(6)
                add_inline(p, text, size=20, base_bold=True)
                for r in p.runs:
                    r.font.bold = True
                    r.font.size = Pt(20)
            else:
                sizes = {1: 18, 2: 15, 3: 13, 4: 11.5, 5: 11, 6: 10.5}
                sz = sizes.get(lv, 11)
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(10 if lv <= 2 else 7)
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.keep_with_next = True
                add_inline(p, text, size=sz, base_bold=True)
                for r in p.runs:
                    r.font.bold = True
                    r.font.size = Pt(sz)
                    if lv <= 2:
                        r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
            i += 1
            continue

        # 引用块
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            shade_paragraph(p, "FFF8E1")
            add_inline(p, " ".join(x for x in buf if x), size=9.5)
            continue

        # 无序列表
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            item = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", m.group(2)).strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.75 + indent * 0.6)
            p.paragraph_format.first_line_indent = Cm(-0.45)
            p.paragraph_format.space_before = Pt(1.5)
            p.paragraph_format.space_after = Pt(1.5)
            r = p.add_run("• ")
            set_run_font(r, size=10.5)
            add_inline(p, item, size=10.5)
            i += 1
            continue

        # 有序列表：手工写编号。
        # 不能用 Word 的 "List Number" 样式 —— 它所有段落共用一个计数器，
        # 会导致"4.2.3 推理 操作步骤"从 11 接着数而不是从 1 重开（踩过这个坑）。
        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if m:
            indent = len(m.group(1)) // 2
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.95 + indent * 0.6)
            p.paragraph_format.first_line_indent = Cm(-0.55)
            p.paragraph_format.space_before = Pt(1.5)
            p.paragraph_format.space_after = Pt(1.5)
            r = p.add_run(f"{m.group(2)}. ")
            set_run_font(r, size=10.5, bold=True)
            add_inline(p, m.group(3), size=10.5)
            i += 1
            continue

        # 普通段落
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.35
        add_inline(p, s, size=10.5)
        i += 1

    flush_code()
    add_page_number_footer(doc)
    doc.save(docx_path)
    print(f"OK -> {docx_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python md2docx.py <输入.md> <输出.docx>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
