"""GB 国标知识库(工程图纸):结构化规则,数据在 data/*.json。

三层用法:
- 渲染查询:    gbstd.get("fonts", "dimension_text")     → 3.5 (mm)
- 页面像素:    gbstd.px("fonts", "dimension_text")      → 35 (px, A4 10×坐标系)
- 规则与代码分离:改 JSON 不改代码,标准换版只换数据文件。

闭环:渲染层(svgparts/core)与审计层(audit)查询同一份规则,
保证"按国标画"与"按国标检"永不脱节。
"""

import json
import os

_DIR = os.path.join(os.path.dirname(__file__), "data")
_CACHE = {}

# A4 10× px 坐标系(297mm → 2970px)
PX_PER_MM = 10.0


def sections():
    """所有知识库节(= data/*.json 文件名)。"""
    return sorted(os.path.splitext(f)[0] for f in os.listdir(_DIR)
                  if f.endswith(".json"))


def load(section):
    if section not in _CACHE:
        path = os.path.join(_DIR, section + ".json")
        if not os.path.exists(path):
            raise KeyError("国标知识库无此节: %s" % section)
        with open(path, encoding="utf-8") as f:
            _CACHE[section] = json.load(f)
    return _CACHE[section]


def get(section, *keys):
    v = load(section)
    for k in keys:
        v = v[k]
    return v


def px(section, *keys):
    """mm 值 → 页面 px(×PX_PER_MM)。"""
    return get(section, *keys) * PX_PER_MM


def snap_scale(px_scale):
    """吸附到 GB/T 14690 比例系列。

    px_scale: 当前可用像素比例(px/mm)。返回 (snap_px, "1:N" 文本)。
    取"不超出可用空间"的最大标准比例;无解时取最小(1:10)。
    """
    s = load("scales")
    cands = [(PX_PER_MM, "1:1", True)]
    for m in s["magnify_preferred"]:
        cands.append((PX_PER_MM * m, "%g:1" % m, True))
    for m in s["magnify_unpreferred"]:
        cands.append((PX_PER_MM * m, "%g:1" % m, False))
    for d in s["reduce_preferred"]:
        cands.append((PX_PER_MM / d, "1:%g" % d, True))
    for d in s["reduce_unpreferred"]:
        cands.append((PX_PER_MM / d, "1:%g" % d, False))
    # 先取能放下的最大比例;同大小时优先选"优先系列"
    best = None
    for pxv, txt, pref in sorted(cands, key=lambda c: (-c[0], not c[2])):
        if pxv <= px_scale + 1e-9:
            best = (pxv, txt)
            break
    if best is None:
        best = min(cands, key=lambda c: c[0])
        best = (best[0], best[1])
    return best


def to_markdown():
    """整库导出 markdown(喂 RAGFlow 知识库,供 AI Agent 检索)。"""
    out = ["# 工程图纸国标知识库(GB Standards)\n"]
    for sec in sections():
        d = load(sec)
        std = d.get("standard", "")
        out.append("\n## %s — %s\n" % (sec, std))
        if d.get("summary"):
            out.append(d["summary"] + "\n")
        out.append("```json\n" + json.dumps(d, ensure_ascii=False, indent=2) + "\n```")
    return "\n".join(out)
