# -*- coding: utf-8 -*-
"""
把 docs/report_draft.md 生成为符合模板要求的 .docx。

模板要求（读自《26-27-01…个人实验报告模板.doc》）：
- A4；上下边距 2.5cm，左 3.0cm，右 2.5cm
- 各级标题：宋体小四（12pt）加粗；正文：宋体五号（10.5pt）
- 行距：固定值 18 磅；页码：页脚居中
- 正文 5~6 页，文件名"学号+姓名"

用法：python tools/build_docx.py
输出：docs/实验报告_【学号+姓名】.docx
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "docs" / "report_draft.md"
OUT = ROOT / "docs" / "实验报告_【学号+姓名】.docx"
SHOTS = ROOT / "docs" / "screenshots"

SONG = "宋体"
FANGSONG = "仿宋"
BODY_PT = 10.5      # 五号
TITLE_PT = 12.0     # 小四
LINE_PT = 18.0      # 固定行距
# 插图宽度：正文宽 15.5cm，图太宽会把整段挤到下一页造成大片留白
FIG_WIDTH_CM = float(os.getenv("FIG_WIDTH_CM", "9.8"))


# ------------------------------------------------------------------ 基础样式
def set_run_font(run, size=BODY_PT, bold=False, name=SONG):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)


def exact_spacing(p, pt=LINE_PT):
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(pt)


def add_inline(p, text, size=BODY_PT):
    """处理 **加粗** 与 `代码`。"""
    for tok in re.split(r"(\*\*.+?\*\*|`.+?`)", text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            set_run_font(r, size, True)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            r = p.add_run(tok[1:-1])
            set_run_font(r, size - 0.5, False, "Consolas")
        else:
            r = p.add_run(tok)
            set_run_font(r, size)


def body_para(doc, text, indent=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    p = doc.add_paragraph()
    p.alignment = align
    exact_spacing(p)
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.first_line_indent = Pt(BODY_PT * 2) if indent else Pt(0)
    add_inline(p, text, BODY_PT)
    return p


def heading(doc, text, level=1):
    p = doc.add_paragraph()
    exact_spacing(p)
    pf = p.paragraph_format
    pf.space_before = Pt(12 if level == 1 else 8)
    pf.space_after = Pt(6 if level == 1 else 3)
    pf.first_line_indent = Pt(TITLE_PT * 2)
    pf.keep_with_next = True
    r = p.add_run(text)
    set_run_font(r, TITLE_PT, True)
    return p


def add_page_number(section):
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    set_run_font(run, 9)
    for tag, attr, txt in (("w:fldChar", "w:fldCharType", "begin"),
                           ("w:instrText", "xml:space", "preserve"),
                           ("w:fldChar", "w:fldCharType", "end")):
        el = OxmlElement(tag)
        el.set(qn(attr), txt)
        if tag == "w:instrText":
            el.text = "PAGE"
        run._r.append(el)


def page_setup(section):
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(3.0)
    section.right_margin = Cm(2.5)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.75)


# ------------------------------------------------------------------ 封面与评分表
def build_cover(doc):
    for _ in range(2):
        p = doc.add_paragraph()
        exact_spacing(p, 18)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    exact_spacing(p, 56)
    r = p.add_run("实验报告")
    set_run_font(r, 45, True)

    for _ in range(3):
        p = doc.add_paragraph()
        exact_spacing(p, 18)

    fields = [
        ("课程名称", "财经智能体开发与应用"),
        ("专    业", "【请填写】"),
        ("任课教师", "宁  静"),
        ("学    号", "【请填写】"),
        ("姓    名", "【请填写】"),
        ("实验日期", "2026-2027学年 第1学期"),
    ]
    for k, v in fields:
        p = doc.add_paragraph()
        exact_spacing(p, 30)
        p.paragraph_format.left_indent = Cm(4.2)
        r = p.add_run(f"{k}：{v}")
        set_run_font(r, 14, True, FANGSONG)

    for _ in range(3):
        p = doc.add_paragraph()
        exact_spacing(p, 18)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    exact_spacing(p, 20)
    r = p.add_run("广东财经大学教务处制")
    set_run_font(r, 12, False, SONG)

    # 分页：评分表单独一页
    doc.add_page_break()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    exact_spacing(p, 24)
    r = p.add_run("评 分 表")
    set_run_font(r, 14, True)

    p = doc.add_paragraph()
    exact_spacing(p, 12)

    table = doc.add_table(rows=4, cols=7)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    data = [
        ["项目", "一 15分", "二 40分", "三 30分", "四 10分", "格式规范 5分", "总  分"],
        ["得  分", "", "", "", "", "", ""],
        ["评阅人", "", "", "", "", "", ""],
        ["复核人", "", "", "", "", "", ""],
    ]
    for i, row in enumerate(data):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(val)
            set_run_font(r, 10.5, i == 0)


# ------------------------------------------------------------------ 正文
def build_body(doc, md_text):
    lines = md_text.splitlines()
    i = 0
    first_title_done = False
    fig_count = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # 跳过开头的排版说明引用块
        if line.startswith(">") or line == "":
            i += 1
            continue
        if line == "---":
            i += 1
            continue

        # 一级标题（## 一、…）
        if line.startswith("## "):
            heading(doc, line[3:].strip(), level=1)
            i += 1
            continue

        # 二级标题（### 3.1 …）
        if line.startswith("### "):
            heading(doc, line[4:].strip(), level=2)
            i += 1
            continue

        # 文档主标题
        if line.startswith("# ") and not first_title_done:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            exact_spacing(p, 24)
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(line[2:].strip())
            set_run_font(r, 15, True)
            first_title_done = True
            i += 1
            continue

        # 副标题与信息行
        if line.startswith("**副标题"):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            exact_spacing(p)
            r = p.add_run(line.strip("*"))
            set_run_font(r, TITLE_PT, False)
            i += 1
            continue
        if line.startswith("课程：") or line.startswith("课程名称："):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            exact_spacing(p)
            r = p.add_run(line)
            set_run_font(r, BODY_PT)
            i += 1
            continue

        # 图片
        m = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if m:
            img = SHOTS / Path(m.group(2)).name
            if img.exists():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pf = p.paragraph_format
                pf.space_before = Pt(6)
                pf.space_after = Pt(2)
                p.add_run().add_picture(str(img), width=Cm(FIG_WIDTH_CM))
                fig_count += 1
            else:
                print(f"  [缺图] {img}")
            i += 1
            continue

        # 图注：*图 X　…*
        if line.startswith("*图") and line.endswith("*"):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            exact_spacing(p, 15)
            p.paragraph_format.space_after = Pt(8)
            r = p.add_run(line.strip("*"))
            set_run_font(r, 9)
            i += 1
            continue

        # 普通正文
        body_para(doc, line)
        i += 1

    return fig_count


def main() -> None:
    md_text = MD.read_text(encoding="utf-8")
    doc = Document()

    # 默认样式也设为宋体五号，避免遗留 Calibri
    style = doc.styles["Normal"]
    style.font.name = SONG
    style.font.size = Pt(BODY_PT)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), SONG)

    sec1 = doc.sections[0]
    page_setup(sec1)

    build_cover(doc)

    # 正文：新节，页码从 1 开始，页脚居中
    sec2 = doc.add_section(WD_SECTION.NEW_PAGE)
    page_setup(sec2)
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:start"), "1")
    sec2._sectPr.append(pg)
    add_page_number(sec2)

    fig_count = build_body(doc, md_text)
    doc.save(OUT)

    han = len(re.findall(r"[\u4e00-\u9fff]", md_text))
    print(f"已生成：{OUT}")
    print(f"汉字数={han}，插图={fig_count} 张")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        raise
