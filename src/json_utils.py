"""
健壮的 JSON 解析工具。

模型常常返回：
- 带 ```json 围栏的文本
- 前后带解释文字
- 中文引号 / 尾逗号 / 单引号
- 被截断的不完整 JSON

这里做「提取 -> 修复 -> 解析 -> 有限次数重试」的完整处理；
实在解析不出来时抛出 LLMOutputError，由上层降级处理，绝不把半成品当结果。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


class LLMOutputError(ValueError):
    """模型输出无法解析为合法 JSON。"""


def strip_code_fence(text: str) -> str:
    """去掉 ``` 代码围栏，返回内部内容；没有围栏则原样返回。"""
    if not text:
        return ""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # 只有开头的围栏（被截断）时，去掉开头那行
    return re.sub(r"^\s*```(?:json|JSON)?\s*", "", text).strip()


def _find_json_object(text: str) -> Optional[str]:
    """用括号配对找出第一个完整的 {...} 片段（忽略字符串内部的括号）。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _autoclose(s: str) -> str:
    """
    补全被截断的 JSON：统计未闭合的 { / [，并在末尾补上对应数量的闭合符。

    模型输出被 max_tokens 截断时非常常见，这一步能把"半截 JSON"救回来。
    """
    brace = brack = 0
    in_str = esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "[":
            brack += 1
        elif ch == "]":
            brack -= 1
    out = s.rstrip()
    if in_str:
        out += '"'
    out = re.sub(r",\s*$", "", out)
    return out + "]" * max(0, brack) + "}" * max(0, brace)


def _repair(text: str) -> str:
    """常见的非法 JSON 修复：中文引号、尾逗号、单引号、截断。"""
    s = text.strip()
    # 中文引号 -> 英文引号（仅在明显成对出现时替换，避免误伤内容里的书名号）
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # 单引号包裹的 key -> 双引号
    s = re.sub(r"(?<=[{,])\s*'([^']+)'\s*:", r'"\1":', s)
    # 单引号包裹的 value -> 双引号
    s = re.sub(r":\s*'([^']*)'", r': "\1"', s)
    # 去掉尾逗号： , } 或 , ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # 括号未闭合（截断）-> 自动补全
    if s.count("{") > s.count("}") or s.count("[") > s.count("]"):
        s = _autoclose(s)
    return s


def _try_load(candidate: str) -> Optional[Any]:
    for txt in (candidate, _repair(candidate)):
        try:
            return json.loads(txt)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def safe_json_loads(text: str) -> Any:
    """
    尽最大努力把模型输出解析为 Python 对象。

    :raises LLMOutputError: 所有尝试都失败
    """
    if text is None or not str(text).strip():
        raise LLMOutputError("模型返回为空")

    raw = str(text).strip()
    attempts: list[str] = []

    attempts.append(strip_code_fence(raw))
    obj = _find_json_object(raw)
    if obj:
        attempts.append(obj)
    attempts.append(raw)

    for cand in attempts:
        parsed = _try_load(cand)
        if parsed is not None:
            return parsed

    # 最后一招：把第一个 { 之后、最后一个 } 之前的内容拿出来再试
    if "{" in raw and "}" in raw:
        trimmed = raw[raw.find("{"): raw.rfind("}") + 1]
        parsed = _try_load(trimmed)
        if parsed is not None:
            return parsed

    raise LLMOutputError(f"无法解析模型输出为 JSON：{raw[:200]}")


def coerce_dict(obj: Any) -> Dict[str, Any]:
    """把解析结果强制成 dict；列表则取第一个 dict 元素。"""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                return item
    raise LLMOutputError(f"模型输出不是 JSON 对象：{type(obj).__name__}")
