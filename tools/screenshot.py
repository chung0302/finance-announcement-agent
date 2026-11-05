# -*- coding: utf-8 -*-
"""
用本机已安装的 Edge/Chrome（playwright channel）截取应用界面。

不下载 Chromium：playwright 的 channel 参数直接驱动系统浏览器。
等待 Streamlit SPA 渲染完成（等待页面出现目标文案）后再截整页。
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:8501"

JOBS = [
    ("01_initial.png", f"{BASE}/", "上市公司公告风险识别与解释助手"),
    ("02_positive_result.png",
     f"{BASE}/?sample=demo_001_positive_earnings_up.txt&autorun=1", "一句话结论"),
    ("03_risk_result.png",
     f"{BASE}/?sample=demo_002_risk_share_reduction.txt&autorun=1", "一句话结论"),
]


def pick_channel(pw) -> str:
    for ch in ("msedge", "chrome"):
        try:
            b = pw.chromium.launch(channel=ch, headless=True)
            b.close()
            return ch
        except Exception:
            continue
    raise RuntimeError("未找到可用的 Edge/Chrome，请确认浏览器已安装")


def main() -> None:
    with sync_playwright() as pw:
        channel = pick_channel(pw)
        print(f"使用浏览器通道：{channel}")
        # Streamlit 主体在独立滚动容器里，full_page 截不到；直接把视口拉到内容高度
        browser = pw.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)
        for name, url, wait_text in JOBS:
            page.goto(url, wait_until="domcontentloaded")
            # 等 Streamlit 把内容渲染出来（以界面固定文案为锚点）
            page.wait_for_selector(f"text={wait_text}", timeout=30000)
            page.wait_for_timeout(2000)
            # Streamlit 的滚动容器是 main#stMain（实测 scrollHeight），
            # 直接把视口拉高到整页高度，再截图
            h = page.evaluate(
                "() => { const m = document.querySelector('main#stMain');"
                " return Math.ceil(Math.max(document.body.scrollHeight,"
                " document.documentElement.scrollHeight,"
                " m ? m.scrollHeight : 0)); }"
            )
            h = min(max(h, 1000), 12000)
            page.set_viewport_size({"width": 1440, "height": h})
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / name))
            print(f"已截图：{name}（视口高度 {h}）")
        browser.close()
    print("全部完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"截图失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
