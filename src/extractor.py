"""
信息抽取模块（流水线第 2 步）。

两条路径：
- LLM 模式：用 prompts/extraction.md + 固定 JSON Schema 调用模型，输出经 safe_json_loads 修复后校验。
- 演示模式（无密钥 / 调用失败 / 显式指定）：用**确定性规则**抽取，结果标注为演示模式，
  绝不冒充模型输出。

抽取结果中的每一条关键数字都携带 evidence（截取原文片段），
后续由 evidence_checker 统一校验。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Optional

from .config import MAX_INPUT_CHARS
from .evidence_checker import find_snippet
from .json_utils import coerce_dict, safe_json_loads
from .knowledge_base import load_kb, retrieve
from .llm_client import LLMClient, LLMError
from .prompts_loader import load_prompt
from .schemas import INSUFFICIENT, UNKNOWN, Evidence, ExtractedFacts, KeyMetric, RiskType

# ------------------------------------------------------------------ 规则库
_COMPANY_PATTERNS = [
    r"公司全称[：:\s]*([^\s，,；;。]{2,30})",
    # 只允许中文：页眉与公司名被合并成一行时（"公告编号：2026-027明远电子股份有限公司"），
    # 若允许任意字符会把"公告编号：2026-027"一起吞进公司名。
    r"([\u4e00-\u9fa5]{2,20}?(?:股份|集团|科技|新材料)?有限公司)",
    r"证券简称[：:\s]*([^\s，,；;。]{2,12})",
    r"本公司(?:及董事会全体成员)?(?:名称)?[为是：:\s]*([^\s，,；;。]{2,20}?有限公司)",
]
_CODE_PATTERNS = [
    r"证券代码[：:\s]*([0-9]{6})",
    r"股票代码[：:\s]*([0-9]{6})",
    r"（([0-9]{6})\s*[,，]\s*[A-Za-z]{2,5}）",
]
_DATE_PATTERNS = [
    r"([0-9]{4})\s*年\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日",
    r"([0-9]{4})[-/]([0-9]{1,2})[-/]([0-9]{1,2})",
]
# 标题：排除页眉行（含"证券代码/公告编号"），避免把页眉误当标题
_TITLE_PATTERNS = [
    r"(?<!证券代码)(关于[^\n]{4,60}?(?:公告|报告|说明|提示性公告))",
    r"([^\n]{4,60}?(?:年度业绩预告|半年度业绩预告|季度业绩预告|业绩快报|提示性公告|公告))",
]
# 标题行黑名单：命中则跳过
_TITLE_BLACKLIST = ("证券代码", "公告编号", "证券简称")
_MONEY_RE = re.compile(r"(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元|%|股)")
_YOY_RE = re.compile(
    r"(同比|较上年同期|比上年同期)(?:增长|上升|增加|下降|减少|降低|变动)?"
    r"[^0-9]{0,12}(-?[0-9]+(?:\.[0-9]+)?)\s*%"
)
# 百分比必须出现在这类语境里才被认为是有效指标，避免把无关数字当金额
_PCT_CONTEXT_RE = re.compile(r"同比|增长|上升|下降|减少|提高|降低|持股|减持|占|比例|率")
# 业绩预告表格里"本期数 上年同期数"成对出现（中间只允许"盈利："这少量字符）。
# 命中时以第一个数为本期值、第二个数为对比基数，避免把上年同期数当成本期指标。
_TABLE_PAIR_RE = re.compile(
    r"(?:盈利[：:]?)?\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)"
    r"[^，,、；;。\n]{0,12}?"
    r"(?:盈利[：:]?)?\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)"
)
_METRIC_NAME_HINT = [
    (r"归属于上市公司股东的净利润|归属于母公司所有者的净利润|归母净利润", "归属于上市公司股东的净利润"),
    (r"扣除非经常性损益(?:后)?的?净利润|扣非净利润", "扣除非经常性损益后的净利润"),
    (r"营业收入|销售收入", "营业收入"),
    (r"净利润", "净利润"),
    (r"担保金额|担保额度|提供担保的金额", "担保金额"),
    (r"涉案金额|诉讼金额|标的金额", "涉案金额"),
    # 股数（减持公告的核心事实，不能只抽金额和百分比）
    (r"持股数量|持有公司?股份|持有股份", "持股数量"),
    (r"减持(?:股份)?数量|减持.{0,6}?不超过|拟减持.{0,6}?股", "拟减持数量"),
    (r"减持(?:股份)?(?:数量|比例)|拟减持", "拟减持股份比例"),
]


def _first(patterns: List[str], text: str, group: int = 1) -> str:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(group).strip()
    return UNKNOWN


def _extract_title(text: str) -> str:
    """逐行找标题：跳过页眉行与过长行。"""
    for line in text.splitlines():
        s = line.strip()
        if not s or len(s) < 4 or len(s) > 60:
            continue
        if any(b in s for b in _TITLE_BLACKLIST):
            continue
        for p in _TITLE_PATTERNS:
            m = re.search(p, s)
            if m:
                return m.group(1).strip()
    return UNKNOWN


def _extract_date(text: str) -> str:
    """
    抽取公告日期。

    公告里往往出现多个日期（报告期起止、承诺到期日、减持窗口等），
    落款日期通常在文末，因此取**最后一个**合法日期。
    """
    found: List[tuple] = []
    for p in _DATE_PATTERNS:
        for m in re.finditer(p, text):
            try:
                y = int(m.group(1))
                mo = int(m.group(2))
                d = int(m.group(3))
            except (TypeError, ValueError):
                continue
            if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                found.append((m.start(), f"{y}-{mo:02d}-{d:02d}"))
    if not found:
        return UNKNOWN
    found.sort()
    return found[-1][1]


def _detect_event_types(text: str) -> List[RiskType]:
    """按知识库触发词做规则化事件类型识别（演示模式使用）。"""
    kb = load_kb()
    hits: List[RiskType] = []
    for rule in kb.get("risk_rules", []):
        name = rule.get("risk_type", "")
        for rt in RiskType:
            if rt.value == name:
                if any(k in text for k in rule.get("trigger_keywords", [])):
                    hits.append(rt)
                break
    return hits


def _percent_name(ctx_before: str) -> str:
    """
    百分比类指标的名称推断。

    只看数字**之前**的文本，并按"离数字最近的那个动词"判定：
    减持公告里常同时出现"目前持有…38.00%"与"拟减持…1.50%"，
    若笼统看整段上下文，会把减持比例误判成持股比例。
    """
    i_reduce = max(ctx_before.rfind("减持"), ctx_before.rfind("转让"))
    # 注意："减持股份"里会跨词出现"持股"二字，不能直接用 rfind("持股")，
    # 只认"持有 / 持股比例 / 持股数量"这几种真实表述。
    hold_hits = [m.start() for m in re.finditer(r"持有|持股比例|持股数量", ctx_before)]
    i_hold = max(hold_hits) if hold_hits else -1
    if i_reduce >= 0 and i_reduce > i_hold:
        return "减持比例"
    if i_hold >= 0:
        return "持股比例"
    if "占" in ctx_before or "比例" in ctx_before:
        return "占总股本比例"
    return "变化率"


def _clean_name_seg(seg: str) -> str:
    """从「项目 本报告期 上年同期 归属于上市公司股东的净利润」这类片段里取出科目名。"""
    for pat, label in _METRIC_NAME_HINT:
        if re.search(pat, seg):
            return label
    seg = re.sub(r"(盈利|亏损)[：:]?", "", seg)
    for noise in ("本报告期", "上年同期", "项目", "金额", "（", "）", "(", ")"):
        seg = seg.replace(noise, "")
    seg = seg.strip(" ：:，,、;；。 \n")
    return seg[-20:] if len(seg) > 20 else seg


def _line_quote(text: str, pos: int, limit: int = 200) -> str:
    """取包含该位置的整句作为证据片段；过长时以目标位置为中心截取，确保片段含该数字。"""
    s = max(text.rfind("。", 0, pos) + 1, text.rfind("\n", 0, pos) + 1)
    e = text.find("。", pos)
    e = len(text) if e < 0 else e + 1
    seg = text[s:e].strip()
    if len(seg) <= limit:
        return seg
    off = max(0, pos - s)
    lo = max(0, off - limit // 2)
    hi = min(len(seg), lo + limit)
    return seg[lo:hi]


def _extract_metrics(text: str) -> List[KeyMetric]:
    """
    规则化抽取关键金额 / 变化率。

    两步走：
    ① 先识别"本期值 上年同期值"成对出现的表格行，只取本期值，
       否则会把上年同期数（如营业收入 12.40 亿元）误当成当期数据；
    ② 再处理其余孤立数字：向左取上下文推断指标名，并把该句作为证据片段。
    抽不到就返回空列表 —— 由上层写"未披露"，不猜。
    """
    metrics: List[KeyMetric] = []
    seen = set()
    covered: List[tuple] = []

    # ---- ① 表格成对数值
    last_end = 0
    for m in _TABLE_PAIR_RE.finditer(text):
        seg = text[last_end:m.start()]
        name = _clean_name_seg(seg) or UNKNOWN
        value = f"{m.group(1)}{m.group(2)}"
        key = (name, value)
        if key not in seen:
            seen.add(key)
            metrics.append(KeyMetric(
                name=name, value=value, unit=m.group(2),
                yoy_change=_detect_yoy(text, m.start()),
                evidence=Evidence(
                    quote=_line_quote(text, m.start()),
                    note=f"表格抽取（只取本期值，同期对比基数已排除）：{name}={value}",
                ),
            ))
        covered.append((m.start(), m.end()))
        last_end = m.end()

    # ---- ② 其余孤立数值
    for m in _MONEY_RE.finditer(text):
        if any(s <= m.start() < e for s, e in covered):
            continue
        unit = m.group(2)
        value = f"{m.group(1)}{unit}"
        before = text[max(0, m.start() - 40):m.start()]
        ctx = text[max(0, m.start() - 40):m.end() + 10]

        if unit == "%":
            if not _PCT_CONTEXT_RE.search(ctx):
                continue  # 无语境的百分比（如章节编号）不作为指标
            if re.search(r"(增长|上升|下降|减少|提高|降低|同比|较上年|比上年)[^0-9%]{0,8}$", before):
                continue  # 这是同比变化率，已由 yoy_change 字段承载，不重复算作独立指标
            name = _percent_name(before)
        else:
            if re.search(r"(上年同期|上年|去年同期|上年度)[^0-9]{0,6}$", before):
                continue  # 这是对比基数（上年同期数），不是本期指标
            name = UNKNOWN
            for pat, label in _METRIC_NAME_HINT:
                if re.search(pat, ctx):
                    name = label
                    break

        key = (name, value)
        if key in seen:
            continue
        seen.add(key)
        metrics.append(KeyMetric(
            name=name, value=value, unit=unit,
            yoy_change=_detect_yoy(text, m.start()),
            evidence=Evidence(quote=_line_quote(text, m.start()),
                              note=f"抽取指标：{name}={value}"),
        ))
    return metrics[:12]


def _detect_yoy(text: str, pos: int) -> str:
    """
    在数字附近查找同比变化描述。

    只向前看 20 字、向后看 90 字，并优先取数字**之后**的变化率：
    同比通常紧跟在本期数值后面，往前看得太远会把上一个科目的同比套到当前数值上。
    例如"净利润 2200 万元，上年同期 6800 万元，同比下降 67.65%；营业收入 4.30 亿元"，
    营业收入不应继承净利润的同比。
    """
    seg_start = max(0, pos - 30)
    seg_end = min(len(text), pos + 90)
    best, best_key = UNKNOWN, (10 ** 9, 0)
    for m in _YOY_RE.finditer(text, seg_start, seg_end):
        start, end = m.start(), m.end()
        if start < pos:
            gap = text[end:pos]
            # 中间隔着谓语或另一个分句（"同比下降67.65%；预计营业收入为"），
            # 说明这是前一个数字的同比，不能套到当前数值上。
            if len(gap) > 6 or re.search(r"[为达预实；;。]", gap):
                continue
            dist = pos - start
        else:
            dist = start - pos
        if (dist, dist) < best_key:
            best_key, best = (dist, dist), f"{m.group(1)}{m.group(2)}%"
    return best


def _num(text: str) -> float:
    """从「约+75.00%」这类字符串中取出数值，取不到返回 0。"""
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def _truncate(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n……（原文过长，已截断至前 %d 字）" % limit


# ------------------------------------------------------------------ 抽取器
class Extractor:
    def __init__(self, client: Optional[LLMClient] = None, mode: str = "auto"):
        """
        :param client: LLM 客户端；为 None 时只能走演示模式
        :param mode: auto（有密钥用 LLM）/ llm（强制）/ demo（强制规则）
        """
        self.client = client
        self.mode = mode
        self.last_raw_output = ""
        self.used_llm = False

    # ---------------------------------------------------------- 演示模式
    def extract_demo(self, cleaned_text: str) -> ExtractedFacts:
        """确定性规则抽取（演示模式）。"""
        text = cleaned_text or ""
        company = _first(_COMPANY_PATTERNS, text[:600]) or _first(_COMPANY_PATTERNS, text)
        code = _first(_CODE_PATTERNS, text[:800]) or _first(_CODE_PATTERNS, text)
        title = _extract_title(text)
        date = _extract_date(text)

        events = _detect_event_types(text)
        metrics = _extract_metrics(text)

        summary = self._demo_summary(text, events, metrics, company)

        facts = ExtractedFacts(
            company_name=company, announcement_title=title,
            announcement_date=date, stock_code=code,
            event_types=events or [RiskType.UNIDENTIFIED],
            metrics=metrics, summary_sentence=summary,
        )
        facts.missing_fields = _missing_fields(facts)
        return facts

    @staticmethod
    def _pick_key_metrics(ev_names: List[str], metrics: List[KeyMetric], limit: int = 2) -> List[KeyMetric]:
        """
        从全部指标中挑出「最值得写进一句话结论」的几个。

        不能直接用 metrics[0]：第一个出现的数字常常是背景信息（如"总股本 38.00%"），
        而不是本次公告的重点（如"拟减持不超过 1.50%"）。这里按事件类型加权排序。
        """
        if not metrics:
            return []

        ev_text = "".join(ev_names)

        def score(m: KeyMetric) -> float:
            s = 0.0
            if "减持" in ev_text and m.name == "减持比例":
                s += 100          # 减持公告的核心数字
            if "营业收入" in m.name or "净利润" in m.name:
                s += 60           # 业绩类公告的核心科目
            if m.yoy_change not in ("", UNKNOWN):
                s += 40 + min(abs(_num(m.yoy_change)), 100)  # 有同比变化说明是本期重点
            if m.name == UNKNOWN:
                s -= 30           # 指标名不明，优先度最低
            if "数量" in m.name:
                s -= 15           # "152,000,000 股"不如"38.00%"直观，结论里让位于比例
            return s

        def group(name: str) -> str:
            """把同一类科目归为一组，避免一句话里同时写"归母净利润"和"扣非净利润"。"""
            if "净利润" in name or "每股收益" in name or "净资产收益率" in name:
                return "profit"
            if "营业收入" in name:
                return "revenue"
            if "减持" in name:
                return "reduce"
            if "持股" in name:
                return "hold"
            return name

        ranked = sorted(metrics, key=lambda m: (score(m), _num(m.value)), reverse=True)
        picked: List[KeyMetric] = []
        used_groups = set()
        for m in ranked:
            g = group(m.name)
            if g in used_groups and m.name != UNKNOWN:
                continue
            used_groups.add(g)
            picked.append(m)
            if len(picked) >= limit:
                break
        return picked

    @staticmethod
    def _demo_summary(text: str, events: List[RiskType], metrics: List[KeyMetric],
                      company: str = "") -> str:
        if not text.strip():
            return "输入为空，未抽取到任何信息。"

        tag = "（演示模式规则抽取，非模型输出）"
        ev_names = [e.value for e in events if e is not RiskType.UNIDENTIFIED]
        ev = "、".join(ev_names) if ev_names else "未识别到既定风险类型"

        picked = Extractor._pick_key_metrics(ev_names, metrics)
        parts = []
        for m in picked:
            if m.yoy_change in ("", UNKNOWN):
                yoy = ""
            elif "同比" in m.yoy_change or "比上年" in m.yoy_change:
                yoy = f"（{m.yoy_change}）"          # 原文已含"同比/比上年"，不重复加前缀
            else:
                yoy = f"（同比{m.yoy_change}）"
            if m.name == UNKNOWN:
                parts.append(f"涉及金额{m.value}{yoy}")
            else:
                parts.append(f"{m.name}{m.value}{yoy}")
        nums = "；".join(parts) if parts else "未披露具体金额"

        who = f"{company}" if company and company != UNKNOWN else "该公司"
        return f"{who}公告涉及{ev}：{nums}。{tag}"

    # ---------------------------------------------------------- LLM 模式
    def extract_llm(self, cleaned_text: str) -> ExtractedFacts:
        """用 prompts/extraction.md 调用模型抽取。"""
        if self.client is None or not self.client.available:
            raise LLMError("模型不可用，无法执行 LLM 抽取")

        template = load_prompt("extraction")
        kb_hits = retrieve(cleaned_text)
        from .knowledge_base import format_retrieved  # 局部导入
        prompt = template.replace("{announcement_text}", _truncate(cleaned_text))
        prompt = prompt.replace("{knowledge_context}", format_retrieved(kb_hits))

        messages = [
            {"role": "system", "content": "你是严谨的中文金融文本结构化抽取引擎，只输出符合给定 Schema 的 JSON。"},
            {"role": "user", "content": prompt},
        ]
        raw = self.client.chat(messages, temperature=0.0)
        self.last_raw_output = raw
        data = coerce_dict(safe_json_loads(raw))

        metrics = []
        for m in data.get("metrics", []) or []:
            if not isinstance(m, dict):
                continue
            ev = m.get("evidence", {}) if isinstance(m.get("evidence"), dict) else {}
            metrics.append(KeyMetric(
                name=m.get("name", UNKNOWN),
                value=m.get("value", UNKNOWN),
                unit=m.get("unit", ""),
                yoy_change=m.get("yoy_change", UNKNOWN),
                evidence=Evidence(quote=ev.get("quote", ""), note=ev.get("note", "")),
            ))

        facts = ExtractedFacts(
            company_name=data.get("company_name", UNKNOWN),
            announcement_title=data.get("announcement_title", UNKNOWN),
            announcement_date=data.get("announcement_date", UNKNOWN),
            stock_code=data.get("stock_code", UNKNOWN),
            event_types=data.get("event_types", []) or [RiskType.UNIDENTIFIED],
            metrics=metrics,
            summary_sentence=data.get("summary_sentence", UNKNOWN),
            missing_fields=data.get("missing_fields", []) or [],
        )
        if not facts.missing_fields:
            facts.missing_fields = _missing_fields(facts)
        self.used_llm = True
        return facts

    # ---------------------------------------------------------- 统一入口
    def extract(self, cleaned_text: str) -> ExtractedFacts:
        if self.mode == "demo":
            return self.extract_demo(cleaned_text)
        if self.mode == "llm":
            # 统一转成 LLMError 抛出，由 Pipeline 决定降级；不把解析异常泄漏到界面
            try:
                return self.extract_llm(cleaned_text)
            except LLMError:
                raise
            except ValueError as exc:
                raise LLMError(str(exc)) from exc
        # auto
        if self.client is not None and self.client.available:
            try:
                return self.extract_llm(cleaned_text)
            except (LLMError, ValueError) as exc:
                # 降级：规则抽取，由 pipeline 记录告警
                self.last_error = str(exc)
                facts = self.extract_demo(cleaned_text)
                facts.summary_sentence += f"（模型抽取失败已降级为规则抽取：{exc}）"
                return facts
        return self.extract_demo(cleaned_text)


def _missing_fields(facts: ExtractedFacts) -> List[str]:
    """列出公告中没有写明的字段，供前端"信息不足提示"使用。"""
    miss: List[str] = []
    zh = {
        "company_name": "公司名称", "announcement_title": "公告标题",
        "announcement_date": "公告日期", "stock_code": "证券代码",
    }
    for k, label in zh.items():
        v = getattr(facts, k, UNKNOWN)
        if v in (UNKNOWN, INSUFFICIENT, ""):
            miss.append(f"{label}未披露")
    if not facts.metrics:
        miss.append("关键金额或指标未披露")
    if not facts.event_types or facts.event_types == [RiskType.UNIDENTIFIED]:
        miss.append("事件类型未能识别，需人工复核")
    return miss
