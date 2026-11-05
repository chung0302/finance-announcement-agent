"""
文件读取（PDF / TXT）。

边界：
- 只支持**文本型** PDF。扫描版 PDF（图片页）不做 OCR，检测到无文本层时返回明确错误。
- 编码自动尝试 UTF-8 / GBK / UTF-8-BOM，失败时给出可读错误而不是崩溃。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import io
from typing import List, Optional, Tuple


class FileLoadError(ValueError):
    """文件无法读取或不含可提取文本。"""


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "big5"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def load_txt(data: bytes) -> Tuple[str, List[str]]:
    text = _decode(data)
    return text, []


def load_pdf(data: bytes, min_text_len: int = 30) -> Tuple[str, List[str]]:
    """
    用 pypdf 抽取 PDF 文本。

    :raises FileLoadError: 未安装 pypdf、文件损坏，或整份文档没有文本层（扫描件）
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise FileLoadError("未安装 pypdf，请先执行 pip install -r requirements.txt") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise FileLoadError(f"PDF 解析失败（文件可能损坏或不是标准 PDF）：{exc}") from exc

    pages: List[str] = []
    empty_pages = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页解析失败不应中断整体
            t = ""
        pages.append(t)
        if len(t.strip()) < min_text_len:
            empty_pages += 1

    raw = "\n\n".join(pages)
    if not raw.strip():
        raise FileLoadError("该 PDF 没有可提取的文本层（可能是扫描件或图片版），本工具不做 OCR。")
    if empty_pages == len(pages) and len(pages) > 0:
        raise FileLoadError("该 PDF 所有页均无文本层（疑似扫描件），本工具不做 OCR，请改用文本型 PDF 或 TXT。")
    return raw, pages


def load_any(filename: str, data: bytes) -> Tuple[str, List[str]]:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return load_pdf(data)
    if name.endswith((".txt", ".md", ".text")):
        return load_txt(data)
    # 其余按文本兜底尝试
    try:
        return load_txt(data)
    except Exception as exc:  # noqa: BLE001
        raise FileLoadError(f"不支持的文件类型：{filename or '未知'}（{exc}）") from exc
