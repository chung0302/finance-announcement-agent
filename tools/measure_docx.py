# -*- coding: utf-8 -*-
"""
用 Word COM 统计 .docx 的页数，并把正文每页的首段打印出来，便于定位排版留白。

用法：python tools/measure_docx.py [docx路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "docs" / "实验报告_【学号+姓名】.docx"


def measure(path: Path) -> None:
    import win32com.client as win32  # type: ignore

    lines: list[str] = []

    def say(s: str = "") -> None:
        lines.append(s)
        try:
            print(s)
        except Exception:  # noqa: BLE001
            pass

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(path))
        doc.Repaginate()
        total = doc.ComputeStatistics(2)  # wdStatisticPages
        say(f"文件：{path.name}")
        say(f"总页数：{total}")

        # 逐页首段，辅助判断留白位置
        for pg in range(1, total + 1):
            try:
                rng = doc.GoTo(1, 1, pg)  # wdGoToPage, wdGoToAbsolute
                para = rng.Paragraphs(1)
                head = para.Range.Text.strip().replace("\r", "")[:40]
            except Exception:  # noqa: BLE001
                head = "(无法定位)"
            say(f"  第 {pg} 页起始段：{head or '(空段/图片)'}")

        # 字数（Word 统计，含标点）
        say(f"字数（Word 统计）：{doc.ComputeStatistics(0)}")

        # 逐段取样：用"段尾"位置判断该段落在哪一页、页内最低到了哪里
        TEXT_TOP_PT = 2.5 / 2.54 * 72            # 上边距
        TEXT_AREA_PT = (29.7 - 5.0) / 2.54 * 72  # 正文可用高度
        last_on_page: dict[int, float] = {}
        for idx in range(1, doc.Paragraphs.Count + 1):
            rng = doc.Paragraphs(idx).Range
            try:
                pg = int(rng.Information(3))        # wdActiveEndPageNumber
                vpos = float(rng.Information(6))    # wdVerticalPositionRelativeToPage
            except Exception:  # noqa: BLE001
                continue
            last_on_page[pg] = max(last_on_page.get(pg, 0.0), vpos)

        say("")
        say("每页内容填充率与底部留白（正文可用高度 24.7cm）：")
        for pg in sorted(last_on_page):
            used = (last_on_page[pg] - TEXT_TOP_PT) / TEXT_AREA_PT
            waste_cm = (TEXT_AREA_PT - (last_on_page[pg] - TEXT_TOP_PT)) / 72 * 2.54
            say(f"  第 {pg} 页：内容到 {used * 100:5.1f}%，底部留白约 {waste_cm:4.1f} cm")

        doc.Close(False)
    finally:
        word.Quit()

    (ROOT / "evaluations" / "measure_out.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not target.exists():
        print(f"文件不存在：{target}")
        raise SystemExit(1)
    measure(target)
