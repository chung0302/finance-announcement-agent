"""
本地小型知识库（流水线第 2 步：知识检索）。

内容：
1. 六类风险的定义与判定说明；
2. 常见金融术语解释；
3. 至少 2 个"正确示例"（含应有的抽取结果与证据）。

重要边界：
- 知识库只提供"判定参考"，**不能替代公告原文证据**。
- 检索结果会作为提示词的上下文送给模型，但任何结论仍必须回原文取证据。
- 知识库条目本身携带 source 字段，标明依据来源（规则/法规常识/示例），
  避免把"常识"伪装成"公告事实"。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .config import KB_DIR

# ---------------------------------------------------------------- 风险类型定义
RISK_RULES: List[Dict[str, Any]] = [
    {
        "risk_type": "业绩预增或扭亏",
        "definition": "公司在业绩预告/快报/定期报告中预计净利润同比增长，或由亏损转为盈利。",
        "trigger_keywords": ["业绩预增", "预增", "扭亏为盈", "扭亏", "同比增长", "净利润增长", "预计盈利"],
        "judge": "同比增幅越大、是否来源于主营业务（而非出售资产/政府补助）决定利好含金量；"
                 "若增长主要来自非经常性损益，需要在推断中说明，并提示可持续性存疑。",
        "default_level": "低",
        "level_rules": {
            "高": "增幅超过100%且含非经常性损益大额贡献，或扭亏主要依靠资产处置",
            "中": "增幅30%~100%，且未说明是否来自主营业务",
            "低": "增幅明确且来自主营业务",
        },
        "source": "规则（依据《上市公司信息披露管理办法》业绩预告相关披露要求的通行理解）",
    },
    {
        "risk_type": "业绩预减或亏损",
        "definition": "公司预计净利润同比下降、首次亏损或亏损扩大。",
        "trigger_keywords": ["业绩预减", "预减", "亏损", "同比下降", "净利润下降", "首亏", "续亏", "由盈转亏"],
        "judge": "关注下降幅度、是否首次亏损、是否触发退市风险警示（如营收低于1亿元且净利润为负）。"
                 "首次亏损或大幅亏损通常对基本面影响更显著。",
        "default_level": "中",
        "level_rules": {
            "高": "首次亏损、亏损扩大幅度超过100%，或可能触及退市风险警示条件",
            "中": "同比下降30%以上但未触及退市指标",
            "低": "小幅下降且公司给出明确改善措施",
        },
        "source": "规则",
    },
    {
        "risk_type": "股东或高管减持",
        "definition": "控股股东、持股5%以上股东或董监高披露减持计划/减持进展/减持完成。",
        "trigger_keywords": ["减持", "拟减持", "减持计划", "减持进展", "大宗交易", "集中竞价", "被动稀释"],
        "judge": "关注减持主体（控股股东/高管 vs 小股东）、减持比例（占总股本比例）、减持方式与期限。"
                 "控股股东或高管大额减持通常被市场视作负面信号。",
        "default_level": "中",
        "level_rules": {
            "高": "控股股东/实控人减持，或单次减持比例达到或超过总股本1%",
            "中": "持股5%以上股东或高管减持，比例低于1%",
            "低": "小额减持或被动稀释，且明确说明不影响控制权",
        },
        "source": "规则（依据减持新规下对大股东、董监高减持披露的通行理解）",
    },
    {
        "risk_type": "重大诉讼或仲裁",
        "definition": "公司或其子公司涉及金额重大的诉讼、仲裁、被执行或账户冻结。",
        "trigger_keywords": ["诉讼", "仲裁", "起诉", "被起诉", "判决", "裁定", "被执行", "冻结", "涉案金额", "被告"],
        "judge": "关注涉案金额占最近一期经审计净资产的比例（常见重大性判断参考为10%）、"
                 "公司是原告还是被告、是否计提预计负债、判决是否生效。",
        "default_level": "中",
        "level_rules": {
            "高": "涉案金额占净资产10%以上，或公司为主要被告且已判决承担大额赔付",
            "中": "涉案金额重大但占净资产比例未披露，或一审尚未判决",
            "低": "公司作为原告主张权利，或涉案金额较小",
        },
        "source": "规则（依据交易所股票上市规则关于重大诉讼披露标准的通行理解）",
    },
    {
        "risk_type": "对外担保或资金占用",
        "definition": "公司为外部对象提供担保（尤其是对资产负债率高的对象担保），或存在控股股东及关联方非经营性占用资金。",
        "trigger_keywords": ["对外担保", "担保", "连带责任", "反担保", "资金占用", "非经营性占用", "关联方", "资金拆借"],
        "judge": "关注担保余额占净资产比例、被担保方是否为关联方、被担保方资产负债率、"
                 "是否逾期。资金占用属监管重点关注事项，性质较担保更严重。",
        "default_level": "中",
        "level_rules": {
            "高": "存在控股股东资金占用，或为资产负债率超过70%的对象担保，或担保已逾期",
            "中": "担保余额占净资产比例较高但未逾期，且被担保方经营正常",
            "低": "对合并报表范围内子公司担保，且风险可控",
        },
        "source": "规则（依据证监会关于上市公司对外担保与资金往来监管要求的通行理解）",
    },
    {
        "risk_type": "审计意见异常或其他监管风险",
        "definition": "年报被出具非标准无保留审计意见，或公司收到监管问询函、警示函、立案调查、处罚。",
        "trigger_keywords": ["保留意见", "无法表示意见", "带强调事项段", "非标准审计意见", "问询函",
                             "关注函", "警示函", "立案", "调查", "处罚", "监管措施", "整改"],
        "judge": "非标准审计意见直接反映财报可信度问题；立案调查性质最严重。"
                 "需区分'已结案'与'进行中'。",
        "default_level": "高",
        "level_rules": {
            "高": "无法表示意见/否定意见，或被立案调查、被行政处罚",
            "中": "保留意见、带强调事项段无保留意见，或收到问询函尚未回复",
            "低": "仅为监管关注且公司已明确回复并整改完成",
        },
        "source": "规则",
    },
]

# ---------------------------------------------------------------- 术语表
TERMS: List[Dict[str, str]] = [
    {"term": "业绩预告", "definition": "上市公司在正式财报披露前，对报告期经营业绩的预先估计，具有不确定性。"},
    {"term": "业绩快报", "definition": "比业绩预告更接近正式数据的经营情况简要报告，通常未经审计。"},
    {"term": "归属于上市公司股东的净利润", "definition": "扣除少数股东损益后的净利润，是衡量公司盈利能力的核心指标，简称'归母净利润'。"},
    {"term": "扣除非经常性损益后的净利润", "definition": "剔除资产处置、政府补助等一次性收益后的净利润，更能反映主营业务盈利。"},
    {"term": "同比（YoY）", "definition": "与上年同期相比的变化，用于消除季节性影响。"},
    {"term": "非经常性损益", "definition": "与主营业务无直接关系的一次性损益，如出售资产收益、政府补助、公允价值变动。"},
    {"term": "退市风险警示（*ST）", "definition": "交易所对触及退市指标的公司实施的特别标识，提示投资者注意风险。"},
    {"term": "集中竞价", "definition": "通过证券交易所交易系统进行的竞价交易，是常见的股份减持方式之一。"},
    {"term": "大宗交易", "definition": "达到规定最低限额的证券单笔买卖申报，买卖双方协商一致并经交易所确认成交。"},
    {"term": "预计负债", "definition": "因诉讼、担保等或有事项很可能发生且金额可计量时确认的负债。"},
    {"term": "关联方", "definition": "一方控制、共同控制另一方或对另一方施加重大影响，以及两方同受一方控制的各方。"},
    {"term": "非经营性资金占用", "definition": "控股股东及关联方非因经营活动需要而占用上市公司资金，属监管禁止行为。"},
    {"term": "强调事项段", "definition": "审计报告中提醒报表使用者关注某事项的段落，不影响审计意见类型本身。"},
    {"term": "保留意见", "definition": "注册会计师认为财报整体公允但存在影响重大的局部问题时的审计意见类型。"},
    {"term": "无法表示意见", "definition": "审计范围受到重大限制、注册会计师无法获取充分适当审计证据时的意见类型，性质严重。"},
]

# ---------------------------------------------------------------- 正确示例（至少 2 个）
GOOD_EXAMPLES: List[Dict[str, Any]] = [
    {
        "title": "示例1：业绩预增（利好向）",
        "text_snippet": "预计2026年半年度实现归属于上市公司股东的净利润为2.10亿元，与上年同期相比增加1.05亿元，同比增长100%左右。",
        "expected": {
            "event_type": "业绩预增或扭亏",
            "metrics": [
                {"name": "归属于上市公司股东的净利润", "value": "2.10亿元", "yoy_change": "同比增长100%左右"},
            ],
            "risk_level": "低",
            "reason": "净利润同比翻倍，业绩预告口径下为正面信息；但需提示增幅是否来自主营业务（公告未说明非经常性损益影响，属信息不足）。",
            "evidence": "预计2026年半年度实现归属于上市公司股东的净利润为2.10亿元，与上年同期相比增加1.05亿元，同比增长100%左右。",
            "note": "证据必须原样截取公告片段，不得改写数字。",
        },
    },
    {
        "title": "示例2：控股股东减持（风险向）",
        "text_snippet": "公司控股股东XX集团计划自本公告披露之日起15个交易日后的3个月内，通过集中竞价方式减持不超过公司总股本1.5%的股份。",
        "expected": {
            "event_type": "股东或高管减持",
            "metrics": [
                {"name": "拟减持股份比例", "value": "不超过公司总股本的1.5%"},
            ],
            "risk_level": "高",
            "reason": "减持主体为控股股东，且单次拟减持比例达到1.5%（超过1%参考线），按知识库判定规则归为高风险。",
            "evidence": "控股股东XX集团计划自本公告披露之日起15个交易日后的3个月内，通过集中竞价方式减持不超过公司总股本1.5%的股份。",
            "note": "主体身份（控股股东）与比例（1.5%）是定级关键，两者都必须有原文依据。",
        },
    },
    {
        "title": "示例3：对外担保（风险向，演示信息不足场景）",
        "text_snippet": "公司为全资子公司向银行申请综合授信提供连带责任保证担保，担保金额为人民币3亿元。",
        "expected": {
            "event_type": "对外担保或资金占用",
            "metrics": [{"name": "担保金额", "value": "人民币3亿元"}],
            "risk_level": "中",
            "reason": "存在对外担保事实，但公告未披露被担保方资产负债率与担保余额占净资产比例，无法完成充分定级，需人工复核。",
            "evidence": "公司为全资子公司向银行申请综合授信提供连带责任保证担保，担保金额为人民币3亿元。",
            "note": "这是'信息不足'的正确处理范式：给出事实，同时明确说明缺什么。",
        },
    },
]


def build_default_kb() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "risk_rules": RISK_RULES,
        "terms": TERMS,
        "good_examples": GOOD_EXAMPLES,
    }


def load_kb(path: Path | None = None) -> Dict[str, Any]:
    """加载知识库；文件不存在时回落到内置默认知识库，并在内存中写回一份便于查看。"""
    p = path or (KB_DIR / "risk_kb.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    kb = build_default_kb()
    try:
        KB_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return kb


def retrieve(query_text: str, kb: Dict[str, Any] | None = None, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    简单的关键词加权检索（无向量库依赖，离线可跑）。

    命中关键词越多、命中越长的词，得分越高；同时返回判定说明与默认等级。
    """
    kb = kb or load_kb()
    text = query_text or ""
    scores: List[tuple] = []
    for rule in kb.get("risk_rules", []):
        hit = [k for k in rule.get("trigger_keywords", []) if k and k in text]
        if hit:
            score = sum(len(k) for k in hit) / 10.0 + len(hit)
            scores.append((score, {
                "kind": "risk_rule",
                "risk_type": rule["risk_type"],
                "definition": rule["definition"],
                "judge": rule["judge"],
                "default_level": rule.get("default_level", "信息不足"),
                "level_rules": rule.get("level_rules", {}),
                "hit_keywords": hit,
                "source": rule.get("source", "规则"),
            }))
    scores.sort(key=lambda x: -x[0])
    top = [item for _, item in scores[:top_k]]

    # 附带命中的术语解释
    for t in kb.get("terms", []):
        term = t.get("term", "")
        if term and term in text and len(top) < top_k + 3:
            top.append({"kind": "term", "term": term,
                        "definition": t.get("definition", ""), "source": "术语表"})
    return top


def format_retrieved(items: List[Dict[str, Any]]) -> str:
    """把检索结果渲染成可放进提示词的文本块。"""
    if not items:
        return "（本次未命中知识库条目，请严格依据公告原文判断，不确定时输出信息不足。）"
    lines = []
    for i, it in enumerate(items, 1):
        if it["kind"] == "risk_rule":
            lines.append(
                f"{i}. [风险规则] {it['risk_type']}\n"
                f"   定义：{it['definition']}\n"
                f"   判定：{it['judge']}\n"
                f"   等级参考：默认{it['default_level']}；{it.get('level_rules', {})}\n"
                f"   命中关键词：{it.get('hit_keywords', [])}\n"
                f"   来源：{it.get('source', '')}"
            )
        else:
            lines.append(f"{i}. [术语] {it['term']}：{it['definition']}（来源：{it.get('source', '')}）")
    return "\n".join(lines)


def format_examples(kb: Dict[str, Any] | None = None, limit: int = 2) -> str:
    kb = kb or load_kb()
    out = []
    for ex in kb.get("good_examples", [])[:limit]:
        out.append(f"【{ex['title']}】\n原文：{ex['text_snippet']}\n"
                   f"期望抽取：{json.dumps(ex['expected'], ensure_ascii=False)}")
    return "\n\n".join(out)
