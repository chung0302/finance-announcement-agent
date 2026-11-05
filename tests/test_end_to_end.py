# -*- coding: utf-8 -*-
"""
端到端冒烟测试 + 错误处理测试。

覆盖：
- 样例文本 -> 结构化结果（端到端）
- 空输入
- 无文本层 PDF（扫描件）
- 模型超时
- 模型返回非法 JSON
"""
import io
import json
from pathlib import Path

import pytest

from src.config import SAMPLES_DIR
from src.ingest import FileLoadError, load_any
from src.llm_client import LLMError
from src.pipeline import Pipeline
from src.schemas import RiskLevel, RiskType

from tests.conftest import FakeLLMClient

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (SAMPLES_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 端到端
def test_end_to_end_positive_sample():
    text = _read("demo_001_positive_earnings_up.txt")
    res = Pipeline(mode="demo").run(text)

    assert res.mode == "demo"
    assert res.facts.company_name.startswith("星海智能")
    assert res.facts.announcement_date == "2026-07-15"
    assert RiskType.EARNINGS_UP in res.facts.event_types
    assert res.overall_risk_level == RiskLevel.LOW
    assert len(res.evidence_verified) >= 1
    assert res.facts.metrics, "应当抽到关键金额"
    assert any("亿元" in m.value for m in res.facts.metrics)
    assert res.to_markdown().startswith("# 上市公司公告风险识别与解释报告")
    json.loads(json.dumps(res.to_dict()))  # 可序列化


def test_end_to_end_risk_sample():
    text = _read("demo_002_risk_share_reduction.txt")
    res = Pipeline(mode="demo").run(text)

    assert RiskType.SHARE_REDUCTION in res.facts.event_types
    assert RiskType.LITIGATION in res.facts.event_types
    assert res.overall_risk_level == RiskLevel.HIGH
    assert res.risks[0].risk_level == RiskLevel.HIGH
    assert res.risks[0].evidence.quote, "高风险结论必须带证据"
    assert res.risks[0].evidence.matched is True
    assert isinstance(res.missing_info, list)


def test_insufficient_info_is_reported_explicitly():
    """担保公告未披露被担保方资产负债率 -> 必须给出信息不足提示 + 人工复核标记。"""
    text = "公司为全资子公司向银行申请综合授信提供连带责任保证担保，担保金额为人民币3亿元。"
    res = Pipeline(mode="demo").run(text)
    assert any("资产负债率" in m for m in res.missing_info)
    assert res.risks[0].need_human_review is True


def test_pipeline_input_output_contract():
    text = _read("demo_001_positive_earnings_up.txt")
    res = Pipeline(mode="demo").run(text)
    d = res.to_dict()
    for key in ("mode", "facts", "risks", "evidence_verified", "evidence_unverified",
                "missing_info", "self_check_issues", "overall_risk_level"):
        assert key in d


# ---------------------------------------------------------------- 错误处理
def test_empty_input_does_not_raise():
    for bad in ("", "   ", "\n\n\n", None):
        res = Pipeline(mode="demo").run(bad or "")
        assert res.overall_risk_level == RiskLevel.UNKNOWN
        assert res.warnings, "空输入必须给出提示而不是崩溃"
        assert res.missing_info


def test_whitespace_only_text_after_clean():
    res = Pipeline(mode="demo").run("；；；；…………")
    assert res.warnings


def test_scanned_pdf_raises_clear_error(tmp_path):
    """构造一个没有文本层的 PDF，验证给出明确错误而不是崩溃。"""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    data = buf.getvalue()

    with pytest.raises(FileLoadError) as exc:
        load_any("scan.pdf", data)
    assert "扫描" in str(exc.value) or "文本层" in str(exc.value)


def test_txt_file_loading():
    raw, pages = load_any("a.txt", "本公告为测试文本。".encode("utf-8"))
    assert "测试文本" in raw
    assert pages == []


def test_unsupported_or_broken_pdf_gives_error():
    with pytest.raises(FileLoadError):
        load_any("broken.pdf", b"not a pdf at all")


def test_model_timeout_falls_back_to_demo():
    text = _read("demo_001_positive_earnings_up.txt")
    client = FakeLLMClient(raise_exc=LLMError("模型调用超时（>60s）"))
    res = Pipeline(mode="auto", client=client).run(text)
    assert res.mode == "demo"
    assert any("降级" in w for w in res.warnings)
    assert res.facts.company_name.startswith("星海智能")  # 降级后仍要出结果


def test_model_illegal_json_falls_back_to_demo():
    text = _read("demo_001_positive_earnings_up.txt")
    client = FakeLLMClient(responses=["这不是 JSON，只是一段说明文字。"])
    res = Pipeline(mode="auto", client=client).run(text)
    assert res.mode == "demo"
    assert res.facts.event_types


def test_llm_mode_forced_without_key_degrades():
    text = _read("demo_002_risk_share_reduction.txt")
    res = Pipeline(mode="llm").run(text)  # 未配置密钥
    assert res.mode == "demo"
    assert any("LLM_API_KEY" in w for w in res.warnings)


def test_fake_llm_happy_path():
    """用假客户端验证 LLM 分支能被正确解析（不联网）。"""
    text = _read("demo_002_risk_share_reduction.txt")
    extraction_json = json.dumps({
        "company_name": "华岭新材料股份有限公司",
        "announcement_title": "关于控股股东减持股份计划的公告",
        "announcement_date": "2026-07-18",
        "stock_code": "600892",
        "event_types": ["股东或高管减持"],
        "metrics": [{
            "name": "拟减持股份比例", "value": "1.50%", "unit": "%",
            "yoy_change": "未披露",
            "evidence": {"quote": "即不超过公司总股本的1.50%", "note": "比例"},
        }],
        "summary_sentence": "控股股东拟减持不超过总股本1.50%的股份。",
        "missing_fields": ["证券代码未披露"],
    }, ensure_ascii=False)
    risk_json = json.dumps({"risks": [{
        "risk_type": "股东或高管减持", "risk_level": "高",
        "reason": "减持主体为控股股东，比例1.50%超过1%参考线。",
        "facts": ["减持主体为控股股东"], "inferences": ["市场通常视作负面信号"],
        "uncertainties": ["未披露减持价格区间"],
        "evidence": {"quote": "即不超过公司总股本的1.50%", "note": "依据"},
        "confidence": 0.8, "need_human_review": True,
    }]}, ensure_ascii=False)

    client = FakeLLMClient(responses=[extraction_json, risk_json])
    res = Pipeline(mode="llm", client=client).run(text)
    assert res.mode == "llm"
    assert res.facts.company_name == "华岭新材料股份有限公司"
    assert res.risks[0].risk_type == RiskType.SHARE_REDUCTION
    assert res.risks[0].evidence.matched is True  # 证据能在原文中定位
    assert res.risks[0].risk_level == RiskLevel.HIGH
