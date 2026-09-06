"""DraftEngine —— 3D 模型 → 工程图纸(工程画图)。

独立的 STEP/模型 → 工程图纸工具:
- 几何事实来自成熟内核(FreeCAD OCC:STEP 解析、BoundBox、圆柱面、投影)
- 表达层完全自研 SVG(图框/标题栏/尺寸/箭头/中心线/隐藏线)
- 输出人类可看的图纸(SVG)+ 机器/AI 可解析的结构化 meta(JSON)

用法:
    from draftengine import generate_drawing
    r = generate_drawing("part.step", "/tmp", title="底板", project="P1")
    # r = {"svg": "/tmp/part_drawing.svg", "pdf": None, "meta": {...}}
"""

from .core import generate_drawing, __version__
from .geometry import HAS_FREECAD

__all__ = ["generate_drawing", "HAS_FREECAD", "__version__"]
