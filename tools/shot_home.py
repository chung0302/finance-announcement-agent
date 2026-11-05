# -*- coding: utf-8 -*-
"""
启动后自检：确认服务真的在跑，并截一张首页图，方便肉眼确认。

用法：python tools/shot_home.py [输出路径]
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "evaluations" / "home_check.png")
URL = "http://127.0.0.1:8501"


def check_http() -> str:
    try:
        with urllib.request.urlopen(URL + "/_stcore/health", timeout=8) as r:
            return f"健康检查 HTTP {r.status}：{r.read().decode().strip()}"
    except Exception as exc:  # noqa: BLE001
        return f"健康检查失败：{exc}"


def main() -> None:
    print(check_http())
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.set_default_timeout(40000)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("text=开始分析")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT))
        browser.close()
    print(f"截图已保存：{OUT}")


if __name__ == "__main__":
    main()
