"""DraftEngine 表达层(国标知识库驱动)。

图框/线型/字体/箭头/标题栏常数全部查询 gbstd 知识库(GB/T 14689/4457.4/
14691/4458.4/10609.1),代码零硬编码——换标准只改 data/*.json。
"""

from datetime import datetime

from . import gbstd

# ---- 页面与图框(GB/T 14689 A4 横放,留装订边:左25 其余5) ----
PAGE_W = int(round(gbstd.px("sheets", "sizes", "A4", "h")))          # 2970
PAGE_H = int(round(gbstd.px("sheets", "sizes", "A4", "w")))          # 2100
FRAME_L = int(round(gbstd.px("sheets", "binding_margin")))           # 250
FRAME_T = FRAME_R = FRAME_B = int(round(gbstd.px("sheets", "sizes", "A4", "c")))  # 50

# ---- 图线(GB/T 4457.4:粗0.5,细=粗/2) ----
LINE_BOLD = round(gbstd.px("lines", "preferred_bold", 0), 1)          # 5px
LINE_THIN = round(LINE_BOLD / gbstd.get("lines", "bold_thin_ratio"), 1)  # 2.5px
_HID = gbstd.get("lines", "types", "hidden")
_CTR = gbstd.get("lines", "types", "center")
HIDDEN_DASH = "%g,%g" % (_HID["dash_len_w"] * LINE_THIN, _HID["gap_w"] * LINE_THIN)
CENTER_DASH = "%g,%g,%g,%g" % (_CTR["long_w"] * LINE_THIN, _CTR["gap_w"] * LINE_THIN,
                               _CTR["dot_w"] * LINE_THIN, _CTR["gap_w"] * LINE_THIN)

# ---- 字体(GB/T 14691 系列:3.5/5/7mm) ----
F_DIM = int(gbstd.px("fonts", "dimension_text"))      # 35
F_LABEL = int(gbstd.px("fonts", "view_label"))        # 50
F_TITLE = int(gbstd.px("fonts", "title_text"))        # 70
F_SMALL = int(gbstd.px("fonts", "small_text"))        # 25

# ---- 箭头与尺寸间距(GB/T 4458.4) ----
ARROW_L = round(gbstd.px("dimensions", "arrow", "len_mm"))     # 35
ARROW_W = round(gbstd.px("dimensions", "arrow", "width_mm"))   # 10
DIM_STEP = round(gbstd.px("dimensions", "spacing_mm"))         # 70

# ---- 标题栏(GB/T 10609.1:180×56mm 右下角) ----
TITLE_W = int(round(gbstd.px("titleblock", "size_mm", "w")))   # 1800
TITLE_H = int(round(gbstd.px("titleblock", "size_mm", "h")))   # 560

# 技术要求区高度(页顶)
TECH_H = 340


def fmt_dim(v):
    """尺寸格式化:整数去小数,否则保留 1 位。"""
    if abs(v - round(v)) < 0.05:
        return str(int(round(v)))
    return ("%.1f" % v).rstrip("0").rstrip(".")


ARROW_MARKER = (
    '<defs>'
    '<marker id="arrow" markerUnits="userSpaceOnUse" markerWidth="%d" markerHeight="%d" '
    'refX="%d" refY="%d" orient="auto">'
    '<path d="M0,0 L%d,%d L0,%d z" fill="black"/>'
    '</marker>'
    '</defs>'
) % (int(ARROW_L), int(ARROW_W), int(ARROW_L) - 2, int(ARROW_W) / 2,
     int(ARROW_L), int(ARROW_W) / 2, int(ARROW_W))

STYLE = (
    '.line { stroke: black; stroke-width: %g; fill: none; }\n'
    '.dim { stroke: black; stroke-width: %g; fill: none; marker-end: url(#arrow); }\n'
    '.hidden { stroke: black; stroke-width: %g; stroke-dasharray: %s; fill: none; }\n'
    '.centerline { stroke: black; stroke-width: %g; stroke-dasharray: %s; }\n'
    '.text { font-family: Arial, sans-serif; font-size: %dpx; fill: #000; }\n'
    '.title { font-family: Arial, sans-serif; font-size: %dpx; font-weight: bold; fill: #000; }\n'
) % (LINE_BOLD, LINE_THIN, LINE_THIN, HIDDEN_DASH, LINE_THIN, CENTER_DASH, F_DIM, F_TITLE)


def header(title, base):
    """SVG 头 + 图框(GB/T 14689:留装订边,装订侧 25mm 其余 5mm)。

    图名不置顶——按 GB/T 10609.1 归入标题栏。
    """
    s = '<?xml version="1.0" encoding="UTF-8"?>\n'
    s += '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" preserveAspectRatio="xMidYMid meet">\n' % (PAGE_W, PAGE_H)
    s += ARROW_MARKER + '\n'
    s += '<style>\n' + STYLE + '</style>\n'
    s += '<rect width="%d" height="%d" fill="white"/>\n' % (PAGE_W, PAGE_H)
    s += '<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="black" stroke-width="%g"/>\n' % (
        FRAME_L, FRAME_T, PAGE_W - FRAME_L - FRAME_R, PAGE_H - FRAME_T - FRAME_B, LINE_BOLD)
    return s


def tech_notes(items=None):
    """技术要求(左上角)。items: techreq.recommend 的输出;
    None 时用默认三条(兼容旧调用)。最多渲染 5 条。"""
    if not items:
        items = [{"text": "未注尺寸公差按 GB/T 1804-m"},
                 {"text": "锐边倒角 C0.5"},
                 {"text": "未注圆角 R0.5"}]
    items = items[:5]
    n = len(items)
    step = 50 if n <= 3 else (48 if n == 4 else 46)
    x, y = FRAME_L + 60, FRAME_T + 90
    s = '<text x="%d" y="%d" class="text" font-weight="bold">技术要求:</text>\n' % (x, y)
    for i, it in enumerate(items):
        s += '<text x="%d" y="%d" class="text">%d. %s</text>\n' % (
            x, y + (i + 1) * step, i + 1, it["text"])
    return s


def _cell(x, y, w, h, label, value, vsize=None):
    """标题栏单元格:细字标签 + 正文字。"""
    vsize = vsize or F_DIM
    s = '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="black" stroke-width="%g"/>\n' % (
        x, y + h, x + w, y + h, LINE_THIN) if y + h < TITLE_H else ""
    s += '<text x="%d" y="%d" class="text" font-size="%d">%s</text>\n' % (
        x + 16, y + 30, F_SMALL, label)
    s += '<text x="%d" y="%d" class="text" font-size="%d" font-weight="bold">%s</text>\n' % (
        x + 16, y + h - 22, vsize, value)
    return s


def title_block(title, base, project, material="", scale_txt="1:1"):
    """标题栏(GB/T 10609.1:180×56mm,图框右下角)。"""
    tx = PAGE_W - FRAME_R - TITLE_W
    ty = PAGE_H - FRAME_B - TITLE_H
    today = datetime.now().strftime("%Y-%m-%d")
    s = '<g transform="translate(%d, %d)">\n' % (tx, ty)
    s += '<rect width="%d" height="%d" fill="none" stroke="black" stroke-width="%g"/>\n' % (
        TITLE_W, TITLE_H, LINE_BOLD)
    # 行列网格:4 行×140px;竖线 x=400/1000/1300/1550
    for yy in (140, 280, 420):
        s += '<line x1="0" y1="%d" x2="%d" y2="%d" stroke="black" stroke-width="%g"/>\n' % (
            yy, TITLE_W, yy, LINE_THIN)
    for xx in (400, 1000, 1300, 1550):
        s += '<line x1="%d" y1="0" x2="%d" y2="%d" stroke="black" stroke-width="%g"/>\n' % (
            xx, xx, TITLE_H, LINE_THIN)
    # 左区(0-400):单位 + 幅面标识
    s += '<text x="200" y="120" class="text" font-size="%d" font-weight="bold" text-anchor="middle">Anvil</text>\n' % F_DIM
    s += '<text x="200" y="170" class="text" font-size="%d" text-anchor="middle">AI Design Tool</text>\n' % F_SMALL
    s += '<text x="200" y="380" class="text" font-size="%d" text-anchor="middle">GB/T 14689</text>\n' % F_SMALL
    s += '<text x="200" y="430" class="text" font-size="%d" text-anchor="middle">A4 横放</text>\n' % F_SMALL
    s += '<text x="200" y="510" class="text" font-size="%d" text-anchor="middle">第一角投影</text>\n' % F_SMALL
    # 中区(400-1000):图名(大) + 图号
    s += '<text x="700" y="220" class="title" text-anchor="middle">%s</text>\n' % (title or base)
    s += '<text x="700" y="330" class="text" font-size="%d" text-anchor="middle">图号 %s</text>\n' % (
        F_DIM, base or "-")
    s += '<text x="700" y="480" class="text" font-size="%d" text-anchor="middle">第一角投影法 GB/T 17452</text>\n' % F_SMALL
    # 右区(1000-1800):3 列 × 4 行参数格
    cols = (1000, 1300, 1550, 1800)
    rows = (0, 140, 280, 420, 560)
    cells = [
        ("比例", scale_txt), ("材料", material or "待定"), ("数量", "1"),
        ("重量", "—"), ("张次", "1"), ("阶段", project or "—"),
        ("设计", "Anvil"), ("审核", "—"), ("工艺", "—"),
        ("日期", today), ("单位", "mm"), ("版次", "A"),
    ]
    for i, (lab, val) in enumerate(cells):
        r, c = divmod(i, 3)
        s += _cell(cols[c], rows[r], cols[c + 1] - cols[c], 140, lab, val)
    s += '</g>\n'
    return s


def dim_h(x1, x2, y, text, extend=22):
    """水平尺寸线(GB/T 4458.4 实心箭头)。"""
    s = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x1, y, x2, y)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x1, y - extend, x1, y + extend)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x2, y - extend, x2, y + extend)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim" marker-start="url(#arrow)" marker-end="url(#arrow)"/>' % (x1, y, x2, y)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle">%s</text>' % ((x1 + x2) / 2, y - 20, text)
    return s


def dim_v(x, y1, y2, text, extend=22):
    """垂直尺寸线。"""
    s = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x, y1, x, y2)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x - extend, y1, x + extend, y1)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x - extend, y2, x + extend, y2)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim" marker-start="url(#arrow)" marker-end="url(#arrow)"/>' % (x, y1, x, y2)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle" transform="rotate(-90,%f,%f)">%s</text>' % (
        x - 24, (y1 + y2) / 2, x - 24, (y1 + y2) / 2, text)
    return s


def dim_h_seg(x1, x2, y, text, l1, l2, extend=22):
    """分段水平尺寸(孔位)。"""
    s = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim" marker-start="url(#arrow)" marker-end="url(#arrow)"/>' % (x1, y, x2, y)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (l1, y - extend, l1, y + extend)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (l2, y - extend, l2, y + extend)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle">%s</text>' % ((x1 + x2) / 2, y - 20, text)
    return s


def dim_v_seg(x, y1, y2, text, l1, l2, extend=22):
    """分段垂直尺寸(孔位)。"""
    s = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim" marker-start="url(#arrow)" marker-end="url(#arrow)"/>' % (x, y1, x, y2)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x - extend, l1, x + extend, l1)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="dim"/>' % (x - extend, l2, x + extend, l2)
    s += '<text x="%f" y="%f" class="text" text-anchor="middle" transform="rotate(-90,%f,%f)">%s</text>' % (
        x - 24, (y1 + y2) / 2, x - 24, (y1 + y2) / 2, text)
    return s


def centerline(cx, cy, r, extra=12):
    """孔中心线(十字点划线)。"""
    s = '<line x1="%f" y1="%f" x2="%f" y2="%f" class="centerline"/>' % (cx - r - extra, cy, cx + r + extra, cy)
    s += '<line x1="%f" y1="%f" x2="%f" y2="%f" class="centerline"/>' % (cx, cy - r - extra, cx, cy + r + extra)
    return s
