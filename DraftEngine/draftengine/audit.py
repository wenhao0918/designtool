"""国标合规自检:按 gbstd 知识库规则审计生成的 SVG。

与渲染层(svgparts/core)共用同一份规则数据——"按国标画"与
"按国标检"永不脱节。输出 checks 列表,汇入 meta.compliance。
"""

import re

from . import gbstd
from . import svgparts as P


def audit_svg(svg_path, scale_txt=None):
    """审计 SVG → {passed, total, checks, standards}。"""
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()
    checks = []

    def chk(name, standard, ok, detail=""):
        checks.append({"name": name, "standard": standard,
                       "ok": bool(ok), "detail": detail})

    # 1 幅面(GB/T 14689: A4 横放 297×210)
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    chk("幅面 A4 横放(297×210mm)", "GB/T 14689",
        m and int(m.group(1)) == P.PAGE_W and int(m.group(2)) == P.PAGE_H,
        "viewBox 0 0 %s %s" % (m.group(1) if m else "?", m.group(2) if m else "?"))

    # 2 图框(装订边 25mm,其余 5mm)
    fw, fh = P.PAGE_W - P.FRAME_L - P.FRAME_R, P.PAGE_H - P.FRAME_T - P.FRAME_B
    ok = re.search(r'<rect x="%d" y="%d" width="%d" height="%d"' % (
        P.FRAME_L, P.FRAME_T, fw, fh), svg) is not None
    chk("图框留装订边(左25mm 其余5mm)", "GB/T 14689", ok,
        "框 (%d,%d) %d×%d" % (P.FRAME_L, P.FRAME_T, fw, fh))

    # 3 图线:宽度集合 ⊆ 标准系列(mm 容差比较),粗:细 = 2:1
    sm = re.search(r"<style>(.*?)</style>", svg, re.S)
    widths = set()
    if sm:
        widths = {float(x) for x in
                  re.findall(r"stroke-width:\s*([\d.]+)", sm.group(1))}
    series_mm = gbstd.get("lines", "width_series")
    ratio = gbstd.get("lines", "bold_thin_ratio")
    ok = bool(widths) and all(
        any(abs(w / gbstd.PX_PER_MM - s) < 0.06 for s in series_mm)
        for w in widths)
    if ok and len(widths) == 2:
        ok = max(widths) / min(widths) == ratio
    chk("图线宽度系列 + 粗细比2:1", "GB/T 4457.4", ok,
        "widths=%s series_mm=%s" % (sorted(widths), series_mm))

    # 4 字体:全部字号 ∈ GB/T 14691 系列
    sizes = {float(x) for x in re.findall(r'font-size="([\d.]+)"', svg)}
    if sm:
        sizes |= {float(x) for x in re.findall(r"font-size:\s*([\d.]+)px", sm.group(1))}
    fseries = {round(h * gbstd.PX_PER_MM) for h in gbstd.get("fonts", "heights")}
    ok = sizes and sizes <= fseries
    chk("字号取自标准系列(3.5/5/7mm...)", "GB/T 14691", ok,
        "sizes=%s" % sorted(sizes))

    # 5 箭头:实心细长三角形,长宽比≈3.5:1
    am = re.search(r'<path d="M0,0 L(\d+),(\d+) L0,(\d+) z"', svg)
    ok = False
    ratio_txt = "-"
    if am:
        alen = float(am.group(1))
        awid = max(float(am.group(2)), float(am.group(3)))
        ratio_txt = "%.1f:1" % (alen / awid)
        ok = 3.0 <= alen / awid <= 4.5
    chk("箭头实心细长(长宽比3~4.5)", "GB/T 4458.4", ok, ratio_txt)

    # 6 第一角投影配置:俯视图在主视图下、左视图在主视图右
    labels = {}
    for mm in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>(主视图|俯视图|左视图)</text>', svg):
        labels[mm.group(3)] = (float(mm.group(1)), float(mm.group(2)))
    ok = (len(labels) == 3 and
          labels["俯视图"][1] > labels["主视图"][1] and
          labels["左视图"][0] > labels["主视图"][0])
    chk("第一角投影(俯在主下,左在主右)", "GB/T 17452", ok, str(labels))

    # 7 标题栏:180×56mm,图框右下角
    tx = P.PAGE_W - P.FRAME_R - P.TITLE_W
    ty = P.PAGE_H - P.FRAME_B - P.TITLE_H
    g = re.search(r'<g transform="translate\((\d+), (\d+)\)">', svg)
    ok = (g and int(g.group(1)) == tx and int(g.group(2)) == ty and
          re.search(r'<rect width="%d" height="%d"' % (P.TITLE_W, P.TITLE_H), svg))
    chk("标题栏180×56mm 右下角", "GB/T 10609.1", ok,
        "at (%d,%d)" % (tx, ty) if g else "未找到")

    # 8 比例:标准系列
    if scale_txt:
        ok = bool(re.match(r"^(\d+(\.\d+)?):1$", scale_txt)) or \
            bool(re.match(r"^1:\d+(\.\d+)?$", scale_txt))
        chk("比例取标准系列(%s)" % scale_txt, "GB/T 14690", ok, scale_txt)

    passed = sum(1 for c in checks if c["ok"])
    stds = sorted({c["standard"] for c in checks})
    return {"passed": passed, "total": len(checks),
            "checks": checks, "standards": stds}
