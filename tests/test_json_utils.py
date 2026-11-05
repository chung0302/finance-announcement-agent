# -*- coding: utf-8 -*-
"""JSON 解析与修复单元测试（对应"模型返回非法 JSON"的错误处理要求）。"""
import pytest

from src.json_utils import LLMOutputError, coerce_dict, safe_json_loads, strip_code_fence


def test_plain_json():
    assert safe_json_loads('{"a": 1}')["a"] == 1


def test_code_fence():
    raw = '```json\n{"company_name": "某某公司"}\n```'
    assert safe_json_loads(raw)["company_name"] == "某某公司"


def test_strip_code_fence():
    assert strip_code_fence("```json\n{}\n```") == "{}"
    assert strip_code_fence("{}") == "{}"


def test_surrounding_text():
    raw = '好的，以下是抽取结果：\n{"company_name": "A公司"}\n如需补充请告知。'
    assert safe_json_loads(raw)["company_name"] == "A公司"


def test_fullwidth_quotes_and_trailing_comma():
    raw = '{"company_name": “A公司”, "metrics": [],}'
    obj = safe_json_loads(raw)
    assert obj["company_name"] == "A公司"
    assert obj["metrics"] == []


def test_truncated_json_without_closing_brace():
    raw = '{"company_name": "A公司", "metrics": [{"name": "净利润", "value": "1.2亿元"}'
    obj = safe_json_loads(raw)
    assert obj["company_name"] == "A公司"


def test_single_quoted_keys():
    raw = "{'company_name': 'A公司'}"
    assert safe_json_loads(raw)["company_name"] == "A公司"


def test_nested_braces_in_string():
    raw = '{"evidence": {"quote": "公司{a}的公告"}, "ok": true}'
    obj = safe_json_loads(raw)
    assert obj["evidence"]["quote"] == "公司{a}的公告"


def test_invalid_raises():
    with pytest.raises(LLMOutputError):
        safe_json_loads("这是一段没有任何 JSON 的文本")
    with pytest.raises(LLMOutputError):
        safe_json_loads("")


def test_coerce_dict_from_list():
    assert coerce_dict([{"a": 1}])["a"] == 1
    with pytest.raises(LLMOutputError):
        coerce_dict([1, 2, 3])
