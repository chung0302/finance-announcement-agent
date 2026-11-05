# -*- coding: utf-8 -*-
"""生成报告用的系统架构图（PNG），避免 Word 里 Mermaid 无法渲染。

输出：docs/screenshots/fig6_architecture.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "fig6_architecture.png"

BLUE = "#2F6FED"
LIGHT = "#EAF2FF"
GRAY = "#5B6673"
DARK = "#1F2937"
GREEN = "#389E0D"
LGREEN = "#F6FFED"
ORANGE = "#AD6800"
LORANGE = "#FFF7E6"


def box(ax, x, y, w, h, title, sub, fc=LIGHT, ec=BLUE, tsize=11, ssize=8.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.1, edgecolor=ec, facecolor=fc))
    ax.text(x + w / 2, y + h - 0.19, title, ha="center", va="center",
            fontsize=tsize, color=DARK, fontweight="bold")
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.16, sub, ha="center", va="center",
                fontsize=ssize, color=GRAY, linespacing=1.45)


def arrow(ax, x1, y1, x2, y2, color=BLUE, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=11, linewidth=1.1,
                                 color=color, linestyle=ls,
                                 shrinkA=0, shrinkB=0))


def main() -> None:
    for font in ("Microsoft YaHei", "SimHei", "DengXian"):
        try:
            matplotlib.font_manager.findfont(font, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [font]
            break
        except Exception:  # noqa: BLE001
            continue
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(9.6, 4.5), dpi=220)
    ax.set_xlim(0, 9.6)
    ax.set_ylim(0, 4.5)
    ax.axis("off")

    # 顶部：输入
    ax.add_patch(FancyBboxPatch((0.3, 3.72), 9.0, 0.52,
                                boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.0, edgecolor=GRAY, facecolor="#F5F6F8"))
    ax.text(4.8, 3.98,
            "输入：粘贴公告文本 ／ 上传文本型 PDF、TXT ／ 一键载入演示样例",
            ha="center", va="center", fontsize=9.5, color=DARK)

    steps = [
        ("① 文本清洗", "断行合并\n去页眉页脚\n全半角统一"),
        ("② 信息抽取", "固定 JSON Schema\n数字保留原文\n失败→修复→重试"),
        ("③ 知识检索", "6 类风险规则\n15 条术语\n3 个示例"),
        ("④ 风险识别", "事实/推断/不确定\n等级：低中高\n信息不足"),
        ("⑤ 证据校验", "归一化后定位\n精确→前缀→模糊\n阈值 0.82"),
        ("⑥ 二次自检", "一致性核对\n幻觉数字检查\n删除投资建议"),
    ]
    w, h, gap, y0 = 1.34, 1.28, 0.13, 1.55
    x = 0.36
    centers = []
    for i, (t, s) in enumerate(steps):
        fc, ec = (LORANGE, ORANGE) if i == 5 else (LIGHT, BLUE)
        box(ax, x, y0, w, h, t, s, fc=fc, ec=ec)
        centers.append(x + w / 2)
        if i < len(steps) - 1:
            arrow(ax, x + w + 0.01, y0 + h / 2, x + w + gap - 0.01, y0 + h / 2)
        x += w + gap

    # 输入到第一步：折线绕行，避免虚线穿过其它步骤框
    ax.plot([4.8, 4.8], [3.70, 3.05], color=GRAY, lw=1.0, ls="--")
    ax.plot([4.8, 1.03], [3.05, 3.05], color=GRAY, lw=1.0, ls="--")
    arrow(ax, 1.03, 3.05, 1.03, y0 + h + 0.02, color=GRAY, ls="--")

    # 大模型 / 规则引擎（可选组件）
    ax.add_patch(FancyBboxPatch((0.36, 0.62), 3.05, 0.62,
                                boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.0, edgecolor=ORANGE, facecolor=LORANGE))
    ax.text(1.885, 0.99, "大语言模型（OpenAI 兼容接口）", ha="center", va="center",
            fontsize=9, color=ORANGE, fontweight="bold")
    ax.text(1.885, 0.78, "未配置密钥／调用失败 → 自动降级为规则引擎并标注",
            ha="center", va="center", fontsize=7.6, color=GRAY)

    ax.add_patch(FancyBboxPatch((3.66, 0.62), 2.55, 0.62,
                                boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.0, edgecolor=GREEN, facecolor=LGREEN))
    ax.text(4.935, 0.99, "本地知识库", ha="center", va="center",
            fontsize=9, color=GREEN, fontweight="bold")
    ax.text(4.935, 0.78, "只作判定参考，不替代原文证据",
            ha="center", va="center", fontsize=7.6, color=GRAY)

    # 虚线指向对应步骤
    arrow(ax, 1.885, 1.26, centers[1], y0 - 0.02, color=ORANGE, ls="--")
    arrow(ax, 4.935, 1.26, centers[3], y0 - 0.02, color=GREEN, ls="--")

    # 底部：输出
    ax.add_patch(FancyBboxPatch((6.36, 0.62), 2.94, 0.62,
                                boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.0, edgecolor=BLUE, facecolor="#F0F5FF"))
    ax.text(7.83, 0.99, "输出（单页 Web 界面）", ha="center", va="center",
            fontsize=9, color=BLUE, fontweight="bold")
    ax.text(7.83, 0.78, "结论·字段·风险·证据·不足提示·导出",
            ha="center", va="center", fontsize=7.6, color=GRAY)
    arrow(ax, centers[5], y0 - 0.02, 7.83, 1.26, color=BLUE, ls="--")

    # 底部标注：证据回溯
    ax.text(4.8, 0.30, "每一层结论都携带原文片段，回溯到同一条清洗后文本",
            ha="center", va="center", fontsize=8.2, color=GRAY, style="italic")

    fig.tight_layout(pad=0.15)
    fig.savefig(OUT, facecolor="white")
    plt.close(fig)
    print(f"已生成：{OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
