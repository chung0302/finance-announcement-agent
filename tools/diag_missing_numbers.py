# -*- coding: utf-8 -*-
"""
诊断：找出 B 方案在「本期口径」上漏抽的数字，并打印抽取出的指标明细。
用法：python tools/diag_missing_numbers.py eval_003 eval_006 eval_009
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import csv  # noqa: E402

from src.config import DATA_DIR  # noqa: E402
from src.evidence_checker import extract_numbers  # noqa: E402
from src.llm_client import make_client  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402
from src.config import get_config  # noqa: E402

sys.path.insert(0, str(ROOT / "evaluations"))
from evaluate import gold_numbers_split  # noqa: E402


def main(targets: list[str]) -> None:
    out_lines: list[str] = []

    def say(s: str = "") -> None:
        out_lines.append(s)
        try:
            print(s)
        except Exception:  # noqa: BLE001
            pass

    with (DATA_DIR / "annotations.csv").open("r", encoding="utf-8-sig", newline="") as f:
        rows = {r["样本编号"]: r for r in csv.DictReader(f)}

    cfg = get_config()
    client = make_client(cfg)
    say(f"模型可用：{client is not None and client.available}")

    for sid in targets:
        row = rows.get(sid)
        if row is None:
            say(f"[跳过] 无样本 {sid}")
            continue
        text = (ROOT / row["文件路径"]).read_text(encoding="utf-8")
        cur, prev = gold_numbers_split(row["关键事实或关键数字"])
        res = Pipeline(mode="llm", client=client).run(text)

        pred = []
        for m in res.facts.metrics:
            pred.extend(extract_numbers(m.value))
            if m.yoy_change:
                pred.extend(extract_numbers(m.yoy_change))

        miss = [n for n in cur if not any(abs(n - p) < 1e-6 for p in pred)]
        say("\n" + "=" * 70)
        say(f"{sid}  {row['公司名称']}")
        say(f"标注本期数字：{cur}")
        say(f"标注同期数字：{prev}")
        say(f"系统抽取数字：{sorted(set(pred))}")
        say(f"漏抽（本期口径）：{miss}")
        say("抽取到的指标：")
        for m in res.facts.metrics:
            say(f"  - 名称={m.name!r} 值={m.value!r} 单位={m.unit!r} 同比={m.yoy_change!r}")

    (ROOT / "evaluations" / "diag_out.txt").write_text("\n".join(out_lines), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:] or ["eval_003", "eval_006", "eval_009"])
