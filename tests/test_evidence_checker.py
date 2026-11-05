# -*- coding: utf-8 -*-
"""证据校验单元测试。"""
from src.evidence_checker import (check_all, check_evidence, extract_numbers,
                                  find_snippet, numbers_consistent)
from src.schemas import Evidence

TEXT = (
    "公司控股股东华岭控股集团有限公司计划自本公告披露之日起15个交易日后的3个月内，"
    "通过集中竞价方式减持不超过公司总股本1.50%的股份。"
    "本次业绩预告未经审计。"
)


def test_exact_match():
    ev = check_evidence("通过集中竞价方式减持不超过公司总股本1.50%的股份", TEXT)
    assert ev.matched is True
    assert ev.score == 1.0
    assert ev.match_method == "精确包含"


def test_match_ignores_punctuation_and_space():
    ev = check_evidence("减持不超过公司总股本1.50%的股份。", TEXT)
    assert ev.matched is True


def test_no_match_returns_unverified():
    ev = check_evidence("公司拟回购不超过5亿元股份", TEXT)
    assert ev.matched is False
    assert ev.match_method == "未匹配"


def test_empty_quote_is_unverified():
    assert check_evidence("", TEXT).matched is False
    assert check_evidence("减持", "").matched is False


def test_too_short_quote_is_unverified():
    ev = check_evidence("减持", TEXT)
    assert ev.matched is False
    assert ev.match_method == "证据过短"


def test_fuzzy_match_on_tiny_typo():
    ev = check_evidence("通过集中竞价方式减持不超过公司总股本1.50%的股份啊", TEXT)
    assert ev.matched is True  # 仅多一个字，模糊匹配应通过
    assert ev.match_method == "模糊匹配"


def test_find_snippet_returns_window():
    snip = find_snippet(TEXT, "集中竞价", window=40)
    assert snip is not None and "集中竞价" in snip


def test_find_snippet_returns_none_when_absent():
    assert find_snippet(TEXT, "回购股份") is None


def test_check_all_splits_verified_and_unverified():
    evs = [Evidence(quote="通过集中竞价方式减持", note="A"),
           Evidence(quote="完全不存在的句子", note="B")]
    ok, bad = check_all(evs, TEXT)
    assert len(ok) == 1 and len(bad) == 1
    assert ok[0].note == "A" and bad[0].note == "B"


def test_extract_numbers():
    assert extract_numbers("2.10亿元，同比增长100%") == [2.10, 100.0]
    assert extract_numbers("未披露") == []


def test_numbers_consistent():
    assert numbers_consistent("净利润2.10亿元", "预计净利润为2.10亿元") is True
    assert numbers_consistent("净利润9.99亿元", "预计净利润为2.10亿元") is False
    # 结论没有数字时不判幻觉
    assert numbers_consistent("公司存在减持计划", "减持不超过1.50%") is True
    # 结论有数字但证据没有 -> 判为不一致
    assert numbers_consistent("涉案金额1.8亿元", "公司涉及一起诉讼") is False
