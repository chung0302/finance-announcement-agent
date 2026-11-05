"""
数据契约（Pydantic v2）。

设计原则：
1. 模型输出必须能落到这里的固定 Schema，禁止 Schema 之外的自由格式字段。
2. 一切"没有原文依据"的结论都必须显式携带 evidence，且允许 evidence 为空 ->
   空证据在证据校验阶段会被判定为「未通过校验」，前端不得当作有效依据展示。
3. 未知信息统一写成「未披露」/「信息不足」/「需人工复核」，不允许模型自由发挥。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

UNKNOWN = "未披露"
INSUFFICIENT = "信息不足"
NEED_REVIEW = "需人工复核"


class RiskType(str, Enum):
    """支持的风险类型（与知识库、评测标注共用同一套枚举）。"""

    EARNINGS_UP = "业绩预增或扭亏"
    EARNINGS_DOWN = "业绩预减或亏损"
    SHARE_REDUCTION = "股东或高管减持"
    LITIGATION = "重大诉讼或仲裁"
    GUARANTEE = "对外担保或资金占用"
    AUDIT_REGULATORY = "审计意见异常或其他监管风险"
    OTHER = "其他重大事项"
    UNIDENTIFIED = "未识别"


class RiskLevel(str, Enum):
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    UNKNOWN = "信息不足"


# 风险等级排序，用于取整体最高等级
_LEVEL_ORDER = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.UNKNOWN: 0}


def max_level(levels: List["RiskLevel"]) -> "RiskLevel":
    """取一组风险等级中的最高等级；空列表 -> 信息不足。"""
    if not levels:
        return RiskLevel.UNKNOWN
    return max(levels, key=lambda x: _LEVEL_ORDER.get(x, 0))


class Evidence(BaseModel):
    """一条原文证据。quote 必须是公告中的连续片段（清洗后原文可匹配）。"""

    quote: str = Field(default="", description="原文连续片段，必须与公告原文一致")
    note: str = Field(default="", description="这条证据支撑什么结论")

    # 由证据校验阶段回填，模型不应输出
    matched: bool = Field(default=False, description="是否与清洗后原文匹配成功")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="归一化后的匹配相似度")
    match_method: str = Field(default="未校验", description="精确包含/模糊匹配/未匹配")

    @field_validator("quote", "note", mode="before")
    @classmethod
    def _to_str(cls, v):
        if v is None:
            return ""
        return str(v).strip()


class KeyMetric(BaseModel):
    """关键指标或金额。value 保留原文写法，避免二次换算引入错误。"""

    name: str = Field(default=UNKNOWN, description="指标名称，如：归属于上市公司股东的净利润")
    value: str = Field(default=UNKNOWN, description="数值原文，如：1.2亿元、同比下降35%")
    numeric_value: Optional[float] = Field(default=None, description="可解析为数字时填写，否则为 None")
    unit: str = Field(default="", description="单位：元/万元/亿元/%等")
    yoy_change: str = Field(default=UNKNOWN, description="同比或环比变化，没有则写未披露")
    evidence: Evidence = Field(default_factory=Evidence)

    @field_validator("name", "value", "unit", "yoy_change", mode="before")
    @classmethod
    def _blank_to_unknown(cls, v):
        if v is None or str(v).strip() == "":
            return UNKNOWN
        return str(v).strip()

    @field_validator("name", "value", "unit", "yoy_change", mode="after")
    @classmethod
    def _fix_unknown_for_unit(cls, v, info):
        # unit 允许为空串（无单位），name/value/yoy_change 不允许
        if info.field_name == "unit":
            return "" if v == UNKNOWN else v
        return v


class ExtractedFacts(BaseModel):
    """信息抽取阶段的固定 Schema 输出。"""

    company_name: str = Field(default=UNKNOWN)
    announcement_title: str = Field(default=UNKNOWN)
    announcement_date: str = Field(default=UNKNOWN, description="YYYY-MM-DD；无法识别写未披露")
    stock_code: str = Field(default=UNKNOWN)
    event_types: List[RiskType] = Field(default_factory=list)
    metrics: List[KeyMetric] = Field(default_factory=list)
    summary_sentence: str = Field(default="", description="一句话概括公告核心事项")
    missing_fields: List[str] = Field(default_factory=list, description="公告中没有写明的字段")

    @field_validator("company_name", "announcement_title", "announcement_date",
                     "stock_code", "summary_sentence", mode="before")
    @classmethod
    def _to_text(cls, v):
        if v is None:
            return UNKNOWN
        s = str(v).strip()
        return s if s else UNKNOWN

    @field_validator("event_types", mode="before")
    @classmethod
    def _norm_types(cls, v):
        if v is None:
            return []
        if isinstance(v, (str, RiskType)):
            v = [v]
        out = []
        for item in v:
            # 已经是枚举实例（规则抽取路径）时直接采用，避免 str(枚举) 退化成 "RiskType.XXX"
            if isinstance(item, RiskType):
                out.append(item)
                continue
            s = str(item).strip()
            for rt in RiskType:
                if s == rt.value or s == rt.name:
                    out.append(rt)
                    break
            else:
                # 模型自由输出的类型映射到"其他重大事项"，避免污染枚举
                if s and s not in (UNKNOWN, INSUFFICIENT):
                    out.append(RiskType.OTHER)
        # 去重保序
        seen, uniq = set(), []
        for x in out:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return uniq


class RiskItem(BaseModel):
    """风险识别阶段的一条风险结论。"""

    risk_type: RiskType = Field(default=RiskType.UNIDENTIFIED)
    risk_level: RiskLevel = Field(default=RiskLevel.UNKNOWN)
    reason: str = Field(default="", description="风险原因解释")
    # 显式区分：事实（原文直接写明）/ 推断（基于事实的判断）/ 不确定性
    facts: List[str] = Field(default_factory=list, description="原文直接写明的事实")
    inferences: List[str] = Field(default_factory=list, description="基于事实的推断，非原文直述")
    uncertainties: List[str] = Field(default_factory=list, description="无法确认或可能导致误判的点")
    evidence: Evidence = Field(default_factory=Evidence)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    need_human_review: bool = Field(default=False)

    @field_validator("risk_level", mode="before")
    @classmethod
    def _norm_level(cls, v):
        # 已是枚举实例（规则判定路径）时直接采用，避免 str(枚举) 退化成 "RiskLevel.LOW"
        if isinstance(v, RiskLevel):
            return v
        if v is None:
            return RiskLevel.UNKNOWN
        s = str(v).strip()
        for lv in RiskLevel:
            if s == lv.value or s == lv.name:
                return lv
        return RiskLevel.UNKNOWN

    @field_validator("risk_type", mode="before")
    @classmethod
    def _norm_type(cls, v):
        if isinstance(v, RiskType):
            return v
        if v is None:
            return RiskType.UNIDENTIFIED
        s = str(v).strip()
        for rt in RiskType:
            if s == rt.value or s == rt.name:
                return rt
        return RiskType.OTHER if s else RiskType.UNIDENTIFIED

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))


class SelfCheckIssue(BaseModel):
    """二次自检发现的问题。"""

    field_name: str = Field(default="")
    issue: str = Field(default="")
    action: str = Field(default="保留", description="保留/降级/删除/标记复核")
    severity: str = Field(default="提示", description="提示/严重")


class AnalysisResult(BaseModel):
    """最终交付给前端的结构化结果。"""

    # 元信息
    mode: str = Field(default="demo", description="demo=演示模式, llm=真实模型模式")
    model_name: str = Field(default="", description="实际使用的模型名；演示模式为空")
    input_chars: int = Field(default=0)
    warnings: List[str] = Field(default_factory=list)

    # 结构化抽取
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)

    # 风险识别
    risks: List[RiskItem] = Field(default_factory=list)
    overall_risk_level: RiskLevel = Field(default=RiskLevel.UNKNOWN)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # 证据与缺失信息
    evidence_verified: List[Evidence] = Field(default_factory=list)
    evidence_unverified: List[Evidence] = Field(default_factory=list)
    missing_info: List[str] = Field(default_factory=list)

    # 自检
    self_check_issues: List[SelfCheckIssue] = Field(default_factory=list)
    self_check_passed: bool = Field(default=False)

    # 时间统计
    elapsed_seconds: float = Field(default=0.0)
    llm_calls: int = Field(default=0)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def to_markdown(self) -> str:
        """导出为 Markdown 报告（前端下载用）。"""
        lines: List[str] = []
        mode_cn = "演示模式（固定样例与规则，非真实模型输出）" if self.mode == "demo" else f"真实模型模式（{self.model_name or '未知模型'}）"
        lines.append("# 上市公司公告风险识别与解释报告")
        lines.append("")
        lines.append(f"> 运行模式：{mode_cn}")
        lines.append("")
        lines.append("## 一句话结论")
        lines.append("")
        lines.append(self.facts.summary_sentence or UNKNOWN)
        lines.append("")
        lines.append("## 基本信息")
        lines.append("")
        lines.append("| 字段 | 值 |")
        lines.append("| --- | --- |")
        lines.append(f"| 公司名称 | {self.facts.company_name} |")
        lines.append(f"| 公告标题 | {self.facts.announcement_title} |")
        lines.append(f"| 公告日期 | {self.facts.announcement_date} |")
        lines.append(f"| 证券代码 | {self.facts.stock_code} |")
        lines.append(f"| 事件类型 | {'、'.join(t.value for t in self.facts.event_types) or UNKNOWN} |")
        lines.append(f"| 整体风险等级 | {self.overall_risk_level.value} |")
        lines.append(f"| 整体置信度 | {self.overall_confidence:.2f} |")
        lines.append("")
        lines.append("## 关键指标")
        lines.append("")
        if self.facts.metrics:
            lines.append("| 指标 | 数值 | 同比变化 | 证据校验 |")
            lines.append("| --- | --- | --- | --- |")
            for m in self.facts.metrics:
                st = "已验证" if m.evidence.matched else "未通过校验"
                lines.append(f"| {m.name} | {m.value} | {m.yoy_change} | {st} |")
        else:
            lines.append(UNKNOWN)
        lines.append("")
        lines.append("## 风险识别")
        lines.append("")
        if self.risks:
            for i, r in enumerate(self.risks, 1):
                lines.append(f"### {i}. {r.risk_type.value}（风险等级：{r.risk_level.value}）")
                lines.append("")
                lines.append(f"- 风险原因：{r.reason or UNKNOWN}")
                lines.append(f"- 置信度：{r.confidence:.2f}")
                if r.facts:
                    lines.append("- 原文事实：" + "；".join(r.facts))
                if r.inferences:
                    lines.append("- 推断：" + "；".join(r.inferences))
                if r.uncertainties:
                    lines.append("- 不确定性：" + "；".join(r.uncertainties))
                if r.evidence.quote:
                    st = "已验证证据" if r.evidence.matched else "未通过校验"
                    lines.append(f"- 证据（{st}，相似度 {r.evidence.score:.2f}）：")
                    lines.append(f"  > {r.evidence.quote}")
                else:
                    lines.append("- 证据：缺失，该结论未通过证据校验")
                if r.need_human_review:
                    lines.append("- 标记：需人工复核")
                lines.append("")
        else:
            lines.append("未识别出明确风险类型。")
            lines.append("")
        lines.append("## 证据清单")
        lines.append("")
        lines.append(f"已验证证据 {len(self.evidence_verified)} 条，未通过校验 {len(self.evidence_unverified)} 条。")
        lines.append("")
        for e in self.evidence_verified:
            lines.append(f"- [已验证] {e.quote}  —— {e.note}")
        for e in self.evidence_unverified:
            lines.append(f"- [未通过校验] {e.quote or '（空证据）'}  —— {e.note}")
        lines.append("")
        lines.append("## 信息不足提示")
        lines.append("")
        if self.missing_info:
            for m in self.missing_info:
                lines.append(f"- {m}")
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("## 二次自检")
        lines.append("")
        lines.append(f"自检结论：{'通过' if self.self_check_passed else '发现问题，已按规则处理'}")
        for it in self.self_check_issues:
            lines.append(f"- [{it.severity}] {it.field_name}：{it.issue} -> {it.action}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("免责声明：本工具仅做财经文本的信息提取与风险提示，不预测股票价格，不构成买入、卖出或持有建议。")
        return "\n".join(lines)
