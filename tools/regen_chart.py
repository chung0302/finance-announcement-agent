# -*- coding: utf-8 -*-
"""
只用已有的 comparison.csv 重画对比图，不重跑模型调用。

用法：python tools/regen_chart.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evaluations"))

from src.config import RESULTS_DIR  # noqa: E402
from evaluate import make_chart  # noqa: E402


def main() -> None:
    csv_path = RESULTS_DIR / "comparison.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    llm_ready = any(r["A_普通大模型直接总结"] not in ("", "待实测（未运行）") for r in rows)
    out = RESULTS_DIR / "comparison_chart.png"
    make_chart(rows, out, llm_ready)
    print(f"已重画：{out}（A 方案已运行={llm_ready}）")


if __name__ == "__main__":
    main()
