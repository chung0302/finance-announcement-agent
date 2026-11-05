# -*- coding: utf-8 -*-
"""界面级冒烟测试：用 Streamlit AppTest 验证「载入样例 → 文本框同步 → 分析 → 渲染」全链路。

这组测试针对课堂演示的真实操作路径，避免出现「按钮点了但输入框没变」的静默缺陷。
"""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _new_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    return at


def test_app_boots_without_api_key():
    """无密钥时必须能启动，并给出引导而不是报错。"""
    at = _new_app()
    assert not at.exception
    assert any("载入样例" in i.value or "粘贴" in i.value for i in at.info)


def test_load_good_sample_updates_textarea():
    at = _new_app()
    at.sidebar.button[0].click().run()  # ▶ 载入利好样例
    assert not at.exception
    assert "星海智能科技" in at.text_area[0].value


def test_analyze_sample_renders_demo_banner_and_conclusion():
    at = _new_app()
    at.sidebar.button[0].click().run()
    at.button[0].click().run()  # 🚀 开始分析（主区域第一个按钮）
    assert not at.exception
    assert at.metric[0].value in {"低", "中", "高", "信息不足"}
    body = " ".join(m.value for m in at.markdown)
    assert "演示模式" in body
    assert "一句话结论" in body
    assert "原文证据清单" in body


def test_risk_sample_triggers_high_level():
    at = _new_app()
    at.sidebar.button[1].click().run()  # ▶ 载入风险样例
    assert "华岭新材料" in at.text_area[0].value
    at.button[0].click().run()
    assert not at.exception
    assert at.metric[0].value == "高"
    body = " ".join(m.value for m in at.markdown)
    assert "股东或高管减持" in body


def test_empty_input_shows_warning():
    at = _new_app()
    at.button[0].click().run()  # 直接分析空输入
    assert not at.exception
    assert any("输入为空" in w.value for w in at.warning)
