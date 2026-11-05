"""
风险识别模块（流水线第 3 步）。

要点：
- 结合「结构化事实 + 知识库检索结果」做判断，知识库只作参考，不替代原文证据。
- 每条风险必须区分：facts（原文直述）/ inferences（推断）/ uncertainties（不确定性）。
- 风险等级取值：低 / 中 / 高 / 信息不足。
- 公告信息不足以支撑判断时：降低置信度 + need_human_review=True + 明确写出缺什么。
- 演示模式使用确定性规则，输出内容明确标注，不冒充模型输出。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .evidence_checker import find_snippet
from .json_utils import coerce_dict, safe_json_loads
from .knowledge_base import format_retrieved, load_kb, retrieve
from .llm_client import LLMClient, LLMError
from .prompts_loader import load_prompt
from .schemas import (INSUFFICIENT, UNKNOWN, Evidence, ExtractedFacts,
                      RiskItem, RiskLevel, RiskType)

# 演示模式下的规则化升级条件（命中则提升一级）
_ESCALATION_RULES: Dict[str, List[str]] = {
    RiskType.EARNINGS_DOWN.value: ["首亏", "首次亏损", "由盈转亏", "退市风险警示", "可能被实施退市"],
    RiskType.SHARE_REDUCTION.value: ["控股股东", "实际控制人", "董事长", "总经理"],
    RiskType.LITIGATION.value: ["立案", "行政处罚", "判决", "被执行", "冻结"],
    RiskType.GUARANTEE.value: ["资金占用", "非经营性占用", "逾期", "资产负债率超过70%"],
    RiskType.AUDIT_REGULATORY.value: ["无法表示意见", "否定意见", "立案调查", "行政处罚"],
    RiskType.EARNINGS_UP.value: ["非经常性损益", "出售资产", "政府补助", "资产处置"],
}

_ESCALATION_NOTE: Dict[str, str] = {
    RiskType.EARNINGS_DOWN.value: "公告出现退市风险或首次亏损相关表述，风险等级上调。",
    RiskType.SHARE_REDUCTION.value: "减持主体为控股股东/实际控制人/董监高，风险等级上调。",
    RiskType.LITIGATION.value: "诉讼已被判决、执行或公司被立案，风险等级上调。",
    RiskType.GUARANTEE.value: "存在资金占用、担保逾期或被担保方高负债，风险等级上调。",
    RiskType.AUDIT_REGULATORY.value: "非标准审计意见或立案调查，风险等级维持高。",
    RiskType.EARNINGS_UP.value: "业绩增长可能主要来自非经常性损益，可持续性存疑，提示关注。",
}

_LEVEL_UP = {RiskLevel.LOW: RiskLevel.MEDIUM, RiskLevel.MEDIUM: RiskLevel.HIGH,
             RiskLevel.HIGH: RiskLevel.HIGH, RiskLevel.UNKNOWN: RiskLevel.UNKNOWN}


def _level_from_text(level_text: str, default: RiskLevel) -> RiskLevel:
    for lv in RiskLevel:
        if level_text == lv.value:
            return lv
    return default


def _rule_default_level(risk_type: RiskType, kb: Dict) -> RiskLevel:
    for rule in kb.get("risk_rules", []):
        if rule.get("risk_type") == risk_type.value:
            return _level_from_text(rule.get("default_level", "信息不足"), RiskLevel.UNKNOWN)
    return RiskLevel.UNKNOWN


def _pick_evidence(text: str, risk_type: RiskType, kb: Dict) -> str:
    """
    从原文中挑一条最能支撑该风险类型的片段；找不到返回空串（表示无证据）。

    策略：遍历该风险类型的所有触发词、以及它在原文中的每一次出现，
    按"是否含数字 > 是否含金额单位 > 片段信息量"打分，取最高分的窗口。
    """
    keywords: List[str] = []
    for rule in kb.get("risk_rules", []):
        if rule.get("risk_type") == risk_type.value:
            keywords = rule.get("trigger_keywords", [])
            break

    best, best_score = "", -1.0
    for kw in keywords:
        start = 0
        while True:
            idx = text.find(kw, start)
            if idx < 0:
                break
            start = idx + 1
            # 窗口起点/终点对齐到句子边界，避免截出半句话
            s = max(0, idx - 60)
            e = min(len(text), idx + len(kw) + 60)
            for sep in ("。", "\n", "；", ";"):
                p = text.rfind(sep, 0, idx)
                if p >= 0:
                    s = max(s, p + 1)
                    break
            for sep in ("。", "\n", "；", ";"):
                p = text.find(sep, idx + len(kw))
                if p >= 0:
                    e = min(e, p + 1)
                    break
            win = text[s:e].strip()
            if len(win) < 12:
                continue
            score = 0.0
            if re.search(r"\d", win):
                score += 2.0
            if re.search(r"亿元|万元|元|%", win):
                score += 1.5
            if re.search(r"占|比例|同比|增长|下降", win):
                score += 1.0
            score += min(len(win), 160) / 160.0
            if score > best_score:
                best_score, best = score, win
    return best


class RiskAnalyzer:
    def __init__(self, client: Optional[LLMClient] = None, mode: str = "auto"):
        self.client = client
        self.mode = mode
        self.last_error = ""
        self.used_llm = False

    # ---------------------------------------------------------- 演示模式
    def analyze_demo(self, facts: ExtractedFacts, cleaned_text: str) -> List[RiskItem]:
        kb = load_kb()
        text = cleaned_text or ""
        items: List[RiskItem] = []

        types = [t for t in facts.event_types if t not in (RiskType.UNIDENTIFIED,)]
        if not types:
            types = [RiskType.UNIDENTIFIED]

        for rt in types:
            if rt == RiskType.UNIDENTIFIED:
                items.append(RiskItem(
                    risk_type=rt, risk_level=RiskLevel.UNKNOWN,
                    reason="未从公告中匹配到六类既定风险事件，无法给出风险等级。",
                    facts=[], inferences=[],
                    uncertainties=["公告内容可能不属于六类既定风险，或表述过于隐晦"],
                    evidence=Evidence(quote="", note="无可用证据"),
                    confidence=0.2, need_human_review=True,
                ))
                continue

            level = _rule_default_level(rt, kb)
            escalate_hit = [k for k in _ESCALATION_RULES.get(rt.value, []) if k in text]
            if escalate_hit and rt != RiskType.EARNINGS_UP:
                level = _LEVEL_UP.get(level, level)

            # 事实：命中关键词对应的原文片段
            quote = _pick_evidence(text, rt, kb)
            facts_list = [f"公告中出现与「{rt.value}」相关的表述（关键词命中："
                          f"{'、'.join(escalate_hit) if escalate_hit else '见证据片段'}）"] if quote else []
            inferences = [f"按知识库判定规则，该事项默认风险等级为「{level.value}」。"]

            uncertainties: List[str] = []
            # 注意：原文出现"资产负债率/净资产"这几个字，不等于披露了具体比例。
            # 必须看到"净资产 … 12.5%"这类数值，才算披露；否则仍要提示信息不足。
            if rt == RiskType.GUARANTEE and not re.search(
                    r"资产负债率[^。；\n]{0,20}\d+(\.\d+)?\s*%", text):
                uncertainties.append("公告未披露被担保方资产负债率与担保余额占净资产比例，定级依据不充分")
            if rt == RiskType.LITIGATION and not re.search(
                    r"净资产[^。；\n]{0,24}\d+(\.\d+)?\s*%", text):
                uncertainties.append("公告未披露涉案金额占最近一期经审计净资产的比例，重大性无法量化")
            if rt == RiskType.SHARE_REDUCTION and not re.search(r"\d+(\.\d+)?\s*%", text):
                uncertainties.append("公告未披露具体减持比例，无法判断是否超过总股本1%")
            if rt == RiskType.EARNINGS_UP and "主营业务" not in text:
                uncertainties.append("公告未说明业绩增长是否来自主营业务，可持续性存疑")

            need_review = bool(uncertainties) or not quote
            conf = 0.55 if quote else 0.25
            if escalate_hit:
                conf = min(0.75, conf + 0.1)
            if need_review:
                conf = max(0.15, conf - 0.15)

            reason_parts = [f"（演示模式规则判定）{rt.value}。"]
            if escalate_hit:
                reason_parts.append(_ESCALATION_NOTE.get(rt.value, ""))
            if not quote:
                reason_parts.append("未能从原文中定位到支撑片段，本条结论未通过证据校验。")
            if uncertainties:
                reason_parts.append("信息不足：" + "；".join(uncertainties))

            items.append(RiskItem(
                risk_type=rt, risk_level=level,
                reason="".join(reason_parts),
                facts=facts_list, inferences=inferences, uncertainties=uncertainties,
                evidence=Evidence(quote=quote, note=f"{rt.value}判定依据"),
                confidence=conf, need_human_review=need_review,
            ))
        return items

    # ---------------------------------------------------------- LLM 模式
    def analyze_llm(self, facts: ExtractedFacts, cleaned_text: str) -> List[RiskItem]:
        if self.client is None or not self.client.available:
            raise LLMError("模型不可用，无法执行 LLM 风险识别")

        template = load_prompt("risk_analysis")
        kb_hits = retrieve(cleaned_text)
        prompt = template.replace("{announcement_text}", cleaned_text[:8000])
        prompt = prompt.replace("{knowledge_context}", format_retrieved(kb_hits))
        prompt = prompt.replace("{extracted_facts}", facts.model_dump_json(ensure_ascii=False))

        messages = [
            {"role": "system", "content": "你是严谨的上市公司公告风险分析助手，只输出符合给定 Schema 的 JSON。"},
            {"role": "user", "content": prompt},
        ]
        raw = self.client.chat(messages, temperature=0.0)
        data = coerce_dict(safe_json_loads(raw))
        self.used_llm = True

        items: List[RiskItem] = []
        for r in data.get("risks", []) or []:
            if not isinstance(r, dict):
                continue
            ev = r.get("evidence", {}) if isinstance(r.get("evidence"), dict) else {}
            items.append(RiskItem(
                risk_type=r.get("risk_type", RiskType.UNIDENTIFIED.value),
                risk_level=r.get("risk_level", RiskLevel.UNKNOWN.value),
                reason=r.get("reason", ""),
                facts=[str(x) for x in (r.get("facts") or [])],
                inferences=[str(x) for x in (r.get("inferences") or [])],
                uncertainties=[str(x) for x in (r.get("uncertainties") or [])],
                evidence=Evidence(quote=ev.get("quote", ""), note=ev.get("note", "")),
                confidence=r.get("confidence", 0.4),
                need_human_review=bool(r.get("need_human_review", False)),
            ))
        return items

    # ---------------------------------------------------------- 统一入口
    def analyze(self, facts: ExtractedFacts, cleaned_text: str) -> List[RiskItem]:
        if self.mode == "demo":
            return self.analyze_demo(facts, cleaned_text)
        if self.mode == "llm":
            try:
                return self.analyze_llm(facts, cleaned_text)
            except LLMError:
                raise
            except ValueError as exc:
                raise LLMError(str(exc)) from exc
        if self.client is not None and self.client.available:
            try:
                return self.analyze_llm(facts, cleaned_text)
            except (LLMError, ValueError) as exc:
                self.last_error = str(exc)
                return self.analyze_demo(facts, cleaned_text)
        return self.analyze_demo(facts, cleaned_text)
