# -*- coding: utf-8 -*-
"""表格型公告的抽取测试（回归用）。

对应曾经出现过的问题：
1. 清洗阶段把「比上年同期增长：100.00%左右」当成重复页眉删除，导致同比丢失；
2. 抽取阶段把表格「上年同期」列（营业收入 12.40 亿元）当成当期数据；
3. 减持公告里「1.50%」被判成持股比例（"减持股份"跨词出现"持股"二字）。
"""
from pathlib import Path

import pytest

from src.extractor import Extractor
from src.text_cleaner import clean_text

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture(scope="module")
def good_facts():
    text = (SAMPLES / "demo_001_positive_earnings_up.txt").read_text(encoding="utf-8")
    return Extractor(mode="demo").extract_demo(clean_text(text))


@pytest.fixture(scope="module")
def risk_facts():
    text = (SAMPLES / "demo_002_risk_share_reduction.txt").read_text(encoding="utf-8")
    return Extractor(mode="demo").extract_demo(clean_text(text))


def test_cleaner_keeps_repeated_data_lines():
    """重复出现的「比上年同期增长：X%」是正文数据，不能被当成页眉页脚删掉。"""
    text = (SAMPLES / "demo_001_positive_earnings_up.txt").read_text(encoding="utf-8")
    cleaned = clean_text(text)
    assert cleaned.count("比上年同期增长") >= 3


def test_table_pair_takes_current_period_only(good_facts):
    """表格成对数值只取本期值，上年同期数（1.05/0.98/12.40 亿元）不得出现。"""
    values = {m.value for m in good_facts.metrics}
    assert "2.10亿元" in values
    assert "1.96亿元" in values
    assert "18.60亿元" in values
    assert "1.05亿元" not in values
    assert "0.98亿元" not in values
    assert "12.40亿元" not in values


def test_table_metric_names_and_yoy(good_facts):
    by_value = {m.value: m for m in good_facts.metrics}
    assert by_value["2.10亿元"].name == "归属于上市公司股东的净利润"
    assert by_value["2.10亿元"].yoy_change.endswith("100.00%")
    assert by_value["18.60亿元"].name == "营业收入"
    assert by_value["18.60亿元"].yoy_change.endswith("50.00%")


def test_no_yoy_rate_as_standalone_metric(good_facts):
    """同比变化率由 yoy 字段承载，不应再作为「变化率」指标重复出现。"""
    assert not any(m.name == "变化率" for m in good_facts.metrics)


def test_summary_prefers_core_items(good_facts):
    s = good_facts.summary_sentence
    assert "归属于上市公司股东的净利润2.10亿元" in s
    assert "营业收入18.60亿元" in s
    assert "演示模式" in s and "非模型输出" in s
    assert "同比同比" not in s


def test_reduction_ratio_named_correctly(risk_facts):
    names = {(m.name, m.value) for m in risk_facts.metrics}
    assert ("减持比例", "1.50%") in names
    assert ("持股比例", "38.00%") in names
    # "减持股份"里的"持股"不能把 1.50% 误判成持股比例
    assert ("持股比例", "1.50%") not in names


def test_summary_uses_planned_reduction_ratio(risk_facts):
    s = risk_facts.summary_sentence
    assert "减持比例1.50%" in s
    assert "1.00%" not in s          # 90 日内集中竞价上限不是本次计划总比例


def test_stock_code_survives_header_dedup():
    """重复页眉只保留一份，否则证券代码会丢失、被误报为「未披露」。"""
    text = (SAMPLES / "demo_002_risk_share_reduction.txt").read_text(encoding="utf-8")
    facts = Extractor(mode="demo").extract_demo(clean_text(text))
    assert facts.stock_code == "600892"
    assert not any("证券代码" in m for m in facts.missing_fields)
