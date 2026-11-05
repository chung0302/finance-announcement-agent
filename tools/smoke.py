# -*- coding: utf-8 -*-
"""本地冒烟脚本：跑通两个演示样例，把结果写到 _smoke_out.txt 便于查看。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pipeline import Pipeline  # noqa: E402
from src.text_cleaner import clean_text  # noqa: E402


def main():
    out = []
    p = Pipeline(mode="demo")
    for name in ("demo_001_positive_earnings_up.txt", "demo_002_risk_share_reduction.txt"):
        path = ROOT / "data" / "samples" / name
        raw = path.read_text(encoding="utf-8")
        res = p.run(raw)
        out.append("=" * 70)
        out.append(f"### {name}")
        out.append(f"模式={res.mode} 用时={res.elapsed_seconds}s 输入字数={res.input_chars}")
        out.append(f"公司={res.facts.company_name} | 标题={res.facts.announcement_title} | 日期={res.facts.announcement_date} | 代码={res.facts.stock_code}")
        out.append(f"事件类型={[t.value for t in res.facts.event_types]}")
        out.append(f"指标数={len(res.facts.metrics)}")
        for m in res.facts.metrics[:5]:
            out.append(f"  - {m.name} = {m.value} ({m.yoy_change}) 证据校验={m.evidence.matched} score={m.evidence.score}")
        out.append(f"整体等级={res.overall_risk_level.value} 置信度={res.overall_confidence}")
        for r in res.risks:
            out.append(f"  [风险] {r.risk_type.value} / {r.risk_level.value} / conf={r.confidence} / 证据={r.evidence.matched} {r.evidence.score}")
            out.append(f"        reason={r.reason[:120]}")
            out.append(f"        evidence={r.evidence.quote[:80]}")
        out.append(f"已验证证据={len(res.evidence_verified)} 未通过={len(res.evidence_unverified)}")
        out.append(f"缺失信息={res.missing_info}")
        out.append(f"自检通过={res.self_check_passed} 问题数={len(res.self_check_issues)}")
        for i in res.self_check_issues:
            out.append(f"   - [{i.severity}] {i.field_name}: {i.issue} -> {i.action}")
        out.append("告警: " + "; ".join(res.warnings))
    (ROOT / "_smoke_out.txt").write_text("\n".join(out), encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
