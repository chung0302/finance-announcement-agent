"""
OpenAI 兼容模型客户端。

约束：
- 密钥只从环境变量读取，绝不写进源码、日志或任何产物文件。
- 无密钥 / 超时 / 返回非法内容时，统一抛出 LLMError，由上层降级为演示模式或其他路径，
  保证应用本身不会崩。
- 调用失败重试次数有限（默认 2 次），不做无限重试。
"""
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import requests

from .config import MAX_RETRIES, REQUEST_TIMEOUT, get_config


class LLMError(RuntimeError):
    """模型调用失败（无密钥 / 网络 / 超时 / 返回异常）。"""


class LLMClient:
    """OpenAI 兼容 /chat/completions 客户端。"""

    def __init__(self, config=None, timeout: float | None = None, max_retries: int | None = None):
        self.cfg = config or get_config()
        self.timeout = timeout if timeout is not None else REQUEST_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else MAX_RETRIES
        self.call_count = 0
        self.last_error: str = ""

    @property
    def available(self) -> bool:
        return self.cfg.available

    def chat(self,
             messages: List[Dict[str, str]],
             temperature: float = 0.0,
             response_format_json: bool = True,
             max_tokens: int = 2048) -> str:
        """
        发起一次对话请求，返回 assistant 的文本内容。

        :raises LLMError: 不可用时或重试耗尽后仍失败
        """
        if not self.available:
            raise LLMError("未配置 LLM_API_KEY，当前不可调用真实模型（可继续使用演示模式）")

        url = f"{self.cfg.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}

        last_err = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    # 4xx 多为配置错误，不重试
                    if 400 <= resp.status_code < 500:
                        break
                else:
                    data = resp.json()
                    content = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    if not content:
                        last_err = "模型返回内容为空"
                    else:
                        self.call_count += 1
                        self.last_error = ""
                        return str(content)
            except requests.exceptions.Timeout:
                last_err = f"模型调用超时（>{self.timeout}s）"
            except requests.exceptions.ConnectionError:
                last_err = "无法连接模型服务（网络不可达或 BASE_URL 有误）"
            except json.JSONDecodeError:
                last_err = "模型返回不是合法 JSON"
            except Exception as exc:  # noqa: BLE001 - 兜底，避免界面崩溃
                last_err = f"模型调用异常：{type(exc).__name__}: {exc}"
            if attempt < self.max_retries:
                time.sleep(1.0 + attempt)

        self.last_error = last_err
        raise LLMError(last_err or "模型调用失败")

    def chat_json(self, messages: List[Dict[str, str]], **kwargs) -> Any:
        """调用并把返回内容解析为 JSON；解析失败抛 LLMError。"""
        from .json_utils import safe_json_loads  # 局部导入避免循环依赖
        raw = self.chat(messages, **kwargs)
        try:
            return safe_json_loads(raw)
        except ValueError as exc:
            raise LLMError(f"模型返回非法 JSON：{exc}") from exc


def make_client(config=None) -> LLMClient:
    return LLMClient(config)
