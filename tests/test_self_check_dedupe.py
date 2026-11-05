# -*- coding: utf-8 -*-
"""信息不足提示的近似去重：同一件事只留一条，且保留表述最具体的那条。"""
from src.self_check import dedupe_missing


def test_identical_items_collapse():
    assert dedupe_missing(["涉案金额未披露", "涉案金额未披露"]) == ["涉案金额未披露"]


def test_containment_keeps_more_specific():
    items = ["涉案金额未披露", "公告未披露涉案金额占最近一期经审计净资产的比例"]
    out = dedupe_missing(items)
    assert len(out) == 1
    assert "占最近一期经审计净资产的比例" in out[0]


def test_paraphrase_collapses():
    # 语序不同但说的是同一件事
    out = dedupe_missing(["涉案金额未披露", "公告未披露涉案金额"])
    assert len(out) == 1


def test_distinct_items_are_kept():
    items = ["减持价格未披露", "涉案金额未披露", "被担保方资产负债率未披露"]
    out = dedupe_missing(items)
    assert len(out) == 3


def test_order_preserved_and_blank_dropped():
    out = dedupe_missing(["减持价格未披露", "  ", "", "担保余额未披露"])
    assert out == ["减持价格未披露", "担保余额未披露"]


def test_chain_collapses_after_representative_grows():
    """
    代表项被替换成更长的一条后，先前判为不重复的条目仍可能与新代表项重复，
    需要反复扫描到稳定，否则会漏掉「公告未披露涉案金额」这类中间形态。
    """
    items = [
        "涉案金额未披露",
        "涉案金额占最近一期经审计净资产比例未披露",
        "公告未披露涉案金额",
        "公告未披露涉案金额占最近一期经审计净资产的比例",
    ]
    out = dedupe_missing(items)
    assert len(out) == 1, out
    assert "占最近一期经审计净资产的比例" in out[0]
