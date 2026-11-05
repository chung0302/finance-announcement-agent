"""
提示词加载工具。

提示词统一放在 prompts/ 目录，便于迭代与文档化；代码里只做占位符替换，
不把提示词硬编码进源码。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .config import PROMPTS_DIR


class PromptNotFoundError(FileNotFoundError):
    pass


def load_prompt(name: str) -> str:
    """
    加载 prompts/<name>（自动补 .md 后缀）。

    :raises PromptNotFoundError: 文件不存在
    """
    p = Path(name)
    if p.suffix != ".md":
        p = p.with_suffix(".md")
    if not p.is_absolute():
        p = PROMPTS_DIR / p
    if not p.exists():
        raise PromptNotFoundError(f"提示词文件不存在：{p}")
    return p.read_text(encoding="utf-8")


def load_prompt_or_empty(name: str) -> str:
    try:
        return load_prompt(name)
    except PromptNotFoundError:
        return ""


def render(template: str, **kwargs) -> str:
    """
    把 {占位符} 替换为实际内容。

    用 str.replace 而不是 format，避免公告正文里的花括号破坏格式化。
    """
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out
