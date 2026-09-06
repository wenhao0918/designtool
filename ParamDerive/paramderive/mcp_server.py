"""
ParamDerive MCP Server (with Sketch Tools)

启动: python3 -m paramderive.mcp_server
端口: 18084 (默认)
"""
import json, sys, os
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from paramderive import registry, calc_runner
from paramderive.sketch.elements import Sketch, Line, Rect, Circle, Point as SkPoint
from paramderive.sketch import beautify as sketch_bf, complete as sketch_cp, svg_export

mcp = FastMCP("paramderive", port=int(os.environ.get("PD_MCP_PORT", "18084")))

# === 参数推导工具 ===

@mcp.tool()
def derive_list_params(category: str = "", min_confidence: int = 0) -> str:
    """列出所有参数，可按分类和最低置信度筛选"""
    cat = category if category else None
    mc = min_confidence if min_confidence > 0 else None
    params = registry.list_params(cat, mc)
    if not params:
        return "暂无参数记录"
    lines = ["| 参数名 | 值 | 单位 | 置信度 | 分类 |"]
    lines.append("|--------|-----|------|--------|------|")
    for p in params:
        lines.append(f"| {p['name']} | {p.get('value','')} | {p.get('unit','')} | {p.get('confidence','')} | {p.get('category','')} |")
    return "\n".join(lines)

@mcp.tool()
def derive_get_param(name: str) -> str:
    """查看单个参数的完整推导链"""
    p = registry.get_param(name)
    if not p:
        return f"参数 '{name}' 未找到"
    lines = [f"# {name}", ""]
    for k in ["value", "unit", "confidence", "category", "description",
              "source", "method", "formula", "inputs", "created", "updated", "updated_by"]:
        v = p.get(k)
        if v is not None:
            lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)

@mcp.tool()
def derive_calc(script_path: str, params_json: str = "{}") -> str:
    """执行推导脚本。script_path: 脚本路径，params_json: JSON输入"""
    try:
        kwargs = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError as e:
        return f"参数JSON格式错误: {e}"
    result = calc_runner.run_script(script_path, **kwargs)
    return json.dumps(result, ensure_ascii=False, indent=2)

@mcp.tool()
def derive_whatif(name: str, params_json: str) -> str:
    """假设分析：修改输入条件后重算参数"""
    p = registry.get_param(name)
    if not p:
        return f"参数 '{name}' 未找到"
    script = p.get("derived_from")
    if not script:
        return f"参数 '{name}' 没有关联推导脚本"
    return derive_calc(script, params_json)

@mcp.tool()
def derive_update_param(name: str, value: float, unit: str, confidence: str,
                         changed_by: str = "AI", reason: str = "") -> str:
    """更新参数值（自动记录审计日志）"""
    p = registry.update_param(name, value, unit, confidence, changed_by, reason)
    return f"参数 '{name}' 已更新: {value} {unit} (置信度: {confidence})"

@mcp.tool()
def derive_list_scripts(category: str = "") -> str:
    """列出可执行的推导脚本"""
    cat = category if category else None
    scripts = calc_runner.list_scripts(cat)
    if not scripts:
        return "暂无推导脚本"
    lines = ["| 名称 | 分类 | 推导参数 | 方法 | 置信度 |"]
    lines.append("|------|------|----------|------|--------|")
    for s in scripts:
        lines.append(f"| {s['name']} | {s['category']} | {s.get('param','')} | {s.get('method','')} | {s.get('confidence','')} |")
    return "\n".join(lines)

# === 简图工具 ===

@mcp.tool()
def sketch_create(elements_json: str) -> str:
    """从JSON创建简图画布并导出SVG。
elements_json: [{\"type\":\"line\",\"x1\":0,\"y1\":0,\"x2\":100,\"y2\":0,\"style\":{}}, ...]
支持类型: line, rect, circle, arrow, hinge, spring, text
"""
    try:
        data = json.loads(elements_json)
    except json.JSONDecodeError as e:
        return f"JSON格式错误: {e}"
    sk = Sketch()
    for el_data in data:
        t = el_data.get("type")
        style = el_data.get("style", {})
        if t == "line":
            sk.add(Line(**{k: el_data.get(k, v) for k, v in [("x1",0),("y1",0),("x2",100),("y2",0)]}, style=style))
        elif t == "rect":
            sk.add(Rect(**{k: el_data.get(k, v) for k, v in [("x",0),("y",0),("w",100),("h",80),("rx",0)]}, style=style))
        elif t == "circle":
            sk.add(Circle(**{k: el_data.get(k, v) for k, v in [("cx",0),("cy",0),("r",50)]}, style=style))
    svg = svg_export.to_svg(sk)
    return svg

@mcp.tool()
def sketch_beautify(elements_json: str) -> str:
    """美化简图：网格吸附、直线对齐"""
    sk = Sketch()
    _load_sketch(sk, elements_json)
    sketch_bf.beautify(sk)
    return svg_export.to_svg(sk)

@mcp.tool()
def sketch_mirror(elements_json: str, axis: str = "y") -> str:
    """沿轴线镜像补全简图（虚线段显示镜像部分）"""
    sk = Sketch()
    _load_sketch(sk, elements_json)
    sketch_cp.mirror_symmetry(sk, axis=axis)
    return svg_export.to_svg(sk)

@mcp.tool()
def sketch_dimensions(elements_json: str) -> str:
    """自动添加尺寸标注"""
    sk = Sketch()
    _load_sketch(sk, elements_json)
    sketch_cp.auto_dimensions(sk)
    return svg_export.to_svg(sk)

@mcp.tool()
def sketch_recognize(points_json: str) -> str:
    """从自由绘制点识别标准图元
points_json: [[x1,y1],[x2,y2],...]"""
    try:
        pts = json.loads(points_json)
    except json.JSONDecodeError as e:
        return f"JSON格式错误: {e}"
    from paramderive.sketch import recognize
    el, conf = recognize.recognize_from_points(pts)
    if el:
        sk = Sketch()
        sk.add(el)
        svg = svg_export.to_svg(sk)
        return f"识别结果 (置信度: {conf:.2f})\n{svg}"
    return "无法识别该图形"

def _load_sketch(sk, elements_json):
    """从JSON加载图元到Sketch"""
    try:
        data = json.loads(elements_json)
    except json.JSONDecodeError:
        return
    for el_data in data:
        t = el_data.get("type")
        style = el_data.get("style", {})
        if t == "line":
            sk.add(Line(x1=el_data.get("x1",0), y1=el_data.get("y1",0),
                        x2=el_data.get("x2",100), y2=el_data.get("y2",0), style=style))
        elif t == "rect":
            sk.add(Rect(x=el_data.get("x",0), y=el_data.get("y",0),
                        w=el_data.get("w",100), h=el_data.get("h",80),
                        rx=el_data.get("rx",0), style=style))
        elif t == "circle":
            sk.add(Circle(cx=el_data.get("cx",0), cy=el_data.get("cy",0),
                          r=el_data.get("r",50), style=style))


if __name__ == "__main__":
    port = int(os.environ.get("PD_MCP_PORT", "18084"))
    print(f"ParamDerive MCP Server starting on port {port}...", file=sys.stderr)
    mcp.run(transport="sse")
