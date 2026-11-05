# -*- coding: utf-8 -*-
"""
测试替身：可控的假模型客户端。

用途：在不联网、不消耗 token 的前提下，测试「模型超时 / 返回非法 JSON / 返回正常 JSON」
三类分支，以及降级逻辑。
"""
from __future__ import annotations

from typing import List, Optional

import pytest

from src.llm_client import LLMError


@pytest.fixture(autouse=True)
def isolate_llm_env(monkeypatch):
    """
    让测试不受本机 .env 影响。

    开发机上配好真实密钥后，原本"无密钥应降级为演示模式"的用例会失败——
    这属于测试对环境的隐式依赖，不是产品缺陷。这里统一把三件事隔断：
    不加载 .env、清空三个环境变量，于是所有测试都在确定性的演示模式下跑，
    既不联网也不消耗 token。
    """
    import src.config as cfg

    monkeypatch.setattr(cfg, "load_dotenv_if_available", lambda *a, **k: None)
    for key in (cfg.ENV_API_KEY, cfg.ENV_BASE_URL, cfg.ENV_MODEL):
        monkeypatch.delenv(key, raising=False)
    yield


class _FakeCfg:
    def __init__(self, model: str = "fake-model", available: bool = True):
        self.model = model
        self.available = available
        self.base_url = "http://fake.local/v1"
        self.api_key = "fake-key" if available else ""


class FakeLLMClient:
    """
    :param responses: 每次 chat() 依次返回的内容
    :param raise_exc: 若设置，则 chat() 直接抛该异常（模拟超时/网络失败）
    """

    def __init__(self,
                 responses: Optional[List[str]] = None,
                 raise_exc: Optional[Exception] = None,
                 available: bool = True,
                 model: str = "fake-model"):
        self.responses = list(responses or [])
        self.raise_exc = raise_exc
        self.cfg = _FakeCfg(model=model, available=available)
        self.call_count = 0
        self.last_messages = None
        self.timeout = 5
        self.max_retries = 0
        self.last_error = ""

    @property
    def available(self) -> bool:
        return self.cfg.available

    def chat(self, messages, temperature: float = 0.0, response_format_json: bool = True, max_tokens: int = 2048) -> str:
        if self.raise_exc is not None:
            raise self.raise_exc
        if not self.available:
            raise LLMError("fake client unavailable")
        idx = self.call_count
        self.call_count += 1
        self.last_messages = messages
        if idx >= len(self.responses):
            raise LLMError("fake client: no more preset responses")
        return self.responses[idx]

    def chat_json(self, messages, **kwargs):
        from src.json_utils import safe_json_loads
        return safe_json_loads(self.chat(messages, **kwargs))
