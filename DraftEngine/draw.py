# -*- coding: utf-8 -*-
"""本地 FreeCAD 1.1 三视图 PDF 生成(带诊断,写状态文件)。

关键点:
1. 官方 ISO 模板(带标题栏)
2. DrawProjGroup 三视图投影组
3. 多轮 GUI 事件循环让视图几何真正渲染(脚本模式投影可能不触发)
4. 状态写文件(FreeCAD stdout 被 AI Copilot 刷掉,不可靠)
5. 导出 PDF + SVG(双重验证视图有没有画出来)

用法:
  /Applications/FreeCAD.app/Contents/Resources/bin/freecad draw.py
"""
import FreeCAD as App
import FreeCAD, Part, TechDraw, TechDrawGui, Import
from FreeCAD import Base
import os, math, time
try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    from PySide6 import QtWidgets, QtCore

step_file = "/Users/dengwenhao/develop/work/dao_code/sample/complex.step"
export_dir = "/Users/dengwenhao/develop/work/dao_code/sample"
status_file = "/tmp/draw_status.txt"

def log(msg):
    with open(status_file, "a") as f:
        f.write(msg + "\n")

def do_work():
    open(status_file, "w").close()
    log("=== 开始 ===")
    app = QtWidgets.QApplication.instance()

    doc = App.ActiveDocument
    if not doc:
        doc = App.newDocument("StepDrawing")
    for obj in list(doc.Objects):
        if obj.TypeId in ("TechDraw::DrawPage", "TechDraw::DrawProjGroup",
                          "TechDraw::DrawViewPart", "TechDraw::DrawSVGTemplate"):
            doc.removeObject(obj.Name)

    Import.insert(step_file, doc.Name)
    doc.recompute()
    source_obj = None
    for obj in doc.Objects:
        if hasattr(obj, 'Shape') and obj.Shape and obj.Shape.Volume > 0:
            source_obj = obj
            break
    if not source_obj:
        log("错误: 无实体")
        return
    log("模型: " + source_obj.Label)

    bbox = source_obj.Shape.BoundBox
    size = max(bbox.XLength, bbox.YLength, bbox.ZLength)
    scale = min(180 / size, 120 / size)
    scale = max(0.1, min(scale, 10.0))
    log("比例: %.2f" % scale)

    # ===== 页面 + 官方模板 =====
    page = doc.addObject('TechDraw::DrawPage', 'Page')
    template = doc.addObject('TechDraw::DrawSVGTemplate', 'Template')
    candidates = [
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_advanced.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_minimal.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_TD.svg",
    ]
    template_path = None
    for c in candidates:
        p = App.getResourceDir() + c
        if os.path.exists(p):
            template_path = p
            break
    template.Template = template_path
    page.Template = template
    page.Visibility = False
    page.Visibility = True
    doc.recompute()
    log("模板: " + os.path.basename(template_path))

    # ===== 三视图投影组 =====
    group = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
    page.addView(group)
    group.Source = [source_obj]
    try:
        group.ProjectionType = "First angle"
    except Exception:
        try:
            group.ProjectionType = 0
        except Exception:
            pass
    group.addProjection("Front")
    group.Anchor.Direction = Base.Vector(0, -1, 0)
    group.Anchor.RotationVector = Base.Vector(1, 0, 0)
    group.addProjection("Top")
    group.addProjection("Right")
    doc.recompute()
    # 先确认页面尺寸(模板加载后才有)
    log("页面尺寸: %.1f x %.1f" % (page.PageWidth, page.PageHeight))
    # 设投影组位置(addProjection 之后)
    group.X = page.PageWidth / 2
    group.Y = page.PageHeight / 2
    doc.recompute()
    log("投影组视图数: %d" % len(group.Views))

    # ===== 多轮事件循环让视图几何渲染 =====
    for i in range(20):
        for _ in range(10):
            app.processEvents()
            time.sleep(0.05)
        doc.recompute()
    # 事件循环后重设位置(防止被 recompute 重置)
    group.X = page.PageWidth / 2
    group.Y = page.PageHeight / 2
    doc.recompute()
    log("事件循环完成, 组位置: %.1f, %.1f" % (group.X, group.Y))

    # 直接设每个视图位置(锚点 Front 居中,Top 在上,Right 在右)
    # FreeCAD 页面坐标 y 向上为正(数学坐标),SVG 导出会翻转
    # 视图区整体居中:左列(Front/Top)与右列(Right)对称于页面中心
    # 实测(2026-08-18):主视图内容半宽 60mm(左缘=98-60=38mm),
    #   右视图内容半宽 80mm(含标注),页面图框 [20,287]mm
    #   对称:右视图右缘 = 297-38 = 259mm → 右列中心 = 259-80 = 179mm
    try:
        for v in group.Views:
            if v.Label == "Front":
                v.X = 98; v.Y = 95
            elif v.Label == "Top":
                v.X = 98; v.Y = 155
            elif v.Label == "Right":
                v.X = 179; v.Y = 95
            v.recompute()
        doc.recompute()
        log("各视图位置已设")
    except Exception as e:
        log("设视图位置失败: " + str(e))

    # 检查视图几何(看 ViewObject 是否有内容)
    try:
        for v in group.Views:
            vo = v.ViewObject
            log("视图 %s: X=%s Y=%s" % (v.Label, v.X, v.Y))
    except Exception as e:
        log("视图检查失败: " + str(e))

    # ===== 导出 SVG + PDF =====
    svg_path = os.path.join(export_dir, "complex_drawing.svg")
    try:
        TechDrawGui.exportPageAsSvg(page, svg_path)
        log("SVG 已导出: %s (%d bytes)" % (svg_path, os.path.getsize(svg_path)))
    except Exception as e:
        log("SVG 导出失败: " + str(e))
    pdf_path = os.path.join(export_dir, "complex_drawing.pdf")
    try:
        TechDrawGui.exportPageAsPdf(page, pdf_path)
        log("PDF 已导出: %s (%d bytes)" % (pdf_path, os.path.getsize(pdf_path)))
    except Exception as e:
        log("PDF 导出失败: " + str(e))

    # 保存文档
    try:
        doc.saveAs(os.path.join(export_dir, "complex_drawing.FCStd"))
        log("FCStd 已保存")
    except Exception as e:
        log("FCStd 失败: " + str(e))
    log("=== 完成 ===")


QtCore.QTimer.singleShot(3000, do_work)
