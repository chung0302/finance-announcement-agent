# -*- coding: utf-8 -*-
"""读取 docx 模板的段落、样式与字体信息（仅用标准库，避免额外依赖）。"""
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DOC = Path(r"C:\Users\openwind\Desktop\财经智能体\finance-announcement-agent\docs\_template.docx")


def run_info(r):
    rPr = r.find(f"{W}rPr")
    if rPr is None:
        return ""
    bits = []
    fonts = rPr.find(f"{W}rFonts")
    if fonts is not None:
        for attr in ("ascii", "eastAsia", "hAnsi"):
            v = fonts.get(f"{W}{attr}")
            if v:
                bits.append(f"{attr}={v}")
    sz = rPr.find(f"{W}sz")
    if sz is not None:
        bits.append(f"sz={int(sz.get(f'{W}val'))/2}pt")
    b = rPr.find(f"{W}b")
    if b is not None and b.get(f"{W}val") != "0":
        bits.append("bold")
    color = rPr.find(f"{W}color")
    if color is not None:
        bits.append(f"color={color.get(f'{W}val')}")
    return ",".join(bits)


def para_text(p):
    return "".join(t.text or "" for t in p.iter(f"{W}t"))


def main():
    with zipfile.ZipFile(DOC) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")

    lines = []
    idx = 0
    for el in body:
        if el.tag == f"{W}p":
            t = para_text(el)
            pPr = el.find(f"{W}pPr")
            style = ""
            ind = ""
            spacing = ""
            if pPr is not None:
                ps = pPr.find(f"{W}pStyle")
                if ps is not None:
                    style = ps.get(f"{W}val")
                sp = pPr.find(f"{W}spacing")
                if sp is not None:
                    spacing = " ".join(f"{k.split('}')[-1]}={v}" for k, v in sp.attrib.items())
                indEl = pPr.find(f"{W}ind")
                if indEl is not None:
                    ind = " ".join(f"{k.split('}')[-1]}={v}" for k, v in indEl.attrib.items())
            runinfo = ""
            for r in el.iter(f"{W}r"):
                ri = run_info(r)
                if ri:
                    runinfo = ri
                    break
            if t.strip() or style or runinfo:
                lines.append(f"[{idx}] style={style} | {spacing} | {ind} | {runinfo}\n     {t}")
            idx += 1
        elif el.tag == f"{W}tbl":
            lines.append("[表格]")
            for row in el.iter(f"{W}tr"):
                cells = ["".join(para_text(p) for p in c.iter(f"{W}p")) for c in row.findall(f"{W}tc")]
                lines.append("  | " + " | ".join(cells))
            lines.append("[/表格]")

    out = Path(r"C:\Users\openwind\Desktop\财经智能体\finance-announcement-agent\docs\_template_dump.txt")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"段落数={idx}，输出={out}")


if __name__ == "__main__":
    main()
