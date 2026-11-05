# -*- coding: utf-8 -*-
"""
提交前密钥体检：扫描项目里所有文本文件，找出疑似 API Key / Token 的字符串。

用法：python tools/scan_secrets.py
输出：命中的文件与行号（不打印密钥本身，只显示首尾各 4 位）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = Path("C:/Users/openwind/Desktop/财经智能体/finance-announcement-agent/.env")

# 常见密钥形态：sk-xxx、"api_key": "xxx"、Bearer xxx、ghp_xxx
PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})"),
]

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
TEXT_EXT = {".py", ".md", ".txt", ".toml", ".json", ".csv", ".bat", ".ps1", ".yml", ".yaml",
            ".env", ".example", ".cfg", ".ini", ".log"}


def mask(s: str) -> str:
    return s if len(s) <= 10 else f"{s[:4]}…{s[-4:]} (len={len(s)})"


def main() -> int:
    hits: list[str] = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXT and path.name != ".env":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            for pat in PATTERNS:
                for m in pat.finditer(line):
                    token = m.group(m.lastindex) if m.lastindex else m.group(0)
                    hits.append(f"{path.relative_to(ROOT)}:{i}  {mask(token)}")

    print(f"扫描 {scanned} 个文本文件")
    if hits:
        print(f"命中 {len(hits)} 处，逐个确认是否应该提交：")
        for h in hits:
            print("  " + h)
        print("\n注意：.env 本来就会命中（它就是存密钥的地方），只要它被 .gitignore 排除即可。")
    else:
        print("未发现疑似密钥。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
