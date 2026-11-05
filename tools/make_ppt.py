# -*- coding: utf-8 -*-
"""
生成答辩 PPT（可编辑 .pptx）。

与 docs/presentation_outline.md 一一对应：
30秒背景 + 1分钟架构 + 2分钟演示 + 1分钟评测 + 30秒局限与收获。
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "slides.pptx"

FONT = "微软雅黑"
ACCENT = RGBColor(0x2F, 0x6F, 0xED)
DARK = RGBColor(0x1F, 0x2A, 0x37)
GRAY = RGBColor(0x5B, 0x66, 0x73)
ORANGE = RGBColor(0xD4, 0x6B, 0x08)
GREEN = RGBColor(0x23, 0x8B, 0x45)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF2, 0xF5, 0xFA)


def add_blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def set_font(run, size: int, bold: bool = False, color: RGBColor = DARK, font: str = FONT):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    # 中文字体需同时设置 east_asian 才生效
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}" + tag.split(":")[1])
        if el is None:
            from pptx.oxml.ns import qn
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", font)


def textbox(slide, left, top, width, height, text, size=18, bold=False,
            color=DARK, align=PP_ALIGN.LEFT, line=1.35):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line
        run = p.add_run()
        run.text = ln
        set_font(run, size, bold, color)
    return box


def bullets(slide, left, top, width, height, items, size=16, color=DARK):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.4
        p.space_after = Pt(6)
        run = p.add_run()
        run.text = "• " + it
        set_font(run, size, False, color)
    return box


def title_bar(slide, title, sub=""):
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.333), Inches(1.05))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    tf = bar.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.alignment = PP_ALIGN.LEFT
    set_font(p.runs[0], 26, True, WHITE)
    if sub:
        textbox(slide, 0.5, 1.12, 12.4, 0.45, sub, size=14, color=GRAY)


def footer(slide, text):
    textbox(slide, 0.5, 6.95, 12.4, 0.35, text, size=11, color=GRAY)


def para(tf, text: str, size: int = 14, bold: bool = False,
         color: RGBColor = DARK, align=None):
    """追加一个段落并显式创建 run（空文本也要有 run，否则 set_font 会越界）。"""
    p = tf.add_paragraph()
    if align is not None:
        p.alignment = align
    run = p.add_run()
    run.text = text
    set_font(run, size, bold, color)
    return p


def build() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ---------------- 1 封面
    s = add_blank(prs)
    bg = s.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = ACCENT
    bg.line.fill.background()
    textbox(s, 0.9, 2.1, 11.5, 1.0,
            "基于大语言模型的上市公司公告风险识别与解释助手",
            size=36, bold=True, color=WHITE)
    textbox(s, 0.9, 3.25, 11.5, 0.6,
            "面向个人投资者的公告要点提取、风险提示与证据回溯",
            size=20, color=RGBColor(0xD6, 0xE4, 0xFF))
    textbox(s, 0.9, 4.5, 11.5, 1.2,
            "课程：财经智能体开发与应用\n"
            "学号【请填写】　姓名【请填写】　专业【请填写】",
            size=16, color=RGBColor(0xD6, 0xE4, 0xFF), line=1.6)
    textbox(s, 0.9, 6.3, 11.5, 0.4,
            "本工具仅做信息提取与风险提示，不预测股价、不提供投资建议",
            size=13, color=RGBColor(0xBF, 0xD3, 0xFF))

    # ---------------- 2 问题背景（30秒）
    s = add_blank(prs)
    title_bar(s, "一、问题背景（30 秒）", "公告太长看不懂，直接问大模型又不可靠")
    bullets(s, 0.6, 1.75, 12.1, 4.6, [
        "现实痛点：公告动辄数千字，术语多、数字多，人工很难快速抓住「谁、什么时候、发生了什么、金额多少」。",
        "直接问大模型的两个坑：① 遗漏关键数字，把「2.10 亿元、同比增长 100%」写成「业绩大幅增长」；"
        "② 生成原文没有的内容（幻觉），如凭印象补证券代码。",
        "更危险的是：这些答案看起来都很确定，普通读者无法分辨。",
        "本作品定位：不是「问答框」，而是带证据回溯的流水线；不做股价预测、不给买卖建议。",
    ], size=17)
    box = s.shapes.add_shape(1, Inches(0.6), Inches(5.55), Inches(12.1), Inches(0.95))
    box.fill.solid()
    box.fill.fore_color.rgb = LIGHT
    box.line.fill.background()
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "核心主张：不知道就说「信息不足」，比编一个确定答案更有价值。"
    set_font(p.runs[0], 18, True, ACCENT)
    footer(s, "对应文档：README · docs/limitations.md")

    # ---------------- 3 系统架构（1分钟）
    s = add_blank(prs)
    title_bar(s, "二、系统架构（1 分钟）", "六步流水线，每步可单独测试")
    steps = [
        ("① 文本清洗", "合并断行、删页眉页脚\n统一全半角", "排版噪声"),
        ("② 信息抽取", "固定 JSON Schema\n数字保留原文写法", "自由发挥/单位换算"),
        ("③ 知识检索", "6 类风险规则 + 术语\n+ 3 个示例（离线）", "标准藏在模型里"),
        ("④ 风险识别", "事实 / 推断 / 不确定性\n三段式输出", "把猜测当事实"),
        ("⑤ 证据校验", "归一化后回原文定位\n相似度 ≥ 0.82", "无依据结论"),
        ("⑥ 二次自检", "一致性核对\n投资建议清理", "数字张冠李戴"),
    ]
    left = 0.45
    width = 2.02
    for i, (t, d, f) in enumerate(steps):
        card = s.shapes.add_shape(1, Inches(left + i * (width + 0.12)), Inches(1.75),
                                  Inches(width), Inches(2.5))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT
        card.line.color.rgb = ACCENT
        tf = card.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = t
        p.alignment = PP_ALIGN.CENTER
        set_font(p.runs[0], 17, True, ACCENT)
        for ln in d.split("\n"):
            pp = tf.add_paragraph()
            pp.text = ln
            pp.alignment = PP_ALIGN.CENTER
            set_font(pp.runs[0], 13, False, DARK)
        pp = tf.add_paragraph()
        pp.text = "防：" + f
        pp.alignment = PP_ALIGN.CENTER
        set_font(pp.runs[0], 12, True, ORANGE)
    bullets(s, 0.6, 4.5, 12.1, 2.2, [
        "知识库只作判定参考，是否成立必须有原文证据 —— 这条边界写死在提示词与代码里。",
        "公告文本视为不可信数据：定界符包裹 + 定界符转义 + 系统消息声明，三重隔离防注入。",
        "无 API 密钥时自动进入演示模式并强制标注；模型超时或返回非法 JSON 只降级，不崩溃。",
    ], size=15)
    footer(s, "对应文档：docs/architecture.md（含 Mermaid 图）")

    # ---------------- 4 关键机制
    s = add_blank(prs)
    title_bar(s, "三、关键机制：怎么防幻觉", "三层约束，而不是「提示词里说一句别编造」")
    items = [
        ("第一层 · 固定 Schema", "只能输出约定字段；未知必须填「未披露 / 信息不足」；"
                                 "数值保留原文写法（禁止 1.2 亿元 → 120000000）。"),
        ("第二层 · 证据校验", "每条结论必须带原文片段；片段与清洗后原文各自归一化"
                              "（全半角、空白、标点），依次精确包含 → 前缀 → 模糊匹配，阈值 0.82。"),
        ("第三层 · 二次自检", "核对公司名/日期/金额/事件是否与原文一致；结论里的数字能否在证据中找到；"
                              "命中「建议买入/卖出/目标价」即删除。"),
        ("三层都失败时", "结论降级为「信息不足」、置信度下调、强制标记人工复核；"
                         "被标为「原文事实」的表述降级为「推断」。"),
    ]
    top = 1.7
    for i, (t, d) in enumerate(items):
        card = s.shapes.add_shape(1, Inches(0.6), Inches(top + i * 1.28), Inches(12.1), Inches(1.12))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT if i < 3 else RGBColor(0xFF, 0xF1, 0xF0)
        card.line.fill.background()
        tf = card.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = t
        set_font(p.runs[0], 16, True, ACCENT if i < 3 else RGBColor(0xC0, 0x2A, 0x2A))
        pp = tf.add_paragraph()
        pp.text = d
        set_font(pp.runs[0], 13, False, DARK)
    footer(s, "对应测试：tests/test_evidence_checker.py · tests/test_risk_level.py")

    # ---------------- 5 演示一
    s = add_blank(prs)
    title_bar(s, "四、现场演示 ① 利好样例（约 50 秒）",
              "《星海智能科技股份有限公司 2026 年半年度业绩预告》")
    bullets(s, 0.6, 1.7, 6.0, 4.8, [
        "操作：侧栏「▶ 载入利好样例」→「🚀 开始分析」",
        "事件类型：业绩预增或扭亏",
        "整体风险等级：中（置信度 0.50）—— 业绩翻倍不等于没风险",
        "关键指标：归母净利润 2.10 亿元、扣非 1.96 亿元、营收 18.60 亿元、非经常性损益 1400 万元",
        "证据状态：已验证 8 / 未通过 0（绿色，相似度 1.00）",
        "仍会提示：预告数据未经审计、非经常性损益占比未拆开",
        "用时约 13 秒（3 次模型调用 + 证据校验）",
    ], size=15)
    box = s.shapes.add_shape(1, Inches(6.9), Inches(1.7), Inches(5.8), Inches(4.8))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xF6, 0xFF, 0xED)
    box.line.color.rgb = GREEN
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "这一页要讲的重点"
    set_font(p.runs[0], 16, True, GREEN)
    for ln in ["系统不会盲目乐观：",
               "即便是利好公告，也会把「公告没说清楚的地方」",
               "明确写进「不确定性」，而不是一味说好话。",
               "",
               "每条金额后面都挂着原文片段，",
               "并且是系统自己回原文比对通过的，",
               "不是模型自己声称的。"]:
        para(tf, ln, 14, False, DARK)
    footer(s, "对应文档：docs/demo_script.md 第 2 段")

    # ---------------- 6 演示二
    s = add_blank(prs)
    title_bar(s, "四、现场演示 ② 风险样例（约 70 秒）",
              "《华岭新材料股份有限公司 关于控股股东减持股份计划的公告》")
    bullets(s, 0.6, 1.7, 6.0, 4.8, [
        "操作：侧栏「▶ 载入风险样例」→「🚀 开始分析」",
        "事件类型：股东或高管减持 ＋ 重大诉讼或仲裁（命中两个）",
        "减持：等级「高」（置信度 0.65）—— 主体是控股股东，比例 1.5% > 1% 参考线",
        "诉讼：等级「信息不足」（置信度 0.35）—— 涉案金额占净资产比例未披露",
        "信息不足提示 9 条，其中两条带「需人工复核」",
        "证据：绿色「已验证」，相似度 1.00",
    ], size=15)
    box = s.shapes.add_shape(1, Inches(6.9), Inches(1.7), Inches(5.8), Inches(4.8))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0xF1, 0xF0)
    box.line.color.rgb = RGBColor(0xC0, 0x2A, 0x2A)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "这一页要讲的重点"
    set_font(p.runs[0], 16, True, RGBColor(0xC0, 0x2A, 0x2A))
    for ln in ["系统不会硬编结论：",
               "「1.5%」不是写死的，是从原文抽出来的；",
               "「控股股东」这个身份也来自原文。",
               "两者共同触发知识库里的升级规则。",
               "",
               "诉讼那条因为关键比例没披露，",
               "系统选择写「信息不足」并标记人工复核，",
               "而不是在「低/中/高」里硬选一个。"]:
        para(tf, ln, 14, False, DARK)
    footer(s, "对应文档：docs/demo_script.md 第 3 段")

    # ---------------- 7 评测设计
    s = add_blank(prs)
    title_bar(s, "五、评测设计（1 分钟）", "A/B 对照，脚本可复现")
    left = s.shapes.add_shape(1, Inches(0.6), Inches(1.75), Inches(5.85), Inches(2.7))
    left.fill.solid()
    left.fill.fore_color.rgb = LIGHT
    left.line.fill.background()
    tf = left.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "A · 普通大模型直接总结"
    set_font(p.runs[0], 17, True, GRAY)
    for ln in ["无 Schema、无知识库、无证据校验",
               "提示词：prompts/baseline_summary.md",
               "还原「把公告丢给模型问一句」的常见用法"]:
        pp = tf.add_paragraph()
        pp.text = "• " + ln
        set_font(pp.runs[0], 14, False, DARK)

    right = s.shapes.add_shape(1, Inches(6.85), Inches(1.75), Inches(5.85), Inches(2.7))
    right.fill.solid()
    right.fill.fore_color.rgb = RGBColor(0xE8, 0xF0, 0xFF)
    right.line.color.rgb = ACCENT
    tf = right.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "B · 本作品工作流"
    set_font(p.runs[0], 17, True, ACCENT)
    for ln in ["结构化抽取 + 知识库 + 证据校验 + 二次自检",
               "提示词：extraction / risk_analysis / self_check",
               "每条结论必须可回溯到原文"]:
        pp = tf.add_paragraph()
        pp.text = "• " + ln
        set_font(pp.runs[0], 14, False, DARK)

    textbox(s, 0.6, 4.7, 12.1, 0.4, "五项指标", size=17, bold=True, color=DARK)
    bullets(s, 0.6, 5.15, 12.1, 1.7, [
        "风险类型识别准确率（完全匹配率 / 至少命中率）　·　关键数字提取正确率（按标注数字召回计算）",
        "引用覆盖率（已验证证据 / 全部证据）　·　无依据结论率（无证据结论 / 全部结论）　·　平均响应时间",
        "命令：python evaluations/evaluate.py --mode demo | --mode llm　→　CSV / JSON / 柱状图",
    ], size=14)
    footer(s, "产物：evaluations/results/ per_sample_results.csv · comparison.csv · metrics_summary.json · comparison_chart.png")

    # ---------------- 8 评测结果（如实）
    s = add_blank(prs)
    title_bar(s, "五、评测结果（如实汇报）", "deepseek-chat · 14 个合成样本 · 温度 0 · 2026-11-04 实测")
    rows = [("指标", "A 普通大模型直接总结", "B 本作品工作流"),
            ("风险类型识别准确率（完全匹配）", "0.79", "1.00"),
            ("关键数字提取正确率", "1.00", "0.92（本期口径 0.98）"),
            ("引用覆盖率", "0.00", "1.00"),
            ("无依据结论率", "1.00", "0.00"),
            ("平均响应时间", "2.05 秒", "11.56 秒")]
    table = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.75),
                               Inches(12.1), Inches(3.3)).table
    table.columns[0].width = Inches(5.0)
    table.columns[1].width = Inches(4.0)
    table.columns[2].width = Inches(3.1)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            cell.text = val
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if c else PP_ALIGN.LEFT
            set_font(p.runs[0], 14 if r else 15, bool(r == 0),
                     WHITE if r == 0 else DARK)
            cell.fill.solid()
            cell.fill.fore_color.rgb = ACCENT if r == 0 else (WHITE if r % 2 else LIGHT)
    warn = s.shapes.add_shape(1, Inches(0.6), Inches(5.25), Inches(12.1), Inches(1.4))
    warn.fill.solid()
    warn.fill.fore_color.rgb = RGBColor(0xFF, 0xF7, 0xE6)
    warn.line.color.rgb = RGBColor(0xFF, 0xD5, 0x91)
    tf = warn.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "必须同时说明（这三句不要省）"
    set_font(p.runs[0], 15, True, ORANGE)
    for ln in ["① 数字召回 A 反而更好（1.00 对 0.92）：A 把数字全列一遍，B 按设计只抽本期值，53 个标注数字里只漏 1 个；",
               "② B 买到的是「每条结论都能回到原文」：74 条证据全部通过校验，代价是慢 5.6 倍；",
               "③ 报告里修正过两处评分口径（A 的自由文本标签、标注里的年份与千分位），两处都让 B 的数字变差。"]:
        pp = tf.add_paragraph()
        pp.text = ln
        set_font(pp.runs[0], 12, False, RGBColor(0xAD, 0x68, 0x00))
    footer(s, "对应文档：docs/limitations.md 第 5 节 · evaluations/results/comparison.csv")

    # ---------------- 9 局限与收获
    s = add_blank(prs)
    title_bar(s, "六、局限与收获（30 秒）", "主动讲局限，比事后被追问更稳妥")
    lb = s.shapes.add_shape(1, Inches(0.6), Inches(1.75), Inches(5.85), Inches(4.6))
    lb.fill.solid()
    lb.fill.fore_color.rgb = RGBColor(0xFF, 0xF1, 0xF0)
    lb.line.fill.background()
    tf = lb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "局限（4 条）"
    set_font(p.runs[0], 17, True, RGBColor(0xC0, 0x2A, 0x2A))
    for ln in ["1. 样本为合成文本，14 份，非真实公告，指标系统性偏高",
               "2. 规则只覆盖 6 类风险，长尾事项落入「其他/未识别」",
               "3. 扫描件 PDF 不做 OCR；长公告截断至 12000 字",
               "4. 证据匹配基于字符相似度，大幅改写仍可能误判"]:
        pp = tf.add_paragraph()
        pp.text = ln
        set_font(pp.runs[0], 14, False, DARK)

    rb = s.shapes.add_shape(1, Inches(6.85), Inches(1.75), Inches(5.85), Inches(4.6))
    rb.fill.solid()
    rb.fill.fore_color.rgb = RGBColor(0xF6, 0xFF, 0xED)
    rb.line.fill.background()
    tf = rb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "收获（3 条）"
    set_font(p.runs[0], 17, True, GREEN)
    for ln in ["1. 财经场景里，「不知道」本身就是有价值的产品能力",
               "2. 工业界智能体靠「工作流 + 校验」，不是一次调用",
               "3. 评测诚实性：B 在数字召回上输给 A，照实写出来",
               "",
               "【请填写：你个人的一点体会】"]:
        para(tf, ln, 14, False, DARK)
    footer(s, "对应文档：docs/limitations.md · docs/qa_defense.md")

    # ---------------- 10 结束
    s = add_blank(prs)
    bg = s.shapes.add_shape(1, Inches(0), Inches(0), prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = ACCENT
    bg.line.fill.background()
    textbox(s, 0.9, 1.6, 11.5, 0.7, "总结", size=32, bold=True, color=WHITE)
    textbox(s, 0.9, 2.6, 11.5, 2.6,
            "这个作品做了三件事：\n"
            "① 把长公告变成结构化字段；\n"
            "② 把风险判断与原文证据绑定；\n"
            "③ 把不知道的部分明确说出来。",
            size=22, color=WHITE, line=1.7)
    textbox(s, 0.9, 5.3, 11.5, 1.2,
            "它不做股价预测，也不给买卖建议 —— 自检环节发现这类措辞会直接删除。\n"
            "欢迎老师和同学提问。",
            size=17, color=RGBColor(0xD6, 0xE4, 0xFF), line=1.6)
    textbox(s, 0.9, 6.6, 11.5, 0.4,
            "免责声明：本工具仅用于财经文本的信息提取与风险提示，不构成任何投资建议。",
            size=12, color=RGBColor(0xBF, 0xD3, 0xFF))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"PPT 已生成：{OUT}（共 {len(prs.slides._sldIdLst)} 页）")


if __name__ == "__main__":
    build()
