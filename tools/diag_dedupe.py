# -*- coding: utf-8 -*-
"""诊断：把 demo_002 跑一遍，打印去重前后的「信息不足提示」。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import SAMPLES_DIR, get_config  # noqa: E402
from src.llm_client import make_client  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402
from src.self_check import _near_duplicate, dedupe_missing  # noqa: E402

text = (SAMPLES_DIR / "demo_002_risk_share_reduction.txt").read_text(encoding="utf-8")
res = Pipeline(mode="llm", client=make_client(get_config())).run(text)

raw: list[str] = []
for m in res.facts.missing_fields:
    if m and m not in raw:
        raw.append(m)
for r in res.risks:
    for u in r.uncertainties:
        if u and u not in raw:
            raw.append(u)

lines = ["【原始 uncertainties 合并后】"]
lines += [f"  {i+1}. {x}" for i, x in enumerate(raw)]
lines.append("")
lines.append("【逐对判断】")
for i in range(len(raw)):
    for j in range(i + 1, len(raw)):
        if _near_duplicate(raw[i], raw[j]):
            lines.append(f"  近似: [{i+1}] {raw[i]}  <=>  [{j+1}] {raw[j]}")
lines.append("")
lines.append("【去重后】")
lines += [f"  {i+1}. {x}" for i, x in enumerate(dedupe_missing(raw))]
lines.append("")
lines.append("【最终 result.missing_info】")
lines += [f"  {i+1}. {x}" for i, x in enumerate(res.missing_info)]

(ROOT / "evaluations" / "dedupe_diag.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok")
