"""
文本清洗模块（流水线第 1 步）。

职责：
1. 合并 PDF 断行（中文行末没有句号/分号时，视为被强行折行，与下一行拼接）。
2. 删除重复页眉页脚（跨页重复出现的短行）。
3. 统一全角/半角、空白字符。
4. 保留原始文本用于证据回溯 —— 证据永远回到"清洗后原文"上做匹配。

注意：清洗只影响展示与检索，不改变原文语义；evidence_checker 在匹配时会对
清洗后原文和证据片段再各自做一次「匹配级归一化」，以吸收标点/空格差异。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import List

# 行末出现这些字符时，认为该行是一个自然段落结束，不与下一行合并
_SENTENCE_END = "。；！？：）”】》」』. ;!?:"
# 行首出现这些字符时，认为是新的一句/新的一条，不向上合并
_LINE_START_STOP = "（(【《“「『一二三四五六七八九十1234567890关于"


def to_halfwidth_digits_letters(s: str) -> str:
    """只把全角数字/字母/空格转半角，保留中文标点不变（用于展示文本）。"""
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
        elif code == 0xFF0E:  # 全角句号（金额里常见："２．１０亿元"）
            out.append(".")
        elif 0xFF10 <= code <= 0xFF19:  # ０-９
            out.append(chr(code - 0xFEE0))
        elif 0xFF21 <= code <= 0xFF3A:  # Ａ-Ｚ
            out.append(chr(code - 0xFEE0))
        elif 0xFF41 <= code <= 0xFF5A:  # ａ-ｚ
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize_whitespace(s: str) -> str:
    """统一各种空白（含不间断空格、制表符）为普通半角空格，并压缩行内连续空格。"""
    s = s.replace("\u00a0", " ").replace("\t", " ").replace("\u3000", " ")
    s = re.sub(r"[ ]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def detect_repeated_lines(pages: List[str], min_pages: int = 2, max_len: int = 40) -> List[str]:
    """
    找出在多个页面中重复出现的短行 —— 典型页眉/页脚（如"证券代码：600XXX  证券简称：XX  公告编号：2026-001"）。

    :param pages: 按页切分后的文本列表
    :param min_pages: 至少在多少页中出现才算重复
    :param max_len: 页眉页脚通常很短，超过该长度不认为是页眉页脚
    """
    if len(pages) < 2:
        return []
    counter: Counter = Counter()
    for page in pages:
        seen = set()
        for line in page.splitlines():
            line = line.strip()
            if not line or len(line) > max_len:
                continue
            # 纯数字页号也算页脚
            if line in seen:
                continue
            seen.add(line)
            counter[line] += 1
    return [line for line, c in counter.items() if c >= min_pages]


def remove_headers_footers(pages: List[str]) -> List[str]:
    """删除跨页重复的页眉页脚，以及独立的纯数字页码行。"""
    repeated = set(detect_repeated_lines(pages))
    cleaned_pages: List[str] = []
    seen_once = set()
    for page in pages:
        keep = []
        for line in page.splitlines():
            s = line.strip()
            if not s:
                keep.append("")
                continue
            if s in repeated:
                if s in seen_once:
                    continue
                # 保留第一次出现：页眉里的证券代码/简称是有效元信息，全删会丢失字段
                seen_once.add(s)
            if re.fullmatch(r"[-—–\s]*第?\s*\d{1,4}\s*页?\s*(共\s*\d{1,4}\s*页)?[-—–\s]*", s):
                continue
            keep.append(line)
        cleaned_pages.append("\n".join(keep))
    return cleaned_pages


_HEADER_HINTS = ("证券代码", "证券简称", "公告编号", "http", "www", "巨潮", "第 ", "页", "披露媒体")
# 含这些词的行是正文数据（如表格里两行都写"比上年同期增长：100.00%左右"），
# 即使重复出现也不能当作页眉页脚删除。
_DATA_HINTS = ("盈利", "增长", "减少", "下降", "上升", "亿元", "万元", "%", "同比", "万股")


def _looks_like_header_footer(s: str) -> bool:
    """判断一行是否像页眉/页脚，避免把重复出现的正文数据行误删。"""
    if any(k in s for k in _DATA_HINTS):
        return False
    if any(k in s for k in _HEADER_HINTS):
        return True
    return len(s) <= 15


def remove_repeated_lines(text: str, max_len: int = 40) -> str:
    """
    删除在单篇文本内部重复出现（>=2 次）的短行 —— 粘贴版公告里的页眉页脚同样适用。

    只对长度 <= max_len 的行生效，且必须"看起来像页眉页脚"，
    避免误删表格中重复出现的数值行。
    """
    lines = text.splitlines()
    counter: Counter = Counter()
    for line in lines:
        s = line.strip()
        if s and len(s) <= max_len:
            counter[s] += 1
    repeated = {s for s, c in counter.items() if c >= 2 and _looks_like_header_footer(s)}
    if not repeated:
        return text
    # 保留第一次出现的那一行，只删后续重复：
    # 页眉里往往带证券代码/简称等元信息，全删会让这些字段变成"未披露"。
    keep_first = set()
    out = []
    for line in lines:
        s = line.strip()
        if s in repeated:
            if s in keep_first:
                continue
            keep_first.add(s)
        out.append(line)
    return "\n".join(out)


def merge_broken_lines(text: str) -> str:
    """
    合并被 PDF 排版强行折断的行。

    规则：
    - 当前行以中文句号/分号等结束 -> 换行保留（自然段落边界）；
    - 当前行末尾是汉字/数字/百分号等，且下一行不是明显的列表起始 -> 合并为一行；
    - 空行作为段落分隔保留。
    """
    lines = text.splitlines()
    out: List[str] = []
    buf = ""
    for line in lines:
        cur = line.strip()
        if not cur:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")
            continue
        if not buf:
            buf = cur
            continue
        last = buf[-1]
        nxt = cur[0]
        # 上一行已自然结束，或下一行明显是新条目 -> 断开
        if last in _SENTENCE_END or nxt in _LINE_START_STOP or re.match(r"^\d+[\.、)]", cur):
            out.append(buf)
            buf = cur
        else:
            buf += cur
    if buf:
        out.append(buf)
    return "\n".join(out)


def clean_text(raw: str, pages: List[str] | None = None) -> str:
    """
    完整清洗流程。

    :param raw: 原始文本（PDF 抽取或粘贴）
    :param pages: 若提供按页文本，则先做页眉页脚清理
    :return: 清洗后的文本
    """
    if raw is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw))
    text = to_halfwidth_digits_letters(text)
    text = normalize_whitespace(text)
    if pages:
        pages = [unicodedata.normalize("NFKC", p) for p in pages]
        text = "\n\n".join(remove_headers_footers(pages))
        text = to_halfwidth_digits_letters(text)
        text = normalize_whitespace(text)
    else:
        # 粘贴文本：同样清理重复出现的页眉页脚行
        text = remove_repeated_lines(text)
    text = merge_broken_lines(text)
    # 去掉行首行尾空格，但保留段落空行
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ------------------------------------------------------------------ 匹配级归一化
_PUNCT_MAP = {
    "，": ",", "。": ".", "；": ";", "：": ":", "？": "?", "！": "!",
    "（": "(", "）": ")", "【": "[", "】": "]", "《": "<", "》": ">",
    "“": '"', "”": '"', "‘": "'", "’": "'", "、": ",", "－": "-",
    "—": "-", "–": "-", "～": "~", "％": "%", "．": ".", "＊": "*",
}


def normalize_for_matching(s: str) -> str:
    """
    用于证据匹配的激进归一化：全角转半角、标点统一、删除所有空白。

    clean_text 的结果与证据片段都会经过这个函数，因此"空格/换行/全半角"差异
    不会导致误判为不匹配。
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(_PUNCT_MAP.get(ch, ch) for ch in s)
    s = re.sub(r"\s+", "", s)
    s = s.lower()
    return s
