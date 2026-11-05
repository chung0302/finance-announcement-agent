# -*- coding: utf-8 -*-
"""文本清洗单元测试。"""
import pytest

from src.text_cleaner import (clean_text, detect_repeated_lines, merge_broken_lines,
                              normalize_for_matching, remove_headers_footers,
                              remove_repeated_lines, to_halfwidth_digits_letters)


def test_merge_broken_lines_joins_wrapped_chinese():
    raw = "公司预计2026年半年度实现归属于上市公司股东的净\n利润为2.10亿元，同比增长100%左右。"
    out = merge_broken_lines(raw)
    assert "净利润为2.10亿元" in out
    assert "\n净" not in out


def test_merge_broken_lines_keeps_sentence_boundary():
    raw = "本次业绩预告未经审计。\n具体数据以半年度报告为准。"
    out = merge_broken_lines(raw)
    assert out.count("\n") == 1  # 句号结尾的行不与下一行合并


def test_merge_broken_lines_keeps_numbered_items():
    raw = "一、本期业绩预计情况\n1、业绩预告期间"
    out = merge_broken_lines(raw)
    assert out.splitlines()[0] == "一、本期业绩预计情况"


def test_fullwidth_digits_and_letters():
    assert to_halfwidth_digits_letters("２．１０亿元Ａ股") == "2.10亿元A股"
    # 中文标点不应被转换
    assert to_halfwidth_digits_letters("净利润，增长。") == "净利润，增长。"


def test_remove_repeated_lines_keeps_single_header():
    text = ("证券代码：600892 证券简称：华岭新材 公告编号：2026-032\n"
            "关于控股股东减持股份计划的公告\n"
            "证券代码：600892 证券简称：华岭新材 公告编号：2026-032\n"
            "一、股东基本情况")
    out = remove_repeated_lines(text)
    # 重复页眉只保留第一份：全删会让"证券代码/证券简称"变成"未披露"
    assert out.count("证券代码") == 1
    assert "关于控股股东减持股份计划的公告" in out


def test_detect_and_remove_headers_footers_across_pages():
    pages = [
        "证券代码：600892 公告编号：2026-032\n正文第一页内容",
        "证券代码：600892 公告编号：2026-032\n正文第二页内容",
    ]
    repeated = detect_repeated_lines(pages)
    assert "证券代码：600892 公告编号：2026-032" in repeated
    cleaned = remove_headers_footers(pages)
    joined = "\n".join(cleaned)
    assert joined.count("证券代码") == 1   # 第 1 页保留一份，第 2 页删除
    assert "正文第一页内容" in joined and "正文第二页内容" in joined


def test_clean_text_end_to_end():
    raw = ("证券代码：600892  证券简称：华岭新材  公告编号：2026-032\n"
           "证券代码：600892  证券简称：华岭新材  公告编号：2026-032\n"
           "公司预计2026年半年度实现归属于上市公司股东的净\n利润为２．１０亿元。\n\n")
    out = clean_text(raw)
    assert out.count("证券代码") == 1
    assert "净利润为2.10亿元" in out


def test_normalize_for_matching_ignores_space_and_punct():
    a = "预计净利润为2.10亿元，同比增长100%左右。"
    b = "预计净利润为2.10亿元, 同比增长100%左右。"
    assert normalize_for_matching(a) == normalize_for_matching(b)
    assert normalize_for_matching("２１０") == normalize_for_matching("210")


def test_clean_text_handles_empty_and_none():
    assert clean_text("") == ""
    assert clean_text(None) == ""  # type: ignore[arg-type]
    assert clean_text("   \n\n  ") == ""


@pytest.mark.parametrize("raw,expect", [
    ("第 1 页", ""),
    ("— 2 —", ""),
])
def test_page_number_removed(raw, expect):
    pages = [raw + "\n正文", raw + "\n正文二"]
    cleaned = remove_headers_footers(pages)
    assert raw not in cleaned[0]
