# -*- coding: utf-8 -*-
"""
国标（第一角投影法）自动出图脚本
从 STEP 文件生成三视图（主、俯、左）+ 总体尺寸标注
适用于 FreeCAD 命令行环境（freecadcmd）
"""

import sys
import os
import math
import time

# 尝试导入 FreeCAD 核心模块
try:
    import FreeCAD as App
    import Part
    import TechDraw
    import Import
    from FreeCAD import Base
except ImportError:
    print("错误：未找到 FreeCAD 模块，请确保在 freecadcmd 环境下运行。")
    sys.exit(1)

# TechDrawGui 在 freecadcmd 中可能不存在，但用于导出 PDF 时可使用 page.export()
try:
    import TechDrawGui
except ImportError:
    TechDrawGui = None


def generate_drawing_from_step(step_file_path, pdf_output_path=None,
                               fcstd_output_path=None, scale=None):
    """
    按国标（第一角投影法）生成三视图工程图

    参数:
        step_file_path (str): STEP 文件路径
        pdf_output_path (str, optional): PDF 输出路径
        fcstd_output_path (str, optional): FCStd 源文件保存路径
        scale (float, optional): 视图比例，若为 None 则自动计算
    """
    # 使用第一角投影法：主视图（Front）在左上，俯视图（Top）在正下，左视图（Left）在正右
    views = ['front', 'top', 'left']

    # 视图配置：方向向量、水平/垂直轴映射
    VIEW_CONFIG = {
        'front':  {'dir': (0, -1, 0), 'h_axis': 'X', 'v_axis': 'Z'},   # 从前向后看
        'top':    {'dir': (0, 0, -1), 'h_axis': 'X', 'v_axis': 'Y'},   # 从上向下看（注意方向）
        'left':   {'dir': (1, 0, 0), 'h_axis': 'Y', 'v_axis': 'Z'},    # 从左向右看（左视图，放在右侧）
    }

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
        print(f"✅ STEP 导入成功: {step_file_path}")
    except Exception as e:
        raise RuntimeError(f"导入 STEP 失败: {e}")

    # --------------------- 3. 查找第一个实体 ---------------------
    source_obj = None
    for obj in doc.Objects:
        if hasattr(obj, 'Shape') and obj.Shape and obj.Shape.Volume > 0:
            source_obj = obj
            break

    if not source_obj:
        raise RuntimeError("STEP 文件中未找到有效实体模型。")

    print(f"📦 使用模型: {source_obj.Label}")

    # --------------------- 4. 计算模型尺寸 ---------------------
    bbox = source_obj.Shape.BoundBox
    width = bbox.XLength
    depth = bbox.YLength
    height = bbox.ZLength
    sizes = {'X': width, 'Y': depth, 'Z': height}
    print(f"📐 模型尺寸: W={width:.2f}, D={depth:.2f}, H={height:.2f}")

    # --------------------- 5. 自动计算比例 ---------------------
    if scale is None:
        # 目标：在 A4 横向图纸（约 280×190 mm 可用区域）中，三视图合理布局
        # 估算三个视图所需的总宽高
        # 主视图（Front）占宽 width，高 height
        # 俯视图（Top）占宽 width，高 depth
        # 左视图（Left）占宽 depth，高 height
        # 按第一角投影法布局：主视图在左上，俯视图在正下，左视图在正右
        # 总宽度 ≈ width + spacing + depth
        # 总高度 ≈ height + spacing + depth
        spacing = 30  # 视图间距
        total_w = width + spacing + depth
        total_h = height + spacing + depth
        # 留边距 25mm
        margin = 25
        usable_w = 280 - 2 * margin
        usable_h = 190 - 2 * margin
        # 计算比例，使得视图整体适应纸张
        scale_w = usable_w / total_w
        scale_h = usable_h / total_h
        scale = min(scale_w, scale_h)
        scale = max(0.05, min(scale, 10.0))
    print(f"📏 使用比例: {scale:.2f}")

    # 计算每个视图在图纸上的显示尺寸（mm）
    view_dims = {
        'front': (width * scale, height * scale),
        'top':   (width * scale, depth * scale),
        'top':   (width * scale, depth * scale),   # 俯视图显示宽为 width，高为 depth
        'left':  (depth * scale, height * scale),  # 左视图显示宽为 depth，高为 height
    }
    # 注意：上述 dict 中 'top' 重复，下面分别取用
    front_w, front_h = width * scale, height * scale
    top_w, top_h = width * scale, depth * scale
    left_w, left_h = depth * scale, height * scale

    # --------------------- 6. 布局计算（第一角投影法） ---------------------
    spacing = 30  # 视图间距
    margin = 25
    # 主视图（Front）位置：左上角
    # 俯视图（Top）：主视图正下方，X 坐标对齐
    # 左视图（Left）：主视图正右方，Y 坐标对齐
    # 整体居中放置
    total_width = front_w + spacing + left_w
    total_height = front_h + spacing + top_h
    start_x = (280 - total_width) / 2
    start_y = (190 - total_height) / 2 + top_h + spacing  # 因为主视图在偏上位置，但为了整体居中，我们计算底边坐标

    # 更精确的居中：以主视图左上角为参考
    # 主视图左上角坐标：(start_x, start_y)
    front_x = start_x + front_w / 2
    front_y = start_y + front_h / 2

    # 俯视图：主视图下方，X 与主视图中心对齐，Y 下移 front_h/2 + spacing + top_h/2
    top_x = front_x
    top_y = front_y - front_h/2 - spacing - top_h/2

    # 左视图：主视图右方，Y 与主视图中心对齐，X 右移 front_w/2 + spacing + left_w/2
    left_x = front_x + front_w/2 + spacing + left_w/2
    left_y = front_y

    positions = {
        'front': (front_x, front_y),
        'top':   (top_x, top_y),
        'left':  (left_x, left_y),
    }

    # --------------------- 7. 创建图纸页面 (A4 横向) ---------------------
    page = doc.addObject('TechDraw::DrawPage', 'Page')
    template = doc.addObject('TechDraw::DrawSVGTemplate', 'Template')
    # 查找模板
    template_candidates = [
        "Mod/TechDraw/Templates/A4_LandscapeTD.svg",
        "Mod/TechDraw/Templates/A4_Landscape.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_advanced.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_minimal.svg",
        "Mod/TechDraw/Templates/ISO/A4_Landscape_TD.svg",
    ]
    template_path = None
    for cand in template_candidates:
        full = App.getResourceDir() + cand
        if os.path.exists(full):
            template_path = full
            break
    if template_path is None:
        raise RuntimeError("未找到 A4 横向模板")
    template.Template = template_path
    page.Template = template
    doc.recompute()

    # --------------------- 8. 创建视图并添加尺寸标注 ---------------------
    def add_dimension_to_view(view, edge_name, label, x, y):
        """用投影视图边创建可显示的线性尺寸。"""
        dim = doc.addObject('TechDraw::DrawViewDimension', 'Dim')
        dim.Type = 'Distance'
        dim.References2D = [(view, edge_name)]
        dim.FormatSpec = label
        dim.X = x
        dim.Y = y
        page.addView(dim)
        dim.Visibility = True
        dim.recompute()
        return dim

    for view_name in views:
        config = VIEW_CONFIG[view_name]
        dir_vec = Base.Vector(*config['dir'])
        h_axis = config['h_axis']
        v_axis = config['v_axis']
        h_size = sizes[h_axis] * scale
        v_size = sizes[v_axis] * scale

        # 创建视图对象
        view = doc.addObject('TechDraw::DrawViewPart', f"View_{view_name.capitalize()}")
        view.Source = [source_obj]
        view.Direction = dir_vec
        # 设定 XDirection 使视图正立
        if view_name in ('front', 'top'):
            view.XDirection = Base.Vector(1, 0, 0)   # 保持正常
        elif view_name == 'left':
            view.XDirection = Base.Vector(0, 1, 0)   # 使左视图正立
        view.Scale = scale
        view.CoarseView = True
        page.addView(view)
        pos_x, pos_y = positions[view_name]
        view.X = pos_x
        view.Y = pos_y
        view.Visibility = True
        view.recompute()
        print(f"创建视图 {view_name} 于 ({pos_x:.1f}, {pos_y:.1f})")

        # 添加水平尺寸（在视图下方）
        add_dimension_to_view(view, 'Edge1', f"{h_axis} = %.2f mm" % sizes[h_axis],
                      pos_x, pos_y - v_size / 2 - 10)
        # 添加垂直尺寸（在视图右侧）
        add_dimension_to_view(view, 'Edge2', f"{v_axis} = %.2f mm" % sizes[v_axis],
                      pos_x + h_size / 2 + 10, pos_y)

    # 强制刷新
    doc.recompute()
    # 在 freecadcmd 中，可能没有 Gui，但我们仍可尝试刷新
    try:
        import FreeCADGui as Gui
        Gui.updateGui()
    except:
        pass

    # 保存 FCStd 文件（如果指定）
    if fcstd_output_path:
        try:
            doc.saveAs(fcstd_output_path)
            print(f"✅ FCStd 已保存: {fcstd_output_path}")
        except Exception as e:
            print(f"⚠️ FCStd 保存失败: {e}")

    # 导出 PDF（如果指定）
    if pdf_output_path:
        try:
            # 使用 Page 对象的 export 方法（无需 GUI）
            page.export(pdf_output_path)
            print(f"✅ PDF 已导出: {pdf_output_path}")
        except Exception as e:
            print(f"⚠️ PDF 导出失败: {e}")
            # 尝试备用方法（如果有 TechDrawGui）
            if TechDrawGui is not None:
                try:
                    TechDrawGui.exportPageAsPdf(page, pdf_output_path)
                    print(f"✅ PDF 已导出 (via TechDrawGui): {pdf_output_path}")
                except Exception as e2:
                    print(f"⚠️ 导出 PDF 再次失败: {e2}")

    print("🎉 出图完成！")
    return doc, page


# --------------------- 主程序入口 ---------------------
if __name__ == "__main__":
    # 示例：假设脚本在项目目录中，且 sample/complex.step 存在
    # 请根据实际路径修改
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    sample_dir = os.path.join(repo_root, 'sample')
    step_file = os.path.join(sample_dir, 'complex.step')
    pdf_file = os.path.join(sample_dir, 'output_GB.pdf')
    fcstd_file = os.path.join(sample_dir, 'output_GB.FCStd')

    if not os.path.exists(step_file):
        print(f"错误：找不到示例文件 {step_file}，请修改路径。")
        sys.exit(1)

    generate_drawing_from_step(step_file, pdf_file, fcstd_file)