# -*- coding: utf-8 -*-
"""
可复现评测脚本：对比 A / B 两种方案。

A（基线）：普通大模型直接总结 —— prompts/baseline_summary.md，无 Schema、无知识库、无证据校验。
B（本作品）：结构化抽取 + 知识库 + 证据校验 + 二次自检 —— src/pipeline.py。

计算指标：
1. 风险类型识别准确率（完全匹配率 / 至少命中率）
2. 关键数字提取正确率（以人工标注中的数字为金标准，按召回计算）
3. 引用覆盖率（能通过原文校验的证据 / 全部证据）
4. 无依据结论率（证据未通过校验的风险结论 / 全部风险结论）
5. 平均响应时间

用法：
    python evaluations/evaluate.py --mode demo      # 无需密钥，B 方案走规则（演示模式）
    python evaluations/evaluate.py --mode llm       # 配置密钥后跑真实模型，A/B 都跑
    python evaluations/evaluate.py --mode demo --limit 5

输出（均在 evaluations/results/）：
    per_sample_results.csv   逐样本明细
    comparison.csv           A/B 汇总对比
    metrics_summary.json     汇总指标（含运行元数据）
    comparison_chart.png     可直接放进报告的柱状图

诚实性约定：
- 演示模式下 A 方案不运行，所有 A 列写为"待实测（未运行）"，绝不用假设数字填充。
- 演示模式下 B 方案的数值也会被标注 mode=demo，不能当作模型真实效果引用。
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.config import DATA_DIR, RESULTS_DIR, get_config  # noqa: E402
from src.evidence_checker import extract_numbers  # noqa: E402
from src.json_utils import coerce_dict, safe_json_loads  # noqa: E402
from src.llm_client import LLMError, make_client  # noqa: E402
from src.pipeline import Pipeline, wrap_untrusted  # noqa: E402
from src.prompts_loader import load_prompt  # noqa: E402

ANNOTATIONS = DATA_DIR / "annotations.csv"
PENDING = "待实测（未运行）"


# ------------------------------------------------------------------ 工具
def load_annotations() -> List[Dict[str, str]]:
    if not ANNOTATIONS.exists():
        raise FileNotFoundError(f"缺少标注文件：{ANNOTATIONS}，请先运行 python tools/gen_samples.py")
    with ANNOTATIONS.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gold_types(s: str) -> set:
    return {x.strip() for x in (s or "").replace("；", ";").split(";") if x.strip()}


def gold_numbers(s: str) -> List[float]:
    """从人工标注的"关键事实或关键数字"列里取数字（金额与百分比都算）。"""
    return extract_numbers(normalize_number_text(s or ""))


DATE_RE = re.compile(
    r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?(?:度|末|初|以来|上半年|下半年|第[一二三四]季度)?"
    r"|\d{4}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{1,2}"
    r"|\d{4}\s*[-/]\s*\d{1,2}(?!\d)"
    r"|\d{4}\s*年")

# 千分位逗号：数字-逗号-恰好三位数字
THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")


def normalize_number_text(s: str) -> str:
    """
    抽数值前的两步归一化，缺一不可。

    1) 去掉千分位逗号。"1,200,000股" 若直接按字符抽，会被切成 1、200、0 三个假数字，
       金标准的分母里就混进了根本不存在的数，命中率失去意义。
    2) 去掉日期中的数字。"2025年度应收账款余额7800万元"，年份会被当成一个关键数字，
       系统即使把 7800 抽对了，也会因为"没抽出 2025"被记成漏抽。
    两者都是评测口径缺陷而不是产品缺陷，故在计数前统一处理，A/B 两侧同规则。
    """
    s = THOUSANDS_RE.sub("", s or "")
    return DATE_RE.sub(" ", s)


def gold_numbers_split(s: str) -> tuple:
    """
    把标注数字拆成「本期关键数字」与「上年同期（对比基数）」两组。

    标注里常写"归母净利润2.10亿元；上年同期1.05亿元"，后者是对比基数而不是本期结论。
    系统按设计只抽本期值，因此需要单独统计本期口径的命中率，
    否则会把「正确地排除了同期基数」记成漏抽。
    """
    cur: List[float] = []
    prev: List[float] = []
    for seg in re.split(r"[；;]", s or ""):
        nums = extract_numbers(normalize_number_text(seg))
        if not nums:
            continue
        if re.search(r"上年同期|去年同期|上年年末|对比基数", seg):
            prev.extend(nums)
        else:
            cur.extend(nums)
    return cur, prev


def pred_numbers(values: List[str]) -> List[float]:
    out: List[float] = []
    for v in values:
        out.extend(extract_numbers(normalize_number_text(v)))
    return out


def ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


# ------------------------------------------------------------------ 方案 A
def run_baseline(text: str, client) -> Optional[Dict[str, Any]]:
    """
    基线方案：一次调用，直接总结。

    返回 None 表示未运行/失败（调用方需按"待实测"处理，不得编造结果）。
    """
    if client is None or not client.available:
        return None
    try:
        template = load_prompt("baseline_summary")
        prompt = template.replace("{announcement_text}", wrap_untrusted(text[:8000]))
        raw = client.chat(
            [{"role": "system", "content": "你是金融助手。"},
             {"role": "user", "content": prompt}],
            temperature=0.0)
        return coerce_dict(safe_json_loads(raw))
    except (LLMError, ValueError) as exc:
        print(f"  [基线调用失败] {exc}")
        return None


# ------------------------------------------------------------------ 主流程
def evaluate(mode: str, limit: Optional[int], out_dir: Path) -> Dict[str, Any]:
    rows = load_annotations()
    if limit:
        rows = rows[:limit]

    cfg = get_config()
    client = make_client(cfg) if mode == "llm" else None
    llm_ready = client is not None and client.available

    print(f"样本数：{len(rows)}；请求模式：{mode}；模型可用：{llm_ready}")
    if mode == "llm" and not llm_ready:
        print("警告：未检测到 LLM_API_KEY，方案 A 将标记为『待实测（未运行）』，方案 B 降级为演示模式。")

    per_sample: List[Dict[str, Any]] = []
    agg_b = {"type_exact": 0, "type_hit": 0, "num_hit": 0, "num_gold": 0,
             "num_hit_cur": 0, "num_gold_cur": 0,
             "evi_ok": 0, "evi_all": 0, "risk_all": 0, "risk_no_evi": 0, "time": 0.0}
    agg_a = {"type_exact": 0, "type_hit": 0, "num_hit": 0, "num_gold": 0,
             "num_hit_cur": 0, "num_gold_cur": 0,
             "evi_ok": 0, "evi_all": 0, "risk_all": 0, "risk_no_evi": 0, "time": 0.0}
    a_ran = 0

    for row in rows:
        path = ROOT / row["文件路径"]
        if not path.exists():
            print(f"  [跳过] 文件不存在：{path}")
            continue
        text = path.read_text(encoding="utf-8")
        g_types = gold_types(row["事件类型"])
        g_nums = gold_numbers(row["关键事实或关键数字"])
        g_cur, _g_prev = gold_numbers_split(row["关键事实或关键数字"])

        # -------- 方案 B
        pipeline = Pipeline(mode=mode, client=client)
        t0 = time.time()
        res = pipeline.run(text)
        elapsed = time.time() - t0

        p_types = {t.value for t in res.facts.event_types if t.value != "未识别"}
        p_nums = pred_numbers([m.value for m in res.facts.metrics] + [m.yoy_change for m in res.facts.metrics])

        type_exact = int(p_types == g_types)
        type_hit = int(len(p_types & g_types) > 0)
        num_hit = len([n for n in g_nums if any(abs(n - p) < 1e-6 for p in p_nums)])
        num_hit_cur = len([n for n in g_cur if any(abs(n - p) < 1e-6 for p in p_nums)])
        evi_all = len(res.evidence_verified) + len(res.evidence_unverified)
        evi_ok = len(res.evidence_verified)
        risk_all = len(res.risks)
        risk_no_evi = sum(1 for r in res.risks if not r.evidence.matched)

        agg_b["type_exact"] += type_exact
        agg_b["type_hit"] += type_hit
        agg_b["num_hit"] += num_hit
        agg_b["num_gold"] += len(g_nums)
        agg_b["num_hit_cur"] += num_hit_cur
        agg_b["num_gold_cur"] += len(g_cur)
        agg_b["evi_ok"] += evi_ok
        agg_b["evi_all"] += evi_all
        agg_b["risk_all"] += risk_all
        agg_b["risk_no_evi"] += risk_no_evi
        agg_b["time"] += elapsed

        # -------- 方案 A
        a_types, a_nums = set(), []
        a_time = None
        if mode == "llm" and llm_ready:
            t1 = time.time()
            base = run_baseline(text, client)
            a_time = time.time() - t1
            if base is not None:
                a_ran += 1
                agg_a["time"] += a_time
                a_types = {str(base.get("risk_type", "")).strip()}
                a_nums = pred_numbers([str(x) for x in base.get("key_numbers", []) or []])
                a_type_exact = int(a_types == g_types)
                a_type_hit = int(len(a_types & g_types) > 0)
                a_num_hit = len([n for n in g_nums if any(abs(n - p) < 1e-6 for p in a_nums)])
                a_num_hit_cur = len([n for n in g_cur if any(abs(n - p) < 1e-6 for p in a_nums)])
                agg_a["type_exact"] += a_type_exact
                agg_a["type_hit"] += a_type_hit
                agg_a["num_hit"] += a_num_hit
                agg_a["num_gold"] += len(g_nums)
                agg_a["num_hit_cur"] += a_num_hit_cur
                agg_a["num_gold_cur"] += len(g_cur)
                # 基线不产出可定位证据：覆盖率记 0，无依据结论率记 100%（定义使然）
                agg_a["evi_all"] += 1
                agg_a["evi_ok"] += 0
                agg_a["risk_all"] += 1
                agg_a["risk_no_evi"] += 1

        per_sample.append({
            "样本编号": row["样本编号"],
            "公司名称": row["公司名称"],
            "样本性质": row["样本性质"],
            "标注事件类型": ";".join(sorted(g_types)),
            "B_预测事件类型": ";".join(sorted(p_types)),
            "B_类型完全匹配": type_exact,
            "B_类型至少命中": type_hit,
            "标注关键数字个数": len(g_nums),
            "B_命中关键数字个数": num_hit,
            "标注本期数字个数": len(g_cur),
            "B_命中本期数字个数": num_hit_cur,
            "B_证据总数": evi_all,
            "B_已验证证据数": evi_ok,
            "B_风险结论数": risk_all,
            "B_无依据结论数": risk_no_evi,
            "B_整体风险等级": res.overall_risk_level.value,
            "B_整体置信度": res.overall_confidence,
            "B_用时秒": round(elapsed, 3),
            "B_运行模式": res.mode,
            "A_预测风险类型": ";".join(sorted(a_types)) if (mode == "llm" and llm_ready) else PENDING,
            "A_命中关键数字个数": (len([n for n in g_nums if any(abs(n - p) < 1e-6 for p in a_nums)])
                                  if (mode == "llm" and llm_ready) else PENDING),
            "A_用时秒": round(a_time, 3) if a_time is not None else PENDING,
        })

    n = len(per_sample)
    summary: Dict[str, Any] = {
        "运行时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "请求模式": mode,
        "模型是否可用": llm_ready,
        "模型名称": (client.cfg.model if llm_ready else PENDING),
        "样本数": n,
        "Python版本": platform.python_version(),
        "B_方案": {
            "实际运行模式": "demo（规则）" if not llm_ready else mode,
            "风险类型识别准确率_完全匹配": ratio(agg_b["type_exact"], n),
            "风险类型识别准确率_至少命中": ratio(agg_b["type_hit"], n),
            "关键数字提取正确率": ratio(agg_b["num_hit"], agg_b["num_gold"]),
            "关键数字提取正确率_本期口径": ratio(agg_b["num_hit_cur"], agg_b["num_gold_cur"]),
            "引用覆盖率": ratio(agg_b["evi_ok"], agg_b["evi_all"]),
            "无依据结论率": ratio(agg_b["risk_no_evi"], agg_b["risk_all"]),
            "平均响应时间秒": round(agg_b["time"] / n, 4) if n else 0.0,
        },
        "A_方案": None,
        "说明": [],
    }

    if mode == "llm" and llm_ready and a_ran > 0:
        summary["A_方案"] = {
            "风险类型识别准确率_完全匹配": ratio(agg_a["type_exact"], a_ran),
            "风险类型识别准确率_至少命中": ratio(agg_a["type_hit"], a_ran),
            "关键数字提取正确率": ratio(agg_a["num_hit"], agg_a["num_gold"]),
            "关键数字提取正确率_本期口径": ratio(agg_a["num_hit_cur"], agg_a["num_gold_cur"]),
            "引用覆盖率": 0.0,
            "无依据结论率": 1.0,
            "平均响应时间秒": round(agg_a["time"] / a_ran, 4),
        }
        summary["说明"].append("A 方案不输出可定位引文，因此引用覆盖率按 0、无依据结论率按 100% 计（定义使然）。")
    else:
        summary["A_方案"] = {k: PENDING for k in (
            "风险类型识别准确率_完全匹配", "风险类型识别准确率_至少命中",
            "关键数字提取正确率", "关键数字提取正确率_本期口径",
            "引用覆盖率", "无依据结论率", "平均响应时间秒")}
        summary["说明"].append("A 方案需要真实模型调用，本次未运行，全部指标标记为「待实测（未运行）」。")

    summary["说明"].append(
        "「关键数字提取正确率」以标注中的全部数字为分母（含「上年同期」对比基数）；"
        "「关键数字提取正确率_本期口径」只统计本期结论性数字。系统按设计只抽本期值，"
        "因此前者会因为「正确地排除了同期基数」而被扣分，后者更贴近产品目标，两者一并报告。")
    summary["说明"].append(
        "统计前会先剔除日期中的数字（如「2025年度」「2026-07-15」）并去掉千分位逗号。"
        "否则年份会被当成一个关键数字、11位股数会被切成 1/200/0 三个假数字，"
        "把系统正确抽出的金额记成错误。两侧同规则。")
    summary["说明"].append(
        "A 与 B 使用同一套 7 个风险类型标签词表（仅为可比性统一词表），"
        "A 仍为单次调用、无 Schema 校验、无知识库判定规则、无证据回溯。")

    if not llm_ready:
        summary["说明"].append("B 方案在无密钥时以「演示模式」运行（确定性规则，非模型输出），"
                               "数值仅用于验证评测脚本可跑通，不能代表模型真实效果。")

    # ------------------------------------------------------------ 落盘
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(per_sample)
    df.to_csv(out_dir / "per_sample_results.csv", index=False, encoding="utf-8-sig")

    comp_rows = []
    keys = ["风险类型识别准确率_完全匹配", "风险类型识别准确率_至少命中", "关键数字提取正确率",
            "关键数字提取正确率_本期口径", "引用覆盖率", "无依据结论率", "平均响应时间秒"]
    for k in keys:
        comp_rows.append({"指标": k,
                          "A_普通大模型直接总结": summary["A_方案"][k],
                          "B_结构化抽取+知识库+证据校验": summary["B_方案"][k]})
    pd.DataFrame(comp_rows).to_csv(out_dir / "comparison.csv", index=False, encoding="utf-8-sig")

    (out_dir / "metrics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    make_chart(comp_rows, out_dir / "comparison_chart.png", llm_ready)
    return summary


def make_chart(comp_rows: List[Dict[str, Any]], png_path: Path, llm_ready: bool) -> None:
    """生成对比柱状图；未跑 A 方案时只画 B 方案。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        for font in ("Microsoft YaHei", "SimHei", "DengXian", "Noto Sans CJK SC"):
            try:
                matplotlib.font_manager.findfont(font, fallback_to_default=False)
                plt.rcParams["font.sans-serif"] = [font]
                break
            except Exception:  # noqa: BLE001
                continue
        plt.rcParams["axes.unicode_minus"] = False
    except Exception as exc:  # noqa: BLE001
        print(f"  [图表跳过] matplotlib 不可用：{exc}")
        return

    def to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    labels, vals_a, vals_b = [], [], []
    for r in comp_rows:
        if r["指标"] == "平均响应时间秒":
            continue
        va, vb = to_float(r["A_普通大模型直接总结"]), to_float(r["B_结构化抽取+知识库+证据校验"])
        if vb is None:
            continue
        labels.append(r["指标"].replace("_", "\n"))
        vals_a.append(va if (llm_ready and va is not None) else 0.0)
        vals_b.append(vb)

    if not labels:
        return

    x = range(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10, 4.9), dpi=160)
    if llm_ready:
        ax.bar([i - width / 2 for i in x], vals_a, width, label="A 普通大模型直接总结", color="#c0c4cc")
        ax.bar([i + width / 2 for i in x], vals_b, width, label="B 结构化抽取+知识库+证据校验", color="#2f6fed")
    else:
        ax.bar(list(x), vals_b, width, label="B 方案（演示模式，规则）", color="#2f6fed")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("比率")
    ax.set_title("方案 A / B 评测指标对比" + ("" if llm_ready else "（A 方案未运行，标记待实测）"),
                 fontsize=12, pad=12)
    # 图例放到图外下方，避免压住柱子
    ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=2, frameon=False)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    for i, (va, vb) in enumerate(zip(vals_a, vals_b)):
        if llm_ready:
            ax.text(i - width / 2, va + 0.02, f"{va:.2f}", ha="center", fontsize=8)
        ax.text(i + (width / 2 if llm_ready else 0), vb + 0.02, f"{vb:.2f}",
                ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="评测：A 普通大模型直接总结 vs B 结构化工作流")
    ap.add_argument("--mode", choices=["demo", "llm"], default="demo",
                    help="demo=无需密钥跑通流程；llm=需要配置 LLM_API_KEY")
    ap.add_argument("--limit", type=int, default=None, help="只评测前 N 个样本")
    ap.add_argument("--out", type=str, default=None, help="结果输出目录")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = evaluate(args.mode, args.limit, out_dir)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n结果已写入：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
