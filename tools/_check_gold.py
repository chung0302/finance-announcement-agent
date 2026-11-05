# -*- coding: utf-8 -*-
"""临时校验：剔除日期后，各样本的金标准数字是什么。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluations"))

import csv  # noqa: E402

from src.config import DATA_DIR  # noqa: E402
from evaluate import gold_numbers, gold_numbers_split, normalize_number_text  # noqa: E402

lines = []
with (DATA_DIR / "annotations.csv").open("r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        raw = r["关键事实或关键数字"]
        cur, prev = gold_numbers_split(raw)
        lines.append(f"{r['样本编号']}")
        lines.append(f"  原文：{raw}")
        lines.append(f"  归一化：{normalize_number_text(raw)}")
        lines.append(f"  全部数字：{gold_numbers(raw)}")
        lines.append(f"  本期={cur}  同期={prev}")
        lines.append("")

Path(ROOT / "evaluations" / "gold_check.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok")
