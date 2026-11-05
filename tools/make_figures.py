# -*- coding: utf-8 -*-
"""
生成实验报告用的分图（不是整页长图）。

报告排版用图的原则：一图讲一件事，视口 1440x900、按需滚动定位，
放进 Word 后仍能看清文字；整页 3000px 长图缩到 A4 宽度会糊。

输出：docs/screenshots/fig*.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

PORT = os.getenv("APP_PORT", "8501")
BASE = f"http://127.0.0.1:{PORT}"
GOOD = f"{BASE}/?sample=demo_001_positive_earnings_up.txt&autorun=1"
RISK = f"{BASE}/?sample=demo_002_risk_share_reduction.txt&autorun=1"
# 真实模型模式下单次分析约 10~15 秒，等待结果出现的超时要放宽
RESULT_WAIT = int(os.getenv("RESULT_WAIT_MS", "60000"))


def scroll_to(page, text: str, offset: int = 70) -> None:
    """把包含指定文案的元素滚到视口顶部（留出一点上边距）。"""
    page.evaluate(
        """([needle, off]) => {
            const all = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,p,span,div'));
            const hit = all.find(e => e.children.length === 0 && e.textContent.trim() === needle);
            if (hit) {
                hit.scrollIntoView({block: 'start', behavior: 'instant'});
                const main = document.querySelector('main') || document.scrollingElement;
                if (main) main.scrollBy(0, -off);
                window.scrollBy(0, -off);
            }
            return !!hit;
        }""",
        [text, offset],
    )


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.set_default_timeout(RESULT_WAIT)

        # 图 1：首屏（模式横幅 + 样例按钮）
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("text=开始分析")
        page.wait_for_timeout(1800)
        page.screenshot(path=str(OUT / "fig1_home.png"))
        print("fig1_home.png")

        # 图 2：利好消息结果（一句话结论 + 指标卡 + 结构化字段）
        page.goto(GOOD, wait_until="domcontentloaded")
        page.wait_for_selector("text=一句话结论")
        page.wait_for_timeout(2200)
        scroll_to(page, "一句话结论", 210)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "fig2_result.png"))
        print("fig2_result.png")

        # 图 3：风险识别（标签 + 等级 + 原因 + 事实/推断/不确定性）
        page.goto(RISK, wait_until="domcontentloaded")
        page.wait_for_selector("text=一句话结论")
        page.wait_for_timeout(2200)
        scroll_to(page, "风险识别", 80)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "fig3_risk.png"))
        print("fig3_risk.png")

        # 图 4：原文证据清单（绿色已验证 / 说明匹配方式与相似度）
        scroll_to(page, "原文证据清单", 80)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "fig4_evidence.png"))
        print("fig4_evidence.png")

        # 图 5：信息不足提示 + 二次自检 + 导出
        scroll_to(page, "信息不足提示", 80)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "fig5_selfcheck.png"))
        print("fig5_selfcheck.png")

        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"截图失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
