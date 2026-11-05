# -*- coding: utf-8 -*-
"""
模型接口连通性检查（不会打印完整密钥）。

用法：
    python tools/check_llm.py

它做三件事：
1. 读出当前 LLM_BASE_URL / LLM_MODEL / 密钥（脱敏显示）；
2. 真实发一次极短的请求（不使用任何公告数据）；
3. 把常见错误翻译成人话：401 密钥错、404 模型名错、余额不足、网络不通。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_config  # noqa: E402
from src.llm_client import LLMError, make_client  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = get_config()

    print("接口地址：", cfg.base_url)
    print("模型名称：", cfg.model)
    print("密钥（脱敏）：", cfg.masked()["api_key"] or "（空）")
    print("-" * 46)

    if not cfg.available:
        print("结果：未检测到 LLM_API_KEY，应用会以「演示模式」启动。")
        print("处理：把 .env.example 复制为 .env，填好三项后重新运行本脚本。")
        return 2

    client = make_client(cfg)
    t0 = time.time()
    try:
        # DeepSeek 等国内接口在启用 json_object 模式时，要求提示词里出现 "json" 字样
        out = client.chat(
            [{"role": "user", "content": '请用 JSON 回复：{"status":"ok"}'}],
            temperature=0.0,
        )
    except LLMError as exc:
        print(f"结果：调用失败（{time.time() - t0:.1f}s）")
        print("错误：", exc)
        msg = str(exc)
        tips = []
        if "401" in msg or "Unauthorized" in msg or "无效" in msg or "auth" in msg.lower():
            tips.append("密钥不正确或已被删除 → 重新复制完整的 key（通常 sk- 开头）")
        if "404" in msg or "model" in msg.lower():
            tips.append("模型名不对 → DeepSeek 填 deepseek-chat，通义填 qwen-plus，Kimi 填 moonshot-v1-8k")
        if "402" in msg or "余额" in msg or "quota" in msg.lower():
            tips.append("余额不足 → 去平台充值（几元即可，本项目的评测只需几毛钱）")
        if "Timeout" in msg or "timed out" in msg or "Connection" in msg:
            tips.append("网络不通或超时 → 检查是否开了代理/VPN，或换一个网络")
        if "base_url" in msg.lower() or "URL" in msg:
            tips.append("地址不对 → 末尾不要带 /chat/completions，正确形式如 https://api.deepseek.com/v1")
        if not tips:
            tips.append("把上面的错误原文发给我，我帮你判断")
        for t in tips:
            print("可能原因：", t)
        return 1

    print(f"结果：连通成功（{time.time() - t0:.2f}s）")
    print("模型返回：", (out or "").strip()[:60])
    print("-" * 46)
    print("下一步：重新启动应用（双击 start.bat），侧栏会显示蓝色「真实模型模式」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
