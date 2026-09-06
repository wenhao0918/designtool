# -*- coding: utf-8 -*-
import FreeCAD as App
import FreeCAD, Part, TechDraw, Import
from FreeCAD import Base
import os
import math
import time

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

try:
    import TechDrawGui
except ImportError:
    TechDrawGui = None

def generate_drawing_from_step(step_file_path, pdf_output_path=None,
                              fcstd_output_path=None, scale=None, views=None):
    """
    从 STEP 文件自动生成含指定视图和总体尺寸的工程图纸。

    参数:
        step_file_path (str): STEP 文件的完整路径。
        pdf_output_path (str, optional): PDF 输出路径。若为 None，则不导出 PDF。
        fcstd_output_path (str, optional): FreeCAD 文档输出路径。若为 None，则不保存文档。
        scale (float, optional): 视图缩放比例。若为 None，则根据模型大小自动估算。
        views (list, optional): 要生成的视图名称列表，支持 'front','top','right','left','back','bottom'。
                                 默认为 ['front', 'top', 'right']。

    返回:
        (doc, page): 创建的文档对象和图纸页面对象。
    """
    # 默认视图
    if views is None:
        views = ['front', 'top', 'right']

    # 支持的视图及其方向、标注轴映射
    VIEW_CONFIG = {
        'front':  {'dir': (0, -1, 0), 'h_axis': 'X', 'v_axis': 'Z'},
        'top':    {'dir': (0, 0, -1), 'h_axis': 'X', 'v_axis': 'Y'},
        'right':  {'dir': (-1, 0, 0), 'h_axis': 'Y', 'v_axis': 'Z'},
        'left':   {'dir': (-1, 0, 0), 'h_axis': 'Z', 'v_axis': 'Y'},
        'back':   {'dir': (0, 1, 0),  'h_axis': 'X', 'v_axis': 'Z'},
        'bottom': {'dir': (0, 0, -1), 'h_axis': 'X', 'v_axis': 'Y'},
    }

    # 验证视图名称
    for v in views:
        if v not in VIEW_CONFIG:
            print(f"WARNING: unsupported view '{v}', skipped")
            views = [v for v in views if v in VIEW_CONFIG]

    if not views:
        raise ValueError("没有有效的视图名称，请提供支持的视图列表。")

    # --------------------- 1. 创建或获取文档 ---------------------
    doc = App.ActiveDocument
    if not doc:
        doc = App.newDocument("StepDrawing")

    # --------------------- 2. 导入 STEP 文件 ---------------------
    if not os.path.exists(step_file_path):
        raise FileNotFoundError(f"STEP 文件不存在: {step_file_path}")

    try:
        Import.insert(step_file_path, doc.Name)
        doc.recompute()
        print(f"STEP imported: {step_file_path}")
    except Exception as e:
        raise RuntimeError(f"导入 STEP 失败: {e}")

    # --------------------- 3. 寻找第一个实体零件 ---------------------
    source_obj = None
    for obj in doc.Objects:
        if hasattr(obj, 'Shape') and obj.Shape and obj.Shape.Volume > 0:
            source_obj = obj
            break

    if not source_obj:
        raise RuntimeError("在 STEP 文件中未找到有效的实体模型。")

    print("Using imported solid model")

    # --------------------- 4. 计算模型总体尺寸 ---------------------
    bbox = source_obj.Shape.BoundBox
    width  = bbox.XLength   # X方向尺寸
    depth  = bbox.YLength   # Y方向尺寸
    height = bbox.ZLength   # Z方向尺寸
    sizes = {'X': width, 'Y': depth, 'Z': height}
    print(f"Model size: W={width:.2f}, D={depth:.2f}, H={height:.2f}")

    # 自动计算比例
    if scale is None:
        max_model_size = max(width, depth, height)
        scale = min(260, 170) * 0.8 / max_model_size
        scale = max(0.05, min(scale, 10.0))
    print(f"Scale: {scale:.2f}")

    # --------------------- 5. 创建图纸页面 (A4 横向) ---------------------
    page = doc.addObject('TechDraw::DrawPage', 'Page')
    template = doc.addObject('TechDraw::DrawSVGTemplate', 'Template')
    template_candidates = [
        "Mod/TechDraw/Templates/A4_LandscapeTD.svg",
        "Mod/TechDraw/Templates/A4_Landscape.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_advanced.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_minimal.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_TD.svg",
    ]
    template_path = next(
        (App.getResourceDir() + candidate for candidate in template_candidates
         if os.path.exists(App.getResourceDir() + candidate)),
        None,
    )
    if template_path is None:
        raise Exception("未找到 A4 横向模板，请检查 FreeCAD 安装。")
    template.Template = template_path
    page.Template = template
    doc.recompute()

    # --------------------- 6. 计算视图布局位置 ---------------------
    paper_width, paper_height = page.PageWidth, page.PageHeight
    margin = 25
    usable_w = paper_width - 2 * margin
    usable_h = paper_height - 2 * margin
    spacing = 20

    if len(views) > 3:
        print("WARNING: layout supports at most 3 views; extras skipped")
        views = views[:3]

    def dimensions_for(view_name):
        config = VIEW_CONFIG[view_name]
        return sizes[config['h_axis']] * scale, sizes[config['v_axis']] * scale

    view_dimensions = [dimensions_for(view_name) for view_name in views]
    if len(view_dimensions) == 1:
        required_w = view_dimensions[0][0]
        required_h = view_dimensions[0][1]
    elif len(view_dimensions) == 2:
        required_w = view_dimensions[0][0] + spacing + view_dimensions[1][0]
        required_h = max(view_dimensions[0][1], view_dimensions[1][1])
    else:
        required_w = view_dimensions[0][0] + spacing + view_dimensions[1][0]
        required_h = max(view_dimensions[0][1], view_dimensions[1][1]) + spacing + view_dimensions[2][1]

    fit_scale = min(usable_w / (required_w / scale + 2 * margin),
                    usable_h / (required_h / scale + 2 * margin))
    scale = max(0.05, min(scale * fit_scale, 10.0))
    view_dimensions = [dimensions_for(view_name) for view_name in views]

    if len(view_dimensions) == 1:
        positions = [(paper_width / 2, paper_height / 2)]
    elif len(view_dimensions) == 2:
        total_w = view_dimensions[0][0] + spacing + view_dimensions[1][0]
        left = (paper_width - total_w) / 2
        row_y = paper_height / 2
        positions = [
            (left + view_dimensions[0][0] / 2, row_y),
            (left + view_dimensions[0][0] + spacing + view_dimensions[1][0] / 2, row_y),
        ]
    else:
        positions = [
            (paper_width * 0.33, paper_height * 0.43),
            (paper_width * 0.33, paper_height * 0.76),
            (paper_width * 0.67, paper_height * 0.43),
        ]

    # --------------------- 7. 创建视图并添加尺寸 ---------------------
    def add_dimension_to_view(view, edge_name, axis_name, x, y):
        """用投影视图中的边创建显示实际包围盒数值的尺寸。"""
        dim = doc.addObject('TechDraw::DrawViewDimension', 'Dim')
        dim.Type = 'Distance'
        dim.References2D = [(view, edge_name)]
        dim.FormatSpec = '%s = %.2f mm' % (axis_name, sizes[axis_name])
        dim.X = x
        dim.Y = y
        dim.Scale = scale
        page.addView(dim)
        dim.Visibility = True
        dim.recompute()
        return dim

    views_dict = {}
    offset = 10  # 尺寸线与视图边框的偏移

    for idx, view_name in enumerate(views):
        config = VIEW_CONFIG[view_name]
        dir_vec = Base.Vector(*config['dir'])
        h_axis = config['h_axis']  # 'X' or 'Z' etc.
        v_axis = config['v_axis']

        # 获取该视图在模型空间对应的水平尺寸和垂直尺寸
        h_size, v_size = view_dimensions[idx]

        # 创建视图对象
        view = doc.addObject('TechDraw::DrawViewPart', f"View_{view_name.capitalize()}")
        view.Source = [source_obj]
        view.Direction = dir_vec
        if view_name in ('right', 'left'):
            view.XDirection = Base.Vector(0, 1, 0)
        view.Scale = scale
        view.CoarseView = True
        page.addView(view)
        # TechDraw 的 X/Y 是视图中心坐标。
        pos_x, pos_y = positions[idx]
        view.X = pos_x
        view.Y = pos_y
        view.Visibility = True
        view.recompute()

        views_dict[view_name] = view
        print(f"Created view {view_name} at ({pos_x:.1f}, {pos_y:.1f})")

        # 添加水平尺寸（在视图下方）
        add_dimension_to_view(view, 'Edge1', h_axis, pos_x, pos_y - v_size / 2 - offset)
        # 添加垂直尺寸（在视图右侧）
        add_dimension_to_view(view, 'Edge2', v_axis, pos_x + h_size / 2 + offset, pos_y)

    # 强制刷新
    page.Visibility = True
    doc.recompute()
    if Gui is not None and hasattr(Gui, 'updateGui'):
        Gui.updateGui()
    try:
        from PySide6 import QtWidgets
    except ImportError:
        try:
            from PySide2 import QtWidgets
        except ImportError:
            QtWidgets = None
    if QtWidgets is not None:
        application = QtWidgets.QApplication.instance()
        if application is not None:
            for _ in range(200):
                application.processEvents()
                time.sleep(0.05)
            doc.recompute()

    if fcstd_output_path:
        try:
            doc.saveAs(fcstd_output_path)
            print(f"FreeCAD document saved: {fcstd_output_path}")
        except Exception as e:
            raise RuntimeError(f"FreeCAD 文档保存失败: {e}")

    # --------------------- 8. 导出 PDF（如果指定了路径） ---------------------
    if pdf_output_path:
        if TechDrawGui is None:
            raise RuntimeError("PDF 导出需要在 FreeCAD 图形界面环境中运行。")
        try:
            TechDrawGui.exportPageAsPdf(page, pdf_output_path)
            print(f"PDF exported: {pdf_output_path}")
        except Exception as e:
            print(f"WARNING: PDF export failed: {e}")

    print("Drawing generation complete")
    return doc, page

if __name__ == "__main__":
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    sample_dir = os.path.join(repo_root, 'sample')

    def run_default_generation():
        try:
            generate_drawing_from_step(
                os.path.join(sample_dir, 'complex.step'),
                pdf_output_path=os.path.join(sample_dir, 'output.pdf'),
                fcstd_output_path=os.path.join(sample_dir, 'output.FCStd'),
                views=['front', 'top', 'right'],
            )
        finally:
            QtCore.QCoreApplication.quit()

    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore
    QtCore.QTimer.singleShot(1000, run_default_generation)