"""
SVG 生成器 — 从 Sketch 导出规范 SVG

适用于专利附图和技术文档，输出干净、可编辑的 SVG
"""
from .elements import (
    Sketch, Line, Rect, Circle, Arc, Polyline, Arrow,
    Dimension, Hinge, Spring, Text, Point
)
import math


def _style_str(style: dict) -> str:
    s = f'stroke="{style.get("stroke", "#000")}" stroke-width="{style.get("stroke_width", 1.5)}"'
    fill = style.get("fill", "none")
    if fill:
        s += f' fill="{fill}"'
    return s


def _origin_transform(el) -> str:
    """如果图元有旋转，包装 transform"""
    if el.rotation:
        return f' transform="rotate({el.rotation} {el.x} {el.y})"'
    return ""


def to_svg(sketch: Sketch, embed_images=False) -> str:
    lines = ['<svg xmlns="http://www.w3.org/2000/svg"',
             f'     width="{sketch.width}" height="{sketch.height}"',
             '     viewBox="0 0 {} {}">'.format(sketch.width, sketch.height),
             f'  <rect width="100%" height="100%" fill="white"/>',
             f'  <g stroke="black" stroke-width="1" fill="none">']

    for el in sketch.elements:
        if isinstance(el, Line):
            lines.append(
                f'  <line x1="{el.x1}" y1="{el.y1}" x2="{el.x2}" y2="{el.y2}" {_style_str(el.style)}/>'
            )

        elif isinstance(el, Rect):
            lines.append(
                f'  <rect x="{el.x}" y="{el.y}" width="{el.w}" height="{el.h}"'
                f' rx="{el.rx}" {_style_str(el.style)}{_origin_transform(el)}/>'
            )

        elif isinstance(el, Circle):
            lines.append(
                f'  <circle cx="{el.cx}" cy="{el.cy}" r="{el.r}" {_style_str(el.style)}/>'
            )

        elif isinstance(el, Arc):
            start_x = el.cx + el.r * math.cos(math.radians(el.start_angle))
            start_y = el.cy + el.r * math.sin(math.radians(el.start_angle))
            end_x = el.cx + el.r * math.cos(math.radians(el.end_angle))
            end_y = el.cy + el.r * math.sin(math.radians(el.end_angle))
            large = 1 if abs(el.end_angle - el.start_angle) > 180 else 0
            sweep = 1 if el.end_angle > el.start_angle else 0
            lines.append(
                f'  <path d="M{start_x},{start_y} A{el.r},{el.r} 0 {large},{sweep} {end_x},{end_y}"'
                f' {_style_str(el.style)}/>'
            )

        elif isinstance(el, Polyline):
            pts = " ".join(f"{p.x},{p.y}" for p in el.points)
            lines.append(f'  <polyline points="{pts}" {_style_str(el.style)}/>')

        elif isinstance(el, Arrow):
            lines.append(
                f'  <line x1="{el.x1}" y1="{el.y1}" x2="{el.x2}" y2="{el.y2}" {_style_str(el.style)}/>'
            )
            # 箭头头
            ang = math.atan2(el.y2 - el.y1, el.x2 - el.x1)
            hs = el.head_size
            ax1 = el.x2 - hs * math.cos(ang - math.radians(30))
            ay1 = el.y2 - hs * math.sin(ang - math.radians(30))
            ax2 = el.x2 - hs * math.cos(ang + math.radians(30))
            ay2 = el.y2 - hs * math.sin(ang + math.radians(30))
            lines.append(f'  <polygon points="{el.x2},{el.y2} {ax1},{ay1} {ax2},{ay2}" fill="black"/>')

        elif isinstance(el, Dimension):
            # 尺寸线 + 延伸线
            ext = el.offset
            lines.append(f'  <line x1="{el.x1}" y1="{el.y1}" x2="{el.x1}" y2="{el.y1 - ext}" stroke="#666" stroke-width="0.5" stroke-dasharray="3,3"/>')
            lines.append(f'  <line x1="{el.x2}" y1="{el.y2}" x2="{el.x2}" y2="{el.y2 - ext}" stroke="#666" stroke-width="0.5" stroke-dasharray="3,3"/>')
            mid_y = min(el.y1, el.y2) - ext / 2
            lines.append(f'  <line x1="{el.x1}" y1="{el.y1 - ext}" x2="{el.x2}" y2="{el.y2 - ext}" stroke="#666" stroke-width="0.5"/>')
            if el.text:
                mid_x = (el.x1 + el.x2) / 2
                lines.append(f'  <text x="{mid_x}" y="{mid_y}" text-anchor="middle" font-size="12" fill="#666">{el.text}</text>')

        elif isinstance(el, Hinge):
            # 铰链：圆 + 对角线交叉
            lines.append(f'  <circle cx="{el.cx}" cy="{el.cy}" r="{el.r}" {_style_str(el.style)}/>')
            r2 = el.r * 0.707
            lines.append(f'  <line x1="{el.cx - r2}" y1="{el.cy - r2}" x2="{el.cx + r2}" y2="{el.cy + r2}" {_style_str(el.style)}/>')
            lines.append(f'  <line x1="{el.cx - r2}" y1="{el.cy + r2}" x2="{el.cx + r2}" y2="{el.cy - r2}" {_style_str(el.style)}/>')

        elif isinstance(el, Spring):
            # 弹簧：锯齿线
            turns = el.turns
            pts = [(el.x1, el.y1)]
            seg_h = (el.y2 - el.y1) / (turns * 2)
            half_w = el.width / 2
            for i in range(turns * 2):
                x = el.x1 + (half_w if i % 2 == 0 else -half_w)
                y = el.y1 + seg_h * (i + 1)
                pts.append((x, y))
            pts.append((el.x2, el.y2))
            pt_str = " ".join(f"{x},{y}" for x, y in pts)
            lines.append(f'  <polyline points="{pt_str}" {_style_str(el.style)}/>')

        elif isinstance(el, Text):
            lines.append(
                f'  <text x="{el.x}" y="{el.y}" font-size="{el.font_size}"'
                f' font-family="sans-serif">{el.text}</text>'
            )

    lines.append('  </g>')
    lines.append('</svg>')
    return "\n".join(lines)


def to_svg_minimal(sketch: Sketch) -> str:
    """导出极简 SVG（仅必要元素，适合嵌入专利文档）"""
    return to_svg(sketch)
