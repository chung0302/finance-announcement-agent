"""
二次自检模块（流水线第 5 步）。

执行两类检查：
A. 规则自检（任何模式下都必须执行，保证下限）：
   1. 公司名称 / 日期 / 金额 / 事件类型 是否与输入原文一致；
   2. 每条风险结论的证据是否通过校验 —— 未通过的一律降级并标记人工复核，
      其中"原文直述事实"降级为"推断"（无法追溯的事实性结论不允许保留）；
   3. 是否混入投资建议（买入/卖出/目标价等）—— 命中即删除并告警；
   4. 缺失字段统一填"未披露"或"信息不足"。
B. 模型自检（仅 LLM 模式）：用 prompts/self_check.md 再跑一遍核对。

原则：自检发现问题不是"报错退出"，而是**降级 + 显式标注**，让用户看到不确定性。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .evidence_checker import check_evidence, numbers_consistent
from .llm_client import LLMClient, LLMError
from .prompts_loader import load_prompt
from .schemas import (INSUFFICIENT, UNKNOWN, AnalysisResult,
                      RiskLevel, SelfCheckIssue)
from .text_cleaner import normalize_for_matching

# 投资建议黑名单词（出现即视为越界输出）
_ADVICE_PATTERNS = [
    r"建议(?:买入|卖出|增持|减持|清仓|加仓)",
    r"(?:可以|应当|建议)?(?:逢低|积极)?买入",
    r"目标价",
    r"值得投资",
    r"(?:强烈)?推荐(?:买入|持有)?",
    r"股价(?:将|会)?(?:上涨|下跌)",
    r"后市(?:看多|看空)",
]
_ADVICE_RE = re.compile("|".join(_ADVICE_PATTERNS))


def _looks_like_advice(text: str) -> bool:
    return bool(text) and bool(_ADVICE_RE.search(text))


def _norm(s: str) -> str:
    return normalize_for_matching(s or "")


# 「信息不足」去重的字符覆盖率阈值：短句里这么多字都能在长句中找到，视为同一件事
MISSING_COVERAGE = 0.9


def _near_duplicate(a: str, b: str) -> bool:
    """
    两条缺失信息是否在说同一件事。

    中文里同一件事常被换个语序重写（"涉案金额未披露" / "公告未披露涉案金额"），
    词序不同但用字几乎一样，因此用**字符集合覆盖率**判断，而不是序列相似度。
    阈值取 0.9 而非更低，是为了避免把"担保余额未披露"和"被担保方资产负债率未披露"
    这类确实不同的缺失项合并掉（两者覆盖率为 0.86）。
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    pool = set(long_)
    hit = sum(1 for ch in set(short) if ch in pool)
    return hit / len(set(short)) >= MISSING_COVERAGE


def dedupe_missing(items: List[str]) -> List[str]:
    """
    合并语义近似的缺失信息。

    模型与规则各写一遍"未披露什么"，很容易出现
    「涉案金额未披露」「公告未披露涉案金额」「公告未披露涉案金额占净资产比例」三条，
    读者只看到噪声。这里做一次近似合并，同一件事只保留**表述最具体**的那条，
    并保持原有顺序，以免界面上出现十几条看似不同的重复提示。

    注意：合并"代表项"时可能换成了更长的一条，而先前被判为不重复的条目
    可能恰与新代表项重复，因此要反复扫描到不再变化（最多 5 轮）。
    """
    kept: List[str] = [x.strip() for x in items if (x or "").strip()]

    for _ in range(5):
        merged: List[str] = []
        changed = False
        for text in kept:
            idx = next((i for i, k in enumerate(merged) if _near_duplicate(text, k)), None)
            if idx is None:
                merged.append(text)
            else:
                changed = True
                if len(_norm(text)) > len(_norm(merged[idx])):
                    merged[idx] = text
        kept = merged
        if not changed:
            break
    return kept


def run_rule_self_check(result: AnalysisResult, cleaned_text: str) -> Tuple[AnalysisResult, List[SelfCheckIssue]]:
    """纯规则自检，任何模式都执行。直接修改并返回 result。"""
    issues: List[SelfCheckIssue] = []
    text_n = _norm(cleaned_text)
    f = result.facts

    # 1. 公司名称一致性
    if f.company_name not in (UNKNOWN, INSUFFICIENT, ""):
        if _norm(f.company_name) not in text_n:
            issues.append(SelfCheckIssue(
                field_name="公司名称",
                issue=f"抽取的公司名称「{f.company_name}」未在原文中出现",
                action="标记为未披露", severity="严重"))
            f.company_name = UNKNOWN
            if "公司名称未披露" not in f.missing_fields:
                f.missing_fields.append("公司名称未披露")

    # 2. 日期一致性：按中文/ISO 两种写法核对，不能直接比对零填充数字
    if f.announcement_date not in (UNKNOWN, INSUFFICIENT, ""):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", f.announcement_date)
        if m:
            y, mo, d = m.group(1), str(int(m.group(2))), str(int(m.group(3)))
            candidates = [
                f"{y}年{mo}月{d}日", f"{y}-{mo}-{d}", f"{y}/{mo}/{d}",
                f"{y}.{mo}.{d}", f"{y}-{m.group(2)}-{m.group(3)}",
            ]
            if not any(_norm(c) in text_n for c in candidates):
                issues.append(SelfCheckIssue(
                    field_name="公告日期",
                    issue=f"公告日期「{f.announcement_date}」无法在原文中核对",
                    action="降级为未披露并提示复核", severity="提示"))
                f.announcement_date = UNKNOWN
                if "公告日期未披露" not in f.missing_fields:
                    f.missing_fields.append("公告日期未披露")

    # 3. 金额一致性
    kept_metrics = []
    for m in f.metrics:
        if m.evidence.matched and not numbers_consistent(m.value, m.evidence.quote):
            issues.append(SelfCheckIssue(
                field_name=f"关键指标[{m.name}]",
                issue=f"数值「{m.value}」与其证据原文中的数字不一致",
                action="删除该指标", severity="严重"))
            continue
        if not m.evidence.matched:
            issues.append(SelfCheckIssue(
                field_name=f"关键指标[{m.name}]",
                issue="该指标的证据未通过原文校验",
                action="保留但标记为未通过校验", severity="提示"))
        kept_metrics.append(m)
    f.metrics = kept_metrics

    # 4. 事件类型是否有原文支撑
    for t in list(f.event_types):
        if t.value == "未识别":
            continue
        from .knowledge_base import load_kb
        kws = []
        for rule in load_kb().get("risk_rules", []):
            if rule.get("risk_type") == t.value:
                kws = rule.get("trigger_keywords", [])
                break
        if kws and not any(_norm(k) in text_n for k in kws):
            issues.append(SelfCheckIssue(
                field_name=f"事件类型[{t.value}]",
                issue="该事件类型在原文中找不到触发词支撑",
                action="删除该事件类型", severity="严重"))
            f.event_types.remove(t)
    if not f.event_types:
        f.event_types = []

    # 5. 逐条风险：证据校验 + 投资建议清理
    kept_risks = []
    for r in result.risks:
        # 5.1 投资建议
        if _looks_like_advice(r.reason) or any(_looks_like_advice(x) for x in r.inferences):
            issues.append(SelfCheckIssue(
                field_name=f"风险[{r.risk_type.value}].原因/推断",
                issue="输出中疑似包含投资建议，违反本工具边界",
                action="删除该表述", severity="严重"))
            r.reason = re.sub(_ADVICE_RE, "（已删除：本工具不提供投资建议）", r.reason)
            r.inferences = [x for x in r.inferences if not _looks_like_advice(x)]

        # 5.2 证据校验
        if not r.evidence.matched:
            if r.facts:
                # 无法追溯的"原文事实"降级为"推断"
                r.inferences.extend([f"（原列为原文事实，因证据未通过校验已降级）{x}" for x in r.facts])
                r.facts = []
            issues.append(SelfCheckIssue(
                field_name=f"风险[{r.risk_type.value}]",
                issue="证据未通过原文校验，无法追溯",
                action="风险等级降为信息不足、置信度下调、标记人工复核", severity="严重"))
            r.risk_level = RiskLevel.UNKNOWN
            r.confidence = min(r.confidence, 0.3)
            r.need_human_review = True
            if not r.uncertainties:
                r.uncertainties = ["缺少可校验的原文证据"]
        else:
            # 证据匹配但结论数字与证据数字对不上
            if not numbers_consistent(" ".join(r.facts + [r.reason]), r.evidence.quote):
                issues.append(SelfCheckIssue(
                    field_name=f"风险[{r.risk_type.value}]",
                    issue="结论中的数字无法在证据原文中找到（疑似幻觉数字）",
                    action="置信度下调并标记人工复核", severity="严重"))
                r.confidence = max(0.1, r.confidence - 0.2)
                r.need_human_review = True
        kept_risks.append(r)
    result.risks = kept_risks

    # 6. 缺失信息汇总（统一措辞）
    missing: List[str] = []
    for m in f.missing_fields:
        if m and m not in missing:
            missing.append(m)
    for r in result.risks:
        if r.risk_level == RiskLevel.UNKNOWN or r.need_human_review:
            tip = f"「{r.risk_type.value}」证据或关键数据不足，需人工复核"
            if tip not in missing:
                missing.append(tip)
        for u in r.uncertainties:
            if u and u not in missing:
                missing.append(u)
    result.missing_info = dedupe_missing(missing)

    # 7. 重算整体等级与置信度
    levels = [r.risk_level for r in result.risks]
    result.overall_risk_level = max(levels, key=lambda x: {"信息不足": 0, "低": 1, "中": 2, "高": 3}.get(x.value, 0)) if levels else RiskLevel.UNKNOWN
    if result.risks:
        result.overall_confidence = round(sum(r.confidence for r in result.risks) / len(result.risks), 3)
    else:
        result.overall_confidence = 0.0
        if "未识别出任何既定风险类型，需人工阅读原文确认" not in result.missing_info:
            result.missing_info.append("未识别出任何既定风险类型，需人工阅读原文确认")

    result.self_check_passed = not any(i.severity == "严重" for i in issues)
    result.self_check_issues = issues
    return result, issues


def run_llm_self_check(result: AnalysisResult, cleaned_text: str, client: Optional[LLMClient]) -> List[SelfCheckIssue]:
    """模型辅助自检（失败时静默返回空列表，不影响主流程）。"""
    if client is None or not client.available:
        return []
    try:
        template = load_prompt("self_check")
        prompt = (template
                  .replace("{announcement_text}", cleaned_text[:6000])
                  .replace("{analysis_result}", result.model_dump_json(ensure_ascii=False)[:6000]))
        raw = client.chat(
            [{"role": "system", "content": "你是严格的合规与事实核对助手，只输出 JSON。"},
             {"role": "user", "content": prompt}],
            temperature=0.0)
        from .json_utils import coerce_dict, safe_json_loads
        data = coerce_dict(safe_json_loads(raw))
        out: List[SelfCheckIssue] = []
        for it in data.get("issues", []) or []:
            if isinstance(it, dict):
                out.append(SelfCheckIssue(
                    field_name=str(it.get("field_name", "")),
                    issue=str(it.get("issue", "")),
                    action=str(it.get("action", "保留")),
                    severity=str(it.get("severity", "提示")),
                ))
        return out
    except (LLMError, ValueError, Exception):  # noqa: BLE001
        return []
