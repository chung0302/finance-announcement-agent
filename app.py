# -*- coding: utf-8 -*-
"""
基于大语言模型的上市公司公告风险识别与解释助手 —— Streamlit 单页应用。

运行：python -m streamlit run app.py

设计约束：
- 无 API 密钥时也能正常启动（自动进入演示模式）。
- 演示模式的结果必须在界面上明确标注，不冒充模型输出。
- 上传内容只在本次会话内存中处理，不落盘、不外传（除用户主动调用模型接口外）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import PROJECT_ROOT, SAMPLES_DIR, get_config  # noqa: E402
from src.ingest import FileLoadError, load_any  # noqa: E402
from src.pipeline import Pipeline  # noqa: E402
from src.schemas import UNKNOWN  # noqa: E402

st.set_page_config(
    page_title="上市公司公告风险识别与解释助手",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ 样式
st.markdown("""
<style>
  .main-title { font-size: 26px; font-weight: 700; margin-bottom: 2px; }
  .sub-title  { color: #5b6673; font-size: 14px; margin-bottom: 14px; }
  .demo-banner {
      background:#fff7e6; border:1px solid #ffd591; border-radius:6px;
      padding:8px 12px; color:#ad6800; font-size:13px; margin-bottom:10px;
  }
  .llm-banner {
      background:#e6f4ff; border:1px solid #91caff; border-radius:6px;
      padding:8px 12px; color:#0958d9; font-size:13px; margin-bottom:10px;
  }
  .evi-ok   { background:#f6ffed; border-left:3px solid #52c41a; padding:6px 10px; margin:6px 0; font-size:13px;}
  .evi-bad  { background:#fff1f0; border-left:3px solid #ff4d4f; padding:6px 10px; margin:6px 0; font-size:13px;}
  .concl    { background:#f0f5ff; border:1px solid #d6e4ff; border-radius:6px; padding:12px 14px; font-size:16px;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">上市公司公告风险识别与解释助手</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">面向个人投资者的公告要点提取、风险提示与证据回溯 · 仅做信息分析，不预测股价、不提供投资建议</div>',
            unsafe_allow_html=True)


# ------------------------------------------------------------------ 侧栏
def sidebar() -> tuple:
    cfg = get_config()
    st.sidebar.header("运行设置")

    if cfg.available:
        st.sidebar.markdown(
            '<div class="llm-banner">已检测到模型配置，可使用真实模型模式。</div>',
            unsafe_allow_html=True)
        st.sidebar.caption(f"接口：{cfg.base_url}")
        st.sidebar.caption(f"模型：{cfg.model}")
        st.sidebar.caption(f"密钥：{cfg.masked()['api_key']}（已脱敏，不会写入任何文件）")
    else:
        st.sidebar.markdown(
            '<div class="demo-banner">未检测到 LLM_API_KEY，当前为<b>演示模式</b>：'
            '结果来自内置确定性规则与样例，不是大语言模型的真实输出。</div>',
            unsafe_allow_html=True)
        st.sidebar.caption("如需真实模型模式：复制 .env.example 为 .env 并填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，重启应用。")

    mode = st.sidebar.radio(
        "分析模式",
        options=["auto", "llm", "demo"],
        format_func=lambda x: {"auto": "自动（有密钥用模型，否则演示）",
                               "llm": "强制真实模型",
                               "demo": "强制演示模式"}[x],
        index=0,
        help="强制真实模型时若无密钥会自动降级为演示模式，并在结果中给出提示。",
    )
    st.sidebar.markdown("---")
    st.sidebar.subheader("载入演示样例")
    st.sidebar.caption("课堂演示建议直接用样例，避免现场临时粘贴长文本。")
    return mode, cfg


def load_sample_names() -> list:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(p.name for p in SAMPLES_DIR.glob("*.txt"))


mode, cfg = sidebar()

sample_names = load_sample_names()


def _load_sample(name: str) -> None:
    """把样例内容写进输入框（text_area 的 key = ta_input）。"""
    path = SAMPLES_DIR / name
    if path.exists():
        st.session_state["ta_input"] = path.read_text(encoding="utf-8")
        # 换样例即视为新的一次输入，清掉上一份 PDF 的分页信息
        st.session_state["uploaded_pages"] = None
        st.session_state["uploaded_name"] = ""


def _on_pick_sample() -> None:
    picked = st.session_state.get("sel_sample", "（不使用）")
    if picked != "（不使用）":
        _load_sample(picked)


sample_pick = st.sidebar.selectbox(
    "选择样例文件",
    options=["（不使用）"] + sample_names,
    index=0,
    key="sel_sample",
    on_change=_on_pick_sample,
)

quick_good = st.sidebar.button("▶ 载入利好样例（业绩预增）", width="stretch")
quick_risk = st.sidebar.button("▶ 载入风险样例（股东减持）", width="stretch")

if quick_good:
    _load_sample("demo_001_positive_earnings_up.txt")
if quick_risk:
    _load_sample("demo_002_risk_share_reduction.txt")

st.sidebar.markdown("---")
st.sidebar.caption("数据仅在本次浏览器会话内处理，不会写入磁盘，也不会上传到无关服务。")

# ------------------------------------------------------------------ URL 预填
# 支持 ?sample=<文件名>&autorun=1 直接打开结果页，便于课堂演示与自动截图。
_qp = st.query_params
_url_sample = _qp.get("sample", "") if hasattr(_qp, "get") else ""
_url_autorun = str(_qp.get("autorun", "")) if hasattr(_qp, "get") else ""
if isinstance(_url_sample, list):
    _url_sample = _url_sample[0] if _url_sample else ""
if isinstance(_url_autorun, list):
    _url_autorun = _url_autorun[0] if _url_autorun else ""
if _url_sample:
    _p = SAMPLES_DIR / _url_sample
    if _p.exists() and not st.session_state.get("ta_input"):
        st.session_state["ta_input"] = _p.read_text(encoding="utf-8")

# ------------------------------------------------------------------ 输入区
# 统一以 ta_input 作为输入框的唯一数据源，避免「按钮载入后文本框不刷新」。
if "ta_input" not in st.session_state:
    st.session_state["ta_input"] = ""


def _on_text_edit() -> None:
    """用户手动改动文本后，上一份 PDF 的分页信息不再适用。"""
    st.session_state["uploaded_pages"] = None
    st.session_state["uploaded_name"] = ""


tab_paste, tab_upload = st.tabs(["① 粘贴公告文本", "② 上传 PDF / TXT"])

# 先处理上传（此时输入框尚未实例化，可安全写入 session_state），
# 再渲染粘贴框，使上传结果能立即显示在文本框中。
with tab_upload:
    up = st.file_uploader("选择一个文件（仅支持文本型 PDF 与 TXT；扫描件不做 OCR）",
                          type=["pdf", "txt", "md"], key="fu")
    if up is not None:
        data = up.getvalue()
        sig = f"{up.name}:{len(data)}"
        if st.session_state.get("upload_sig") != sig:
            st.session_state["upload_sig"] = sig
            try:
                raw, pages = load_any(up.name, data)
                st.session_state["ta_input"] = raw
                st.session_state["uploaded_pages"] = pages
                st.session_state["uploaded_name"] = up.name
            except FileLoadError as exc:
                st.session_state["ta_input"] = ""
                st.session_state["uploaded_pages"] = None
                st.error(f"文件读取失败：{exc}")
            except Exception as exc:  # noqa: BLE001
                st.session_state["ta_input"] = ""
                st.session_state["uploaded_pages"] = None
                st.error(f"文件读取出现未预期错误：{type(exc).__name__}: {exc}")
    if st.session_state.get("uploaded_name"):
        cur = st.session_state.get("ta_input", "")
        st.success(f"已读取 {st.session_state['uploaded_name']}：{len(cur)} 字符")
        with st.expander("查看提取到的原文（前 1500 字）"):
            st.text(cur[:1500])

with tab_paste:
    text_input = st.text_area(
        "把公告正文粘贴到这里（支持带页眉页脚、断行的原始文本）",
        height=260,
        key="ta_input",
        on_change=_on_text_edit,
        placeholder="例如：证券代码：xxxxxx  证券简称：xxxx  公告编号：2026-001 ...",
    )

uploaded_pages = st.session_state.get("uploaded_pages")

run_clicked = st.button("🚀 开始分析", type="primary", width="stretch")
# 通过 ?sample=xxx&autorun=1 打开时自动跑一次，便于演示与截图
if _url_sample and _url_autorun in ("1", "true", "True"):
    run_clicked = True

# ------------------------------------------------------------------ 分析
if run_clicked:
    raw_text = text_input or ""
    if not raw_text or not raw_text.strip():
        st.warning("输入为空：请先粘贴公告文本、上传文件，或点击左侧『载入演示样例』。")
        st.stop()

    with st.spinner("正在分析：文本清洗 → 信息抽取 → 知识检索 → 风险识别 → 证据校验 → 二次自检 …"):
        t0 = time.time()
        try:
            pipeline = Pipeline(mode=mode)
            result = pipeline.run(raw_text, pages=uploaded_pages)
        except Exception as exc:  # noqa: BLE001
            st.error(f"分析过程出错：{type(exc).__name__}: {exc}")
            st.stop()
    st.session_state["result"] = result
    st.session_state["src_name"] = st.session_state.get("uploaded_name") or "粘贴文本"
    st.success(f"分析完成，用时 {time.time() - t0:.2f} 秒。")

result = st.session_state.get("result")
if result is None:
    st.info("👈 先在左侧载入样例或粘贴公告文本，然后点击『开始分析』。")
    st.stop()

# ------------------------------------------------------------------ 结果展示
if result.mode == "demo":
    st.markdown('<div class="demo-banner">⚠️ <b>演示模式</b>：以下结果由内置确定性规则与样例生成，'
                '<b>不是大语言模型的真实输出</b>，请勿当作模型效果引用。</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="llm-banner">✅ 真实模型模式（{result.model_name}），'
                f'模型调用 {result.llm_calls} 次。</div>', unsafe_allow_html=True)

for w in result.warnings:
    st.caption("· " + w)

c1, c2, c3, c4 = st.columns(4)
c1.metric("整体风险等级", result.overall_risk_level.value)
c2.metric("整体置信度", f"{result.overall_confidence:.2f}")
c3.metric("已验证证据 / 未通过校验", f"{len(result.evidence_verified)} / {len(result.evidence_unverified)}")
c4.metric("处理用时", f"{result.elapsed_seconds:.2f} s")

st.markdown("### 一句话结论")
st.markdown(f'<div class="concl">{result.facts.summary_sentence or UNKNOWN}</div>', unsafe_allow_html=True)

st.markdown("### 结构化抽取结果")
f = result.facts
st.table({
    "字段": ["公司名称", "公告标题", "公告日期", "证券代码", "事件类型", "识别到的指标数"],
    "值": [str(f.company_name), str(f.announcement_title), str(f.announcement_date),
           str(f.stock_code), "、".join(t.value for t in f.event_types) or UNKNOWN,
           str(len(f.metrics))],
})

if f.metrics:
    st.markdown("#### 关键指标与金额")
    rows = []
    for m in f.metrics:
        rows.append({
            "指标": m.name,
            "数值（原文写法）": m.value,
            "同比/变化": m.yoy_change,
            "证据校验": "✅ 已验证" if m.evidence.matched else "❌ 未通过校验",
            "相似度": f"{m.evidence.score:.2f}",
        })
    # 统一转成字符串再交给 Arrow 序列化，避免数值/文本混排导致的类型推断报错
    st.dataframe(pd.DataFrame(rows).astype(str), width="stretch", hide_index=True)
else:
    st.info("未抽取到关键金额或指标（记为『未披露』）。")

st.markdown("### 风险识别")
if not result.risks:
    st.info("未识别出既定风险类型（等级：信息不足），建议人工阅读原文。")
for i, r in enumerate(result.risks, 1):
    color = {"高": "🔴", "中": "🟠", "低": "🟢", "信息不足": "⚪"}.get(r.risk_level.value, "⚪")
    with st.expander(f"{color} {i}. {r.risk_type.value} —— 风险等级：{r.risk_level.value}（置信度 {r.confidence:.2f}）",
                     expanded=(i == 1)):
        st.markdown(f"**风险原因**：{r.reason or UNKNOWN}")
        if r.facts:
            st.markdown("**原文事实**（原文直接写明）：")
            for x in r.facts:
                st.markdown(f"- {x}")
        if r.inferences:
            st.markdown("**推断**（非原文直述）：")
            for x in r.inferences:
                st.markdown(f"- {x}")
        if r.uncertainties:
            st.markdown("**不确定性**：")
            for x in r.uncertainties:
                st.markdown(f"- {x}")
        if r.evidence.quote:
            if r.evidence.matched:
                st.markdown(f'<div class="evi-ok"><b>已验证证据</b>（{r.evidence.match_method}，'
                            f'相似度 {r.evidence.score:.2f}）<br>{r.evidence.quote}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="evi-bad"><b>未通过校验</b>（{r.evidence.match_method}，'
                            f'相似度 {r.evidence.score:.2f}）—— 不得作为有效依据<br>{r.evidence.quote}</div>',
                            unsafe_allow_html=True)
        else:
            st.markdown('<div class="evi-bad">本条结论<b>缺少证据</b>，未通过证据校验，已按规则降级处理。</div>',
                        unsafe_allow_html=True)
        if r.need_human_review:
            st.warning("该条已标记：需人工复核。")

st.markdown("### 原文证据清单")
st.caption("『已验证』指该片段可在清洗后的公告原文中定位；『未通过校验』指无法定位，界面不做为依据展示。")
for e in result.evidence_verified:
    st.markdown(f'<div class="evi-ok">✅ {e.quote}<br><span style="color:#5b6673">说明：{e.note}</span></div>',
                unsafe_allow_html=True)
for e in result.evidence_unverified:
    st.markdown(f'<div class="evi-bad">❌ {e.quote or "（空证据）"}<br>'
                f'<span style="color:#5b6673">说明：{e.note}</span></div>', unsafe_allow_html=True)
if not result.evidence_verified and not result.evidence_unverified:
    st.info("本次没有产生任何证据条目。")

st.markdown("### 信息不足提示")
if result.missing_info:
    for m in result.missing_info:
        st.markdown(f"- {m}")
else:
    st.markdown("- 无")

st.markdown("### 二次自检")
if result.self_check_passed:
    st.success("自检通过：未发现严重问题。")
else:
    st.warning("自检发现严重问题，已按规则降级/删除处理，详见下表。")
if result.self_check_issues:
    _issues = [{"字段": i.field_name, "问题": i.issue, "处理动作": i.action, "级别": i.severity}
               for i in result.self_check_issues]
    st.dataframe(pd.DataFrame(_issues).astype(str), width="stretch", hide_index=True)

# ------------------------------------------------------------------ 导出
st.markdown("### 导出")
dl1, dl2 = st.columns(2)
md_text = result.to_markdown()
json_text = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
with dl1:
    st.download_button("⬇️ 导出 Markdown 报告", data=md_text.encode("utf-8"),
                       file_name="announcement_risk_report.md", mime="text/markdown",
                       width="stretch")
with dl2:
    st.download_button("⬇️ 导出 JSON 结果", data=json_text.encode("utf-8"),
                       file_name="announcement_risk_result.json", mime="application/json",
                       width="stretch")

with st.expander("查看 JSON 结果（前 3000 字符）"):
    st.code(json_text[:3000], language="json")

st.markdown("---")
st.caption("免责声明：本工具仅用于财经文本的信息提取与风险提示，不预测股票价格，"
           "不构成任何买入、卖出或持有建议。分析结果可能存在错误，投资决策请以公司正式披露文件为准。")
