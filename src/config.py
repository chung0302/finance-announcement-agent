"""
财经公告风险识别助手 - 全局配置与路径常量。

约定：
- 所有密钥只从环境变量 / .env 读取，绝不写入源码或日志。
- 无密钥时应用必须能启动（自动降级为演示模式）。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
# src/config.py -> 项目根
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
SAMPLES_DIR: Path = DATA_DIR / "samples"
KB_DIR: Path = DATA_DIR / "knowledge"
PROMPTS_DIR: Path = PROJECT_ROOT / "prompts"
EVAL_DIR: Path = PROJECT_ROOT / "evaluations"
RESULTS_DIR: Path = EVAL_DIR / "results"
DOCS_DIR: Path = PROJECT_ROOT / "docs"
SCREENSHOT_DIR: Path = DOCS_DIR / "screenshots"
TESTS_DIR: Path = PROJECT_ROOT / "tests"


def ensure_dirs() -> None:
    """确保运行期需要的目录存在（只读场景缺失时自动补建）。"""
    for d in (DATA_DIR, SAMPLES_DIR, KB_DIR, PROMPTS_DIR,
              EVAL_DIR, RESULTS_DIR, DOCS_DIR, SCREENSHOT_DIR, TESTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 模型配置
ENV_BASE_URL = "LLM_BASE_URL"
ENV_API_KEY = "LLM_API_KEY"
ENV_MODEL = "LLM_MODEL"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# 超时与重试：模型不可用时必须快速失败并降级，不能拖死界面
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

# 单次送入模型的公告文本上限（字符），避免超长公告撑爆上下文
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "12000"))

# 证据校验：文本归一化后允许的最小证据长度
MIN_EVIDENCE_LEN = 4
# 证据模糊匹配阈值（0~1），低于该值视为「未通过校验」
EVIDENCE_MATCH_THRESHOLD = 0.82


def load_dotenv_if_available(path: Path | None = None) -> None:
    """可选加载 .env。没有 python-dotenv 或没有 .env 文件时静默跳过。"""
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    target = path or (PROJECT_ROOT / ".env")
    if target.exists():
        load_dotenv(target, override=False)


class LLMConfig:
    """从环境变量构造的模型配置；缺失密钥时 available=False。"""

    def __init__(self) -> None:
        load_dotenv_if_available()
        self.base_url: str = (os.getenv(ENV_BASE_URL) or DEFAULT_BASE_URL).strip().rstrip("/")
        self.api_key: str = (os.getenv(ENV_API_KEY) or "").strip()
        self.model: str = (os.getenv(ENV_MODEL) or DEFAULT_MODEL).strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def masked(self) -> dict:
        """用于界面/日志展示，密钥只保留首尾各 3 位。"""
        k = self.api_key
        shown = "" if not k else (k[:3] + "*" * max(0, len(k) - 6) + k[-3:] if len(k) > 6 else "***")
        return {"base_url": self.base_url, "model": self.model, "api_key": shown}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"LLMConfig(base_url={self.base_url!r}, model={self.model!r}, available={self.available})"


def get_config() -> LLMConfig:
    return LLMConfig()
