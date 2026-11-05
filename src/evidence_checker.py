"""
证据校验模块（流水线第 4 步）。

硬性规则：
- 任何要展示给用户的"关键结论 / 风险原因 / 关键数字"，都必须带 evidence.quote。
- quote 必须在「清洗后原文」中可定位：先精确包含匹配，再退回模糊匹配。
- 匹配不上的证据，一律标记为 matched=False，前端归入「未通过校验」，
  不得作为有效依据展示；同时会拉低结论置信度。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

from .config import EVIDENCE_MATCH_THRESHOLD, MIN_EVIDENCE_LEN
from .schemas import Evidence
from .text_cleaner import normalize_for_matching


def _too_short(quote: str) -> bool:
    """过短的片段（少于 MIN_EVIDENCE_LEN 个有效字符）不具备证据效力。"""
    return len(normalize_for_matching(quote)) < MIN_EVIDENCE_LEN


def check_evidence(quote: str, cleaned_text: str,
                   threshold: float = EVIDENCE_MATCH_THRESHOLD) -> Evidence:
    """
    校验单条证据能否在清洗后原文中定位。

    :return: Evidence，matched / score / match_method 已回填
    """
    ev = Evidence(quote=(quote or "").strip())
    if not ev.quote or not cleaned_text:
        ev.matched, ev.score, ev.match_method = False, 0.0, "未提供证据"
        return ev
    if _too_short(ev.quote):
        ev.matched, ev.score, ev.match_method = False, 0.0, "证据过短"
        return ev

    q = normalize_for_matching(ev.quote)
    t = normalize_for_matching(cleaned_text)

    # 1) 精确包含
    if q in t:
        ev.matched, ev.score, ev.match_method = True, 1.0, "精确包含"
        return ev

    # 2) 取原文中与证据等长的所有窗口，做模糊相似度比较
    n = len(q)
    if n <= 0 or len(t) == 0:
        ev.matched, ev.score, ev.match_method = False, 0.0, "未匹配"
        return ev
    best = 0.0
    step = max(1, n // 2)  # 步长取半窗，兼顾速度与召回
    for i in range(0, max(1, len(t) - n + 1), step):
        window = t[i:i + n]
        r = difflib.SequenceMatcher(None, q, window).ratio()
        if r > best:
            best = r
        if best >= 0.999:
            break

    # 3) 证据是长句被截断时，尝试前缀匹配（模型常截断长句）
    if best < threshold:
        head = q[: max(MIN_EVIDENCE_LEN, int(len(q) * 0.6))]
        if head and head in t:
            ev.matched, ev.score, ev.match_method = True, 0.95, "前缀包含"
            return ev

    ev.score = round(best, 4)
    ev.matched = best >= threshold
    ev.match_method = "模糊匹配" if ev.matched else "未匹配"
    return ev


def find_snippet(cleaned_text: str, keyword: str, window: int = 60) -> Optional[str]:
    """
    在清洗后原文中定位关键词，并返回其周围的一段原文（用于自动补证据）。

    找不到时返回 None —— 调用方必须按"信息不足"处理，不得捏造引文。
    """
    if not cleaned_text or not keyword:
        return None
    idx = cleaned_text.find(keyword)
    if idx < 0:
        return None
    start = max(0, idx - window // 2)
    end = min(len(cleaned_text), idx + len(keyword) + window // 2)
    return cleaned_text[start:end].strip()


def check_all(evidences: List[Evidence], cleaned_text: str) -> Tuple[List[Evidence], List[Evidence]]:
    """批量校验，返回 (已验证, 未通过校验)。"""
    ok: List[Evidence] = []
    bad: List[Evidence] = []
    for e in evidences:
        checked = check_evidence(e.quote, cleaned_text)
        checked.note = e.note
        (ok if checked.matched else bad).append(checked)
    return ok, bad


# ------------------------------------------------------------------ 数字一致性
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_numbers(s: str) -> List[float]:
    """从字符串中提取所有数字（用于自检阶段核对关键数字是否被改动）。"""
    if not s:
        return []
    out = []
    for m in _NUM_RE.findall(str(s)):
        try:
            out.append(float(m))
        except ValueError:
            continue
    return out


def numbers_consistent(claim: str, evidence_quote: str) -> bool:
    """
    自检用：结论里出现的数字，是否都能在对应证据原文中找到。

    结论没写数字 -> True（无可核对项）。
    结论写了数字但证据里一个都对不上 -> False（疑似幻觉数字）。
    """
    nums = extract_numbers(claim)
    if not nums:
        return True
    ev_nums = extract_numbers(evidence_quote)
    if not ev_nums:
        return False
    return all(any(abs(a - b) < 1e-6 for b in ev_nums) for a in nums)
