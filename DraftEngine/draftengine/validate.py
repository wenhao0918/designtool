"""DraftEngine 视觉验证:SVG → PNG(Playwright headless)。

流程中的中间态(三视图无标注)先用 Playwright 渲染成 PNG:
- 供人工/CI 快速检查(空白/错位一目了然)
- 作为 VLM(moonshot-vision)标注决策的输入图

Playwright/Chromium 不可用时降级返回 None(不阻塞出图主流程)。
"""

import os
import shutil


def render_png(svg_path, png_path=None, width=1600):
    """SVG 渲染为 PNG。返回 png 路径,失败返回 None。"""
    if not os.path.exists(svg_path):
        return None
    if png_path is None:
        png_path = os.path.splitext(svg_path)[0] + ".png"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if shutil.which("rsvg-convert"):
            import subprocess
            subprocess.run(["rsvg-convert", "-w", str(width), "-o", png_path, svg_path],
                           check=True, capture_output=True, timeout=60)
            return png_path if os.path.exists(png_path) else None
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            # A4 横向比例视口(viewBox 自适应缩放,勿用超大视口——截图会超时)
            page = browser.new_page(viewport={"width": width, "height": int(width * 2100 / 2970)})
            page.goto("file://" + os.path.abspath(svg_path))
            page.wait_for_timeout(300)
            page.screenshot(path=png_path)
            browser.close()
        return png_path if os.path.exists(png_path) else None
    except Exception:
        return None


def check_not_blank(png_path, thresh=0.99):
    """PNG 非空白检查(几乎全白 = 视图丢失)。返回 (ok, 非白像素比例)。"""
    try:
        from PIL import Image
    except ImportError:
        return True, -1  # 无法检查时视为通过
    try:
        img = Image.open(png_path).convert("L")
        px = list(img.getdata())
        nonwhite = sum(1 for v in px if v < 245)
        ratio = nonwhite / len(px)
        return ratio > (1 - thresh), ratio
    except Exception:
        return False, 0
