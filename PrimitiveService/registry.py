"""
Parametric design primitives — high-level FreeCAD code generators.

Each primitive takes structured parameters and returns correct FreeCAD Python code.
LLM never writes raw Part.makeBox coordinates — it calls these primitives.
"""

import os
import json


def indent(code, level=1):
    lines = code.strip().split("\n")
    return "\n".join("    " * level + l if l.strip() else l for l in lines)


def _v(pos):
    """Convert a sequence to FreeCAD Vector string."""
    if isinstance(pos, (list, tuple)):
        return "FreeCAD.Vector(%s, %s, %s)" % (pos[0], pos[1], pos[2])
    return str(pos)


def generate_shell_box(name, L, W, H, t, pos=(0, 0, 0)):
    """壳体盒：四壁 + 实心底，顶部开口，壁厚 t。
    参数:
        name  零件名
        L     长（X 方向，mm）
        W     宽（Y 方向，mm）
        H     高（Z 方向，mm）
        t     壁厚（mm）
        pos   放置位置，默认原点
    坐标系: 底面位于 pos 的 XY 平面，沿 +Z 生长，开口朝 +Z。
    用途: 外壳/罩、容器、箱体类零件。
    """

    v = _v(pos)
    # 退化壁厚防御:t>=H 或内腔长宽<=0 时按实心盒生成(LLM 常用 t=H 表达实心件,
    # 原实现内腔高度 0 会让 FreeCAD 抛 'height of box too small' 拒绝建模)。
    _solid = (t >= H) or (L - 2*t <= 0) or (W - 2*t <= 0)
    if _solid:
        return f"""# === {name}: solid box {L}x{W}x{H} (t={t}>=半厚,按实心) ===
_shape = Part.makeBox({L}, {W}, {H})
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""
    return f"""# === {name}: shell box {L}x{W}x{H} t={t} ===
_outer = Part.makeBox({L}, {W}, {H})
_inner = Part.makeBox({L}-2*{t}, {W}-2*{t}, {H}-{t}).translate({v})
_shape = _outer.cut(_inner)
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""



def generate_u_channel(name, L, W, H, t, pos=(0, 0, 0), ends="open"):
    """U 型槽：两侧壁 + 底，顶部开口。
    参数:
        name  零件名
        L     长（X 方向，mm）
        W     宽（Y 方向，mm）
        H     高（Z 方向，mm）
        t     壁厚（mm）
        pos   放置位置，默认原点
        ends  端壁控制: 'open'=两端无壁（开放对接用）; 'both'=两端封壁成槽;
               'start'/'end'=单端封壁
    坐标系: 底面位于 pos 的 XY 平面，沿 +Z 生长，长度沿 X。
    用途: 导轨槽、结构梁、线槽、开放槽。
    """

    vx, vy, vz = pos[0], pos[1], pos[2]
    if ends == "start":
        ix, il = t, L - t
    elif ends == "end":
        ix, il = 0, L - t
    elif ends == "both":
        ix, il = t, L - 2*t
    else:
        ix, il = 0, L
    return f"""# === {name}: U-channel {L}x{W}x{H} t={t} ends={ends} ===
_outer = Part.makeBox({L}, {W}, {H})
_inner = Part.makeBox({il}, {W} - 2*{t}, {H} - {t})
_inner.translate(FreeCAD.Vector({ix}, {t}, {t}))
_shape = _outer.cut(_inner)
_shape.translate(FreeCAD.Vector({vx}, {vy}, {vz}))
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""



def generate_wedge_box(name, L1, L2, W, H, t, pos=(0, 0, 0)):
    """楔形盒：宽度沿长度从 L1 渐变到 L2（四壁 + 底，顶部开口）。
    参数:
        name  零件名
        L1    起始端长（X 方向，mm）
        L2    末端长（X 方向，mm）
        W     宽（Y 方向，mm）
        H     高（Z 方向，mm）
        t     壁厚（mm）
        pos   放置位置，默认原点
    坐标系: 底面位于 pos 的 XY 平面，沿 +Z 生长。
    用途: 收窄过渡件、斜面结构、楔形支座。
    """

    v = _v(pos)
    return f"""# === {name}: wedge box {L1}->{L2}x{W}x{H} t={t} ===
_outer1 = Part.makeBox({L1}, {W}, {H})
_cut_l = Part.makeBox({L1}+2, ({W}-{L2})/2, {H}+2).translate(FreeCAD.Vector(-1, -1, -1))
_cut_r = Part.makeBox({L1}+2, ({W}-{L2})/2, {H}+2).translate(FreeCAD.Vector(-1, {W}-({W}-{L2})/2+1, -1))
_outer = _outer1.cut(_cut_l).cut(_cut_r)
_inner1 = Part.makeBox({L1}-2*{t}, {W}-2*{t}, {H}-{t}).translate(FreeCAD.Vector({t}, {t}, {t}))
_cut_l_in = Part.makeBox({L1}+2, ({W}-{L2})/2-{t}, {H}+2).translate(FreeCAD.Vector(-1, {t}-1, -1))
_cut_r_in = Part.makeBox({L1}+2, ({W}-{L2})/2-{t}, {H}+2).translate(FreeCAD.Vector(-1, {W}-({W}-{L2})/2+1, -1))
_inner = _inner1.cut(_cut_l_in).cut(_cut_r_in)
_shape = _outer.cut(_inner)
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""








def generate_hinge_connection(name, pos, axis_dir, pin_length, pin_r,
                              ear_count_a=2, ear_count_b=1, ear_w=12, ear_h=12,
                              ear_depth=10, mount_h=8):
    """铰链连接：两零件之间的水平铰链（耳座 + 销轴）。
    参数:
        name        零件名
        pos         铰链中心位置
        axis_dir    轴线方向（'x'/'y'/'z'）
        pin_length  销轴长度（mm）
        pin_r       销轴半径（mm）
    坐标系: 铰链轴线过 pos，沿 axis_dir；耳座成对布置，销轴贯穿。
    用途: 折叠机构、翻盖、摆动连接、门轴。
    """

    ear_total = ear_count_a + ear_count_b
    if axis_dir == "y":
        axis_vec, perp = "(1,0,0)", "X"
        p_i, p_j = "Z", "X"
    else:
        axis_vec, perp = "(0,1,0)", "Y"
        p_i, p_j = "Z", "Y"

    code = f"""# === {name}: hinge joint (axis={axis_dir}) ===
_pin_r = {pin_r}
_pin_L = {pin_length}
_ear_w = {ear_w}
_ear_h = {ear_h}
_ear_d = {ear_depth}
_mount_h = {mount_h}
"""
    ear_spacing = pin_length / ear_total
    for i in range(ear_count_a + ear_count_b):
        side = "a" if i < ear_count_a else "b"
        ear_center_z = pos[2]
        if axis_dir == "y":
            ear_cx = pos[0] + (-1 if side == "a" else 1) * ear_depth / 2
            ear_cy = pos[1] - pin_length / 2 + (i + 0.5) * ear_spacing
            ear_cz = pos[2] + ear_h / 2
        else:
            ear_cx = pos[0] - pin_length / 2 + (i + 0.5) * ear_spacing
            ear_cy = pos[1] + (-1 if side == "a" else 1) * ear_depth / 2
            ear_cz = pos[2] + ear_h / 2
        e_name = f"{name}_ear_{side}_{i}"
        if axis_dir == "y":
            code += f"""
_ear_box_{e_name} = Part.makeBox({ear_depth}, {ear_w}, {ear_h})
_ear_box_{e_name}.translate(FreeCAD.Vector({ear_cx - ear_depth / 2}, {ear_cy - ear_w / 2}, {ear_cz - ear_h / 2}))
_ear_hole_{e_name} = Part.makeCylinder({pin_r + 0.25}, {ear_h + 2})
_ear_hole_{e_name}.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector{axis_vec}, 90)
_ear_hole_{e_name}.translate(FreeCAD.Vector({ear_cx}, {ear_cy}, {ear_cz - ear_h / 2 - 1}))
_ear_{e_name} = _ear_box_{e_name}.cut(_ear_hole_{e_name})
_obj = doc.addObject('Part::Feature', '{e_name}')
_obj.Shape = _ear_{e_name}
"""
        else:
            code += f"""
_ear_box_{e_name} = Part.makeBox({ear_w}, {ear_depth}, {ear_h})
_ear_box_{e_name}.translate(FreeCAD.Vector({ear_cx - ear_w / 2}, {ear_cy - ear_depth / 2}, {ear_cz - ear_h / 2}))
_ear_hole_{e_name} = Part.makeCylinder({pin_r + 0.25}, {ear_w + 2})
_ear_hole_{e_name}.translate(FreeCAD.Vector({ear_cx - ear_w / 2 - 1}, {ear_cy}, {ear_cz}))
_ear_{e_name} = _ear_box_{e_name}.cut(_ear_hole_{e_name})
_obj = doc.addObject('Part::Feature', '{e_name}')
_obj.Shape = _ear_{e_name}
"""

    # Pin
    px, py, pz = pos[0], pos[1], pos[2]
    code += f"""
# === {name}: hinge pin ===
_pin = Part.makeCylinder({pin_r}, {pin_length})
_pin.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector{axis_vec}, 90)
_pin.translate(FreeCAD.Vector({px}, {py}, {pz}))
_obj = doc.addObject('Part::Feature', '{name}_pin')
_obj.Shape = _pin
"""
    return code

def generate_bellows_seal(name, center, outer_r, inner_r, num_rings, pitch, axis='z'):
    """波纹管密封：多个同心环构成的柔性密封段。
    参数:
        name      零件名
        center    中心位置
        outer_r   外径（mm）
        inner_r   内径（mm）
        num_rings 环数
        pitch     环间距（mm）
        axis      轴向（'x'/'y'/'z'），默认 'z'
    坐标系: 环沿 axis 方向排列，圆心在 center。
    用途: 柔性密封、伸缩护套、风琴罩、柔性管道连接。
    """

    ring_h = max(1.0, pitch * 0.3)
    cx, cy, cz = center[0], center[1], center[2]
    code = f"""# === {name}: bellows seal ===
_bellows = None
for _i in range({num_rings}):
    _ring = Part.makeCylinder({outer_r}, {ring_h}).cut(Part.makeCylinder({inner_r}, {ring_h}))
"""
    if axis == 'z':
        code += f"""    _z_off = _i * {pitch}
    _ring.translate(FreeCAD.Vector({cx}, {cy}, {cz} + _z_off))
"""
    else:
        code += f"""    _y_off = _i * {pitch}
    _ring.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,1,0), 90)
    _ring.translate(FreeCAD.Vector({cx}, {cy} + _y_off, {cz}))
"""
    code += f"""    if _bellows is None:
        _bellows = _ring
    else:
        _bellows = _bellows.fuse(_ring)
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _bellows
"""
    return code

def generate_u_channel_bellows(name, L, W, H, t, num_folds, pos=(0, 0, 0), wall_t=2):
    """U 型槽波纹管：匹配 U 型槽截面的柔性折叠段，两端开口。
    参数:
        name     零件名
        L        长（X 方向，mm）
        W        宽（Y 方向，mm）
        H        高（Z 方向，mm）
        t        壁厚（mm）
        num_folds 折叠数
        pos      放置位置，默认原点
        wall_t   折叠壁厚（mm）
    坐标系: 与 u_channel 对齐，两端开口对接 U 型槽。
    用途: 两段 U 型槽之间的柔性连接（折叠导轨、伸缩护套）。
    """

    vx, vy, vz = pos[0], pos[1], pos[2]
    wt = wall_t
    seg_len = L / (num_folds * 2)
    ridge_extra = 3.0
    
    code = f"""# === {name}: U-channel bellows {L}x{W}x{H} wall_t={wt} ===
"""
    # Build outer shape by fusing ridge+valley segments
    code += "_outer = None\n"
    for i in range(num_folds):
        bx = i * 2 * seg_len
        # valley
        code += f"_v = Part.makeBox({seg_len}, {W}, {H})\n"
        code += f"_v.translate(FreeCAD.Vector({bx}, 0, 0))\n"
        # ridge (wider)
        code += f"_r = Part.makeBox({seg_len}, {W} + 2*{ridge_extra}, {H})\n"
        code += f"_r.translate(FreeCAD.Vector({bx + seg_len}, -{ridge_extra}, 0))\n"
        if i == 0:
            code += "_outer = _v.fuse(_r)\n"
        else:
            code += "_outer = _outer.fuse(_v).fuse(_r)\n"
    # Single cavity cut
    code += f"_inner = Part.makeBox({L}, {W} - 2*{wt}, {H} - {wt})\n"
    code += f"_inner.translate(FreeCAD.Vector(0, {wt}, {wt}))\n"
    code += f"_body = _outer.cut(_inner)\n"
    code += f"_body.translate(FreeCAD.Vector({vx}, {vy}, {vz}))\n"
    code += f"_obj = doc.addObject('Part::Feature', '{name}')\n"
    code += f"_obj.Shape = _body\n"
    
    return code

def generate_plate(name, L, W, t, pos=(0, 0, 0)):
    """平板：矩形薄板。
    参数:
        name  零件名
        L     长（X 方向，mm）
        W     宽（Y 方向，mm）
        t     厚（Z 方向，mm）
        pos   放置位置，默认原点
    坐标系: 板面平行于 XY 平面，位于 pos 上方。
    用途: 底板、法兰、连接板、加强板。
    """

    v = _v(pos)
    return f"""# === {name}: plate {L}x{W}x{t} ===
_shape = Part.makeBox({L}, {W}, {t})
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""


def generate_cylinder(name, r, h, pos=(0, 0, 0)):
    """圆柱：实心圆柱体。
    参数:
        name  零件名
        r     半径（mm）
        h     高度（Z 方向，mm）
        pos   底面中心位置，默认原点
    坐标系: 轴线沿 +Z，底面在 pos 的 XY 平面。
    用途: 轴、销、滚子、推杆、立柱。
    """

    v = _v(pos)
    return f"""# === {name}: cylinder r={r} h={h} ===
_shape = Part.makeCylinder({r}, {h})
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""


def generate_sphere(name, r, pos=(0, 0, 0)):
    """球体：实心球。
    参数:
        name  零件名
        r     半径（mm）
        pos   球心位置，默认原点
    坐标系: 球心在 pos。
    用途: 球形关节、缓冲球、把手球头。
    """

    v = _v(pos)
    return f"""# === {name}: sphere r={r} ===
_shape = Part.makeSphere({r})
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""


def generate_fuse(name, part_names):
    """布尔并：将多个零件融合为一个实体。
    参数:
        name       结果零件名
        part_names 参与融合的零件名列表
    坐标系: 继承各输入零件的位置。
    用途: 组合重叠体、合并多段结构。
    """

    if len(part_names) < 2:
        return f"# fuse: needs >=2 parts\n"
    code = "# === fuse: %s ===\n" % name
    code += "_fparts = [%s]\n" % ", ".join(repr(n) for n in part_names)
    code += "_fshapes = []\n"
    code += "for _k in _fparts:\n"
    code += "    _ak = _NAME_MAP.get(_k, _k)\n"
    code += "    _vk = '_{}_shape'.format(_ak)\n"
    code += "    if _vk in dir():\n"
    code += "        _fshapes.append(eval(_vk))\n"
    code += "if _fshapes:\n"
    code += "    _shape = _fshapes[0]\n"
    code += "    for _s in _fshapes[1:]:\n"
    code += "        _shape = _shape.fuse(_s)\n"
    code += "    _obj = doc.addObject('Part::Feature', '%s')\n" % name
    code += "    _obj.Shape = _shape\n"
    code += "    _NAME_MAP[%r] = %r\n" % (name, name)
    code += "    _%s_shape = _shape\n" % name
    return code





def generate_subtract(name, base, tools):
    """布尔差：从基体上切除工具体。
    参数:
        name  结果零件名
        base  基体零件名
        tools 工具体零件名列表
    坐标系: 继承基体位置。
    用途: 开孔（圆柱减圆柱）、挖槽、掏壳（球减球、盒减盒）、沉孔。

    几何自校验:每个刀具必须与基体【实际相交】(交集体积>0),
    否则刀具悬空/只贴表面 → 减法无效 → 直接抛错,让 LLM 修正刀具位置。
    """

    if not tools:
        return f"# subtract: needs >=1 tool\n"
    code = "# === subtract: %s ===\n" % name
    code += "_bk = _NAME_MAP.get(%r, %r)\n" % (base, base)
    code += "_bv = '_{}_shape'.format(_bk)\n"
    code += "if _bv in dir():\n"
    code += "    _shape = eval(_bv)\n"
    for t in tools:
        code += "    _tk = _NAME_MAP.get(%r, %r)\n" % (t, t)
        code += "    _tv = '_{}_shape'.format(_tk)\n"
        code += "    if _tv in dir():\n"
        # 几何自校验:刀具必须与基体相交,否则切不到 → 抛错
        code += "        _tool_shape = eval(_tv)\n"
        code += "        _inter = _shape.common(_tool_shape)\n"
        code += "        _inter_vol = getattr(_inter, 'Volume', 0) or 0\n"
        code += "        if _inter_vol <= 0.001:\n"
        code += "            _tb = _tool_shape.BoundBox\n"
        code += "            _bb = _shape.BoundBox\n"
        code += "            _ov = not (_tb.XMax <= _bb.XMin or _tb.XMin >= _bb.XMax or _tb.YMax <= _bb.YMin or _tb.YMin >= _bb.YMax or _tb.ZMax <= _bb.ZMin or _tb.ZMin >= _bb.ZMax)\n"
        code += "            if not _ov:\n"
        code += "                _msg = '布尔减法无效: 刀具 %s 与基体 %s 不相交(包围盒也不相交,刀具悬空),交集体积=' + str(round(_inter_vol, 4)) + '。'\n" % (t, base)
        code += "                _msg += '刀具包围盒: ' + str(_tb) + '; 基体包围盒: ' + str(_bb) + '\\n'\n"
        code += "                _msg += '请修正刀具位置/尺寸,使其真正穿过基体材料(如圆柱中心伸入基体内部).'\n"
        code += "                raise RuntimeError(_msg)\n"
        code += "            print('[subtract] 刀具 %s 落在先前刀具已切除区域(包围盒相交,交集体积=0),本次跳过')\n" % t
        code += "        else:\n"
        code += "            _shape = _shape.cut(_tool_shape)\n"
    code += "    _obj = doc.addObject('Part::Feature', '%s')\n" % name
    code += "    _obj.Shape = _shape\n"
    code += "    _NAME_MAP[%r] = %r\n" % (name, name)
    code += "    _%s_shape = _shape\n" % name
    return code







def generate_side_shaft(name, pos, axis_dir, length, radius, mount_t=0, mount_r=0):
    """侧轴：从壁面伸出的枢轴段（可带安装座）。
    参数:
        name      零件名
        pos       轴中心位置
        axis_dir  轴向（'x'/'y'/'z'）
        length    轴长（mm）
        radius    轴半径（mm）
        mount_t   安装座厚度（mm，0=无）
        mount_r   安装座半径（mm）
    坐标系: 轴线过 pos 沿 axis_dir，从壁面向外伸出。
    用途: 槽/通道侧壁的枢轴（左右成对做同轴旋转），配合 side_hole。
    """

    px, py, pz = pos[0], pos[1], pos[2]
    sign = 1 if axis_dir == "+y" else -1
    code = f"# === {name}: side shaft axis={axis_dir} ===\n"
    code += f"_shaft = Part.makeCylinder({radius}, {length})\n"
    code += f"_shaft.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector(1,0,0), -90)\n"
    code += f"_shaft.translate(FreeCAD.Vector({px}, {py} + {sign}*{length}/2, {pz}))\n"
    if mount_t > 0 and mount_r > radius:
        code += f"_mount = Part.makeCylinder({mount_r}, {mount_t})\n"
        code += f"_mount.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector(0,1,0), 90)\n"
        code += f"_mount.translate(FreeCAD.Vector({px}, {py} + {sign}*{mount_t}/2, {pz}))\n"
        code += f"_body = _mount.fuse(_shaft)\n"
        code += f"_obj = doc.addObject('Part::Feature', '{name}')\n"
        code += f"_obj.Shape = _body\n"
    else:
        code += f"_obj = doc.addObject('Part::Feature', '{name}')\n"
        code += f"_obj.Shape = _shaft\n"
    return code

def generate_side_hole(name, pos, axis_dir, depth=None, radius=1.0, through=False):
    """侧孔：侧壁上的孔（枢轴安装孔）。
    参数:
        name     零件名
        pos      孔中心位置
        axis_dir 孔轴向（'+x'/'-x'/'+y'/'-y'/'+z'/'-z'）
        depth    孔深（mm）
        radius   孔半径（mm）
        through  是否贯通（True 通孔 / False 盲孔）
    坐标系: 孔轴线过 pos 沿 axis_dir。
    用途: 配合 side_shaft 的铰链孔、安装孔、任意方向开孔。
    注意: 通孔(through=True)深度必须覆盖整个壁厚;盲孔(through=False)深度必须小于壁厚。
    """

    px, py, pz = pos[0], pos[1], pos[2]
    # axis_dir 防御归一:LLM 常写 'z'/'Z'/'+Z'/带空格——统一到 '+z' 等规范值,
    # 否则方向表 KeyError 使整个 build 失败。
    axis_dir = str(axis_dir).strip().lower()
    if axis_dir in ("z", "+z"): axis_dir = "+z"
    elif axis_dir == "-z": axis_dir = "-z"
    elif axis_dir in ("x", "+x"): axis_dir = "+x"
    elif axis_dir == "-x": axis_dir = "-x"
    elif axis_dir in ("y", "+y"): axis_dir = "+y"
    elif axis_dir == "-y": axis_dir = "-y"
    # through=true:刀具沿轴向两端延伸(3x depth),保证从任一表面 pos 都能穿透
    # 基体(原实现圆柱中心对 pos、深度照用,pos 在表面时只切半个板厚);
    # 盲孔保持精确深度(中心 ±depth/2)。
    # depth 缺省防御:贯穿孔(through=True)LLM 常省略 depth(认为贯穿无需给深度)
    # ——用大深度保证穿透;盲孔缺 depth 由 constraints 硬约束(blind_hole_depth)
    # 在 compose 前拦截(422 回传 LLM),不会静默生成错误几何。
    if depth is None:
        depth = 1e4 if through else 1.0
    _eff_depth = depth * 3 if through else depth
    # 旋转:圆柱默认沿 +Z(底面中心在原点,向 +Z 延伸 depth),按 axis_dir 转到目标方向
    # rotate 绕原点旋转后,圆柱沿目标方向延伸,底面中心仍过原点。
    rot_map = {
        "+x": ("(0,1,0)", 90), "-x": ("(0,1,0)", -90),
        "+y": ("(1,0,0)", -90), "-y": ("(1,0,0)", 90),
        "+z": ("(0,0,1)", 0), "-z": ("(0,0,1)", 180),
    }
    axis_vec, angle = rot_map.get(axis_dir, ("(0,1,0)", 90))
    # translate 让圆柱几何中心落在 pos:旋转后圆柱中心在 目标方向*depth/2 处,整体平移到 pos
    dir_vec = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}[axis_dir]
    off = (dir_vec[0]*_eff_depth/2, dir_vec[1]*_eff_depth/2, dir_vec[2]*_eff_depth/2)
    code = f"# === {name}: side hole axis={axis_dir} ===\n"
    code += f"_hole = Part.makeCylinder({radius}, {_eff_depth})\n"
    code += f"_hole.rotate(FreeCAD.Vector(0,0,0), FreeCAD.Vector{axis_vec}, {angle})\n"
    code += f"_hole.translate(FreeCAD.Vector({px - off[0]}, {py - off[1]}, {pz - off[2]}))\n"
    code += f"_obj = doc.addObject('Part::Feature', '{name}')\n"
    code += f"_obj.Shape = _hole\n"
    code += f"_shape = _hole\n"  # 关键:暴露给 generate_model 的 _shape 引用
    return code

def generate_extruded_profile(name, profile_points, height, pos=(0, 0, 0)):
    """轮廓拉伸：闭合多边形轮廓沿 Z 拉伸成实体。
    参数:
        name           零件名
        profile_points 2D 轮廓点列表（[[x,y],...]，闭合多边形）
        height         拉伸高度（mm）
        pos            放置位置，默认原点
    坐标系: 轮廓在 XY 平面，沿 +Z 拉伸。
    用途: 梁、导轨、结构型材、异形截面件。
    """

    v = _v(pos)
    if len(profile_points) < 3:
        return f"# {name}: extruded profile (need >=3 points)\n"
    pts_str = ", ".join("FreeCAD.Vector(%s, %s, 0)" % (p[0], p[1]) for p in profile_points)
    # Close polygon by repeating first point
    first = profile_points[0]
    pts_str += ", FreeCAD.Vector(%s, %s, 0)" % (first[0], first[1])
    return f"""# === {name}: extruded profile ===
_wire = Part.makePolygon([{pts_str}])
_face = Part.Face(_wire)
_shape = _face.extrude(FreeCAD.Vector(0, 0, {height}))
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""


def generate_revolved_solid(name, profile_points, axis_start, axis_end, angle_deg=360, pos=(0, 0, 0)):
    """旋转体：轮廓绕轴旋转生成实体。
    参数:
        name          零件名
        profile_points 轮廓点列表（[[x,y],...]）
        axis_start    旋转轴起点
        axis_end      旋转轴终点
        angle_deg     旋转角度（默认 360）
        pos           放置位置，默认原点
    坐标系: 旋转轴由 axis_start→axis_end 定义。
    用途: 轮、带轮、法兰、锥体、回转类零件。
    """

    v = _v(pos)
    if len(profile_points) < 2:
        return f"# {name}: revolved (need >=2 points)\n"
    pts = ", ".join("FreeCAD.Vector(%s, %s, 0)" % (p[0], p[1]) for p in profile_points)
    return f"""# === {name}: revolved solid ===
_wire = Part.makePolygon([{pts}, FreeCAD.Vector({profile_points[0][0]}, {profile_points[0][1]}, 0)])
_face = Part.Face(_wire)
_axis_start = FreeCAD.Vector{tuple(axis_start)}
_axis_end = FreeCAD.Vector{tuple(axis_end)}
_shape = _face.revolve(_axis_start, _axis_end, {angle_deg})
_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _shape
"""



def generate_fillet(name, base_shape_code, edge_indices, radius, pos=(0, 0, 0)):
    """圆角：给已有形状添加圆角（去应力/外观）。
    参数:
        name             结果零件名
        base_shape_code  基体形状的 FreeCAD 代码
        edge_indices     边索引列表
        radius           圆角半径（mm）
        pos              放置位置，默认原点
    用途: 边角倒圆、去应力、外观修饰。
    """

    v = _v(pos)
    edges_str = ", ".join(str(e) for e in edge_indices)
    return f"""# === {name}: fillet r={radius} ===
_fillet_shape = {base_shape_code}.makeFillet({radius}, [{edges_str}])
_fillet_shape.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _fillet_shape
"""


def generate_pattern(name, base_shape_code, direction, count, spacing, pos=(0, 0, 0)):
    """阵列：沿指定方向复制形状（线性阵列）。
    参数:
        name             结果零件名
        base_shape_code  基体形状的 FreeCAD 代码
        direction        阵列方向（'x'/'y'/'z'）
        count            复制数量
        spacing          间距（mm）
        pos              放置位置，默认原点
    用途: 螺栓孔阵列、翅片、加强筋、散热齿。
    """

    v = _v(pos)
    dx, dy, dz = direction[0], direction[1], direction[2]
    code = f"""# === {name}: pattern {count}x ===
_pattern_shapes = []
for _i in range({count}):
    _copy = {base_shape_code}.copy()
    _copy.translate(FreeCAD.Vector({dx} * _i * {spacing}, {dy} * _i * {spacing}, {dz} * _i * {spacing}))
    _pattern_shapes.append(_copy)
_combined = _pattern_shapes[0]
for _s in _pattern_shapes[1:]:
    _combined = _combined.fuse(_s)
_combined.translate({v})
_obj = doc.addObject('Part::Feature', '{name}')
_obj.Shape = _combined
"""
    return code


PRIMITIVE_REGISTRY = {
    "shell_box": {
        "fn": generate_shell_box,
        "description": "Hollow box with walls, solid bottom, open top. For seats, containers, enclosures.",
        "params": {
            "name": "Part name",
            "L": "Length (X direction, mm)",
            "W": "Width (Y direction, mm)",
            "H": "Height (Z direction, mm)",
            "t": "Wall thickness (mm)",
            "pos": "Position (x,y,z) tuple, default (0,0,0)"
        }
    },
    "wedge_box": {
        "fn": generate_wedge_box,
        "description": "Tapered hollow box — width transitions along length. For parts that need to narrow.",
        "params": {
            "name": "Part name",
            "L1": "Length (mm)",
            "L2": "Width at narrow end (mm)",
            "W": "Width at wide end (mm)",
            "H": "Height (mm)",
            "t": "Wall thickness (mm)",
            "pos": "Position (x,y,z)"
        }
    },
    "u_channel": {
        "fn": generate_u_channel,
        "description": "U-shaped channel — two side walls + bottom, open top. Use ends='both' for standalone trough (walls on both ends), ends='open' for open-ended section, ends='start'/'end' for one-sided wall.",
        "params": {
            "name": "Part name",
            "L": "Length along X (mm)",
            "W": "Width along Y (mm)",
            "H": "Height along Z (mm)",
            "t": "Wall thickness (mm)",
            "pos": "Position (x,y,z), default (0,0,0)",
            "ends": "End walls: 'open' (none), 'start' (x=0), 'end' (x=L), 'both' (default: 'open')"
        }
    },
    "hinge_connection": {
        "fn": generate_hinge_connection,
        "description": "Horizontal hinge connecting two parts — ears + pin. For folding, flipping, pivoting connections.",
        "params": {
            "name": "Base name",
            "pos": "Pin center position (x,y,z)",
            "axis_dir": "Pin axis direction: 'x' or 'y'",
            "pin_length": "Total pin length (mm)",
            "pin_r": "Pin radius (mm)",
            "ear_count_a": "Number of ears on part A (default 2)",
            "ear_count_b": "Number of ears on part B (default 1)",
            "ear_w": "Ear width along pin axis (mm, default 12)",
            "ear_h": "Ear height (mm, default 12)",
            "ear_depth": "Ear depth perpendicular to pin (mm, default 10)"
        }
    },
    "bellows_seal": {
        "fn": generate_bellows_seal,
        "description": "Flexible bellows seal — concentric rings. For flexible sealing, expansion joints, protective covers.",
        "params": {
            "name": "Object name",
            "center": "Center position (x,y,z)",
            "outer_r": "Outer radius (mm)",
            "inner_r": "Inner radius (mm)",
            "num_rings": "Number of convolutions",
            "pitch": "Spacing between rings (mm)",
            "axis": "Stack direction: 'z' or 'y' (default 'z')"
        }
    },
"u_channel_bellows": {
        "fn": generate_u_channel_bellows,
        "description": "U-channel bellows — flexible section matching u_channel cross-section, both ends open. For connecting two u_channel sections.",
        "params": {
            "name": "Object name",
            "L": "Length along X (mm)",
            "W": "Channel width along Y (mm)",
            "H": "Channel height along Z (mm)",
            "t": "Wall thickness (mm)",
            "num_folds": "Number of bellows folds",
            "pos": "Position (x,y,z) tuple, default (0,0,0)"
        }
    },
    "fuse": {
        "fn": generate_fuse,
        "description": "Boolean union — fuse multiple parts into one solid. For combining overlapping bodies.",
        "params": {
            "name": "Result part name",
            "part_names": "List of part names to fuse together"
        }
    },
    "subtract": {
        "fn": generate_subtract,
        "description": "Boolean subtraction — cut tool shapes from a base shape. For hollow shells (sphere minus inner sphere), through holes (shape minus cylinder), slots, cutouts.",
        "params": {
            "name": "Result part name",
            "base": "Base part name to cut from",
            "tools": "List of tool part names to subtract"
        }
    },
    "sphere": {
        "fn": generate_sphere,
        "description": "Solid sphere. For balls, knobs, spherical joints, buffer stops.",
        "params": {
            "name": "Part name",
            "r": "Radius (mm)",
            "pos": "Position (x,y,z) tuple, default (0,0,0)"
        }
    },
    "cylinder": {
        "fn": generate_cylinder,
        "description": "Solid cylinder, axis ALWAYS along +Z (height is Z direction), pos = BOTTOM CENTER (cylinder extends from pos up to pos+Z*h). For shafts, pins, dowels, rollers. NOT for holes in other directions — use side_hole for +x/-x/+y/-y holes.",
        "params": {
            "name": "Part name",
            "r": "Radius (mm)",
            "h": "Height (mm) along Z",
            "pos": "BOTTOM CENTER position (x,y,z); cylinder occupies z from pos.z to pos.z+h"
        }
    },
    "plate": {
        "fn": generate_plate,
        "description": "Flat rectangular plate.",
        "params": {
            "name": "Part name",
            "L": "Length (mm)",
            "W": "Width (mm)",
            "t": "Thickness (mm)",
            "pos": "Position (x,y,z)"
        }
    },
    "side_shaft": {
        "fn": generate_side_shaft,
        "description": "Side shaft extending from a wall surface. For pivot axles on channel/trough side walls. Pair on opposite walls for coaxial rotation.",
        "params": {
            "name": "Object name", "pos": "Center on wall surface (x,y,z)", "axis_dir": "'+y' or '-y'",
            "length": "Shaft length (mm)", "radius": "Shaft radius (mm)",
            "mount_t": "Mount plate thickness (0=none, mm)", "mount_r": "Mount plate radius (mm)"
        }
    },
    "side_hole": {
        "fn": generate_side_hole,
        "description": "HOLE (cut tool) in ANY direction — axis_dir '+x'/'-x'/'-y'/'+y'/'-z'/'+z'. pos = hole CENTER. depth = hole depth. For side/face holes in non-Z directions (e.g. front face hole along +x). "
                       "通孔/盲孔 (through=False): depth < wall thickness, bottom sealed. "
                       "贯穿孔 (through=True): depth >= wall thickness, both ends open.",
        "params": {
            "name": "Object name", "pos": "Hole CENTER (x,y,z)", "axis_dir": "'+x'/'-x'/'-y'/'+y'/'-z'/'+z'",
            "depth": "Hole depth (mm)", "radius": "Hole radius (mm)",
            "through": "True=贯穿孔 (both ends open), False=通孔/盲孔 (bottom sealed, default)"
        }
    },

    "extruded_profile": {
        "fn": generate_extruded_profile,
        "description": "Extruded profile from a closed 2D polygon. For beams, rails, structural profiles.",
        "params": {
            "name": "Part name",
            "profile_points": "List of [x,y] vertices forming closed polygon",
            "height": "Extrusion height (mm)",
            "pos": "Position (x,y,z)"
        }
    },
    "revolved_solid": {
        "fn": generate_revolved_solid,
        "description": "Revolved solid from a profile around an axis. For wheels, pulleys, flanges.",
        "params": {
            "name": "Part name",
            "profile_points": "List of [x,y] profile points",
            "axis_start": "[x,y,z] start of revolution axis",
            "axis_end": "[x,y,z] end of revolution axis",
            "angle_deg": "Revolution angle in degrees (default 360)",
            "pos": "Position (x,y,z)"
        }
    },
    "fillet": {
        "fn": generate_fillet,
        "description": "Add fillets (rounded edges) to an existing shape.",
        "params": {
            "name": "Object name",
            "base_shape_code": "Variable name of base shape",
            "edge_indices": "List of edge indices to fillet",
            "radius": "Fillet radius (mm)",
            "pos": "Position (x,y,z)"
        }
    },
    "pattern": {
        "fn": generate_pattern,
        "description": "Linear pattern replicating a shape. For bolt holes, fins, ribs.",
        "params": {
            "name": "Object name",
            "base_shape_code": "Variable name of base shape",
            "direction": "[dx,dy,dz] pattern direction",
            "count": "Number of copies",
            "spacing": "Spacing between copies (mm)",
            "pos": "Position (x,y,z)"
        }
    },

}

def list_primitives():
    """Return primitive descriptions for LLM tool definitions.

    desc_cn 取自 generate_* 函数 docstring 首行(中文一句话用途),
    供 system prompt 动态名录使用,避免 prompt 手写清单与注册表脱节。
    """
    out = {}
    for k, v in PRIMITIVE_REGISTRY.items():
        entry = {"description": v["description"], "params": v["params"]}
        fn = v.get("fn")
        doc = (getattr(fn, "__doc__", "") or "").strip().split("\n")[0].strip()
        if doc:
            entry["desc_cn"] = doc
        out[k] = entry
    return out


def _ascii_alias(idx, ptype="obj"):
    """Stable ASCII object name for a part index, with readable type prefix.

    FreeCAD 0.19 对象内部名必须 ASCII;用类型前缀+序号保证可读(如 sphere_0、subtract_4),
    中文名保留在 Label(STEP 导出时作为 PRODUCT 名)。
    """
    return "%s_%d" % (ptype, idx)


# 参数别名归一:LLM 常用的同义参数名 → 原语签名参数名。
# 只在"签名缺该参数但存在别名"时转换;不改变已有合法参数。
_PARAM_ALIASES = {
    "t": ("H", "T", "th", "thickness", "thk", "wall_thickness", "wall_t"),  # 厚度/壁厚
    "L": ("len", "length"),                               # 长
    "W": ("width", "wid"),                                # 宽
    "d": ("D", "diameter", "dia"),                        # 直径
    "r": ("R", "radius"),
    "depth": ("dep", "deep", "depth_mm"),
    "h": ("H", "height", "height_mm"),
}


def _normalize_params(ptype, params):
    """按原语函数签名归一参数:别名映射 + 未知参数剔除(带告警注释)。"""
    import inspect
    fn = PRIMITIVE_REGISTRY.get(ptype, {}).get("fn")
    if fn is None:
        return params
    try:
        sig = set(inspect.signature(fn).parameters)
    except (ValueError, TypeError):
        return params
    out = {}
    dropped = []
    for k, v in params.items():
        if k in sig:
            out[k] = v
            continue
        mapped = False
        for canon, aliases in _PARAM_ALIASES.items():
            if k in aliases and canon in sig and canon not in out:
                out[canon] = v
                mapped = True
                break
        if not mapped:
            dropped.append(k)
    # 注意:dropped 不进 params(**传参会炸);由调用方写代码注释
    return out, dropped


def generate_model(parts, joints, output_name="Design"):
    code = f'doc = FreeCAD.newDocument("{output_name}")\n'
    code += "_NAME_MAP = {}\n"
    code += "_INTERMEDIATE_NAMES = set()\n\n"
    all_part_names = []
    # Collect intermediate names (tools used in boolean ops)
    intermediate_names = set()
    # 防呆:裸 cylinder 当"刀具"(名含 刀具/tool/cut)且未被 subtract 引用
    # → 跳过生成(不切割还混入装配=静默错误)。显式 subtract 引用的保留。
    _cut_names = set()
    for part in parts:
        n = (part.get("params") or {}).get("name", "")
        if part.get("type") == "cylinder" and any(
                k in str(n) for k in ("刀具", "tool", "cut")):
            _cut_names.add(n)
    _referenced = set()
    for part in parts:
        if part.get("type") == "subtract":
            _referenced.update((part.get("params") or {}).get("tools") or [])
    _skip_cylinders = _cut_names - _referenced

    # side_hole 的 base:自动合成 subtract(孔必须切进基体——原实现把孔当
    # 独立零件、base 参数被丢,孔全部游离不切割)。同 base 多孔合并一次切。
    _holes_by_base = {}
    for part in parts:
        if part.get("type") == "side_hole":
            _b = (part.get("params") or {}).get("base")
            if _b:
                _holes_by_base.setdefault(_b, []).append(
                    (part.get("params") or {}).get("name"))
    if _holes_by_base:
        # name 用独立键 base#cut:与 base 同名会让 _NAME_MAP 覆盖,
        # intermediate 删除循环误删 subtract 结果(留下未切孔的原始板)。
        # _label 保留 base 名作显示名(装配体零件列表仍显示"底板")。
        parts = list(parts) + [
            {"type": "subtract",
             "params": {"name": _b + "#cut", "base": _b, "tools": _holes,
                        "_label": _b}}
            for _b, _holes in _holes_by_base.items()
        ]
    for part in parts:
        ptype = part["type"]
        params = part.get("params", {})
        if ptype == "subtract":
            intermediate_names.add(params.get("base", ""))
            for t in params.get("tools", []):
                intermediate_names.add(t)
        elif ptype == "fuse":
            for p in params.get("part_names", []):
                intermediate_names.add(p)
    if intermediate_names:
        code += "_INTERMEDIATE_NAMES.update({"
        code += ", ".join(repr(n) for n in intermediate_names)
        code += "})\n\n"
    idx = 0

    # 拓扑排序:布尔/融合引用的工具(base/tools/part_names)必须先于使用者生成,
    # 否则后加的刀具(如方孔刀具 extruded_profile)排在使用它的 subtract 之后,
    # 生成代码里 eval 不到对应 shape,减法被跳过 → 孔切不出来。
    def _part_deps(p):
        params = p.get("params", {})
        t = p.get("type")
        if t == "subtract":
            deps = [params.get("base", "")] + list(params.get("tools", []) or [])
        elif t == "fuse":
            deps = list(params.get("part_names", []) or [])
        else:
            deps = []
        return [d for d in deps if d]

    def _order_parts(ps):
        by_name = {p.get("params", {}).get("name"): p for p in ps if p.get("params", {}).get("name")}
        ordered = []
        done = set()
        def visit(p):
            pid = id(p)
            if pid in done:
                return
            done.add(pid)
            for d in _part_deps(p):
                dep = by_name.get(d)
                if dep:
                    visit(dep)
            ordered.append(p)
        for p in ps:
            visit(p)
        return ordered

    for part in _order_parts(parts):
        ptype = part["type"]
        params = dict(part.get("params", {}))
        if ptype not in PRIMITIVE_REGISTRY:
            # 不再静默跳过:落注释进生成代码,stdout/结果可见(治零件无故消失)
            code += "# [WARN] 未知原语 '%s'(零件 %s 被跳过)。可用: %s\n" % (
                ptype, params.get("name", "?"), ",".join(sorted(PRIMITIVE_REGISTRY.keys())))
            continue
        if params.get("name") in _skip_cylinders:
            code += ("# [WARN] 刀具圆柱 '%s' 未被 subtract 引用——不会切割任何基体,"
                     "已跳过。请改用 side_hole(base=基体名) 或 subtract 显式引用。\n"
                     % params["name"])
            continue
        if ptype == "side_hole" and not params.get("base"):
            code += ("# [WARN] side_hole '%s' 缺 base 参数——孔不会切进任何材料"
                     "(游离圆柱),已跳过。必须指定 base=要开孔的零件名。\n"
                     % params.get("name", "?"))
            continue
        # 参数别名归一:LLM 常用 H/T/thickness/height 表达厚度等,
        # 按原语签名过滤 + 常见别名映射,防 TypeError(H vs t)。
        _label = params.pop("_label", None)  # 合成件显式显示名(须在归一前取走)
        params, dropped_params = _normalize_params(ptype, params)
        if dropped_params:
            code += "# [param-normalize] %s: dropped unknown params: %s\n" % (
                part.get("params", {}).get("name", ptype), ",".join(dropped_params))
        orig_name = params.get("name", f"part_{len(all_part_names)}")
        all_part_names.append(orig_name)
        alias = _ascii_alias(idx, ptype)
        params["name"] = alias
        code += PRIMITIVE_REGISTRY[ptype]["fn"](**params) + "\n"
        # Save shape reference + restore original label + record map
        code += f"_NAME_MAP[{orig_name!r}] = {alias!r}\n"
        code += f"_{alias}_shape = _shape\n"
        code += f"doc.getObject({alias!r}).Label = {(_label or orig_name)!r}\n"
        idx += 1

    for joint in joints:
        jtype = joint["type"]
        params = dict(joint.get("params", {}))
        if jtype not in PRIMITIVE_REGISTRY:
            continue
        orig_name = params.get("name", f"part_{len(all_part_names)}")
        all_part_names.append(orig_name)
        alias = _ascii_alias(idx, jtype)
        params["name"] = alias
        code += PRIMITIVE_REGISTRY[jtype]["fn"](**params) + "\n"
        code += f"_NAME_MAP[{orig_name!r}] = {alias!r}\n"
        code += f"_{alias}_shape = _shape\n"
        code += f"doc.getObject({alias!r}).Label = {orig_name!r}\n"
        idx += 1

    code += "doc.recompute()\n"
    # Remove intermediate (boolean tool/base) objects so only final parts remain
    code += """\n# === Remove intermediate objects ===\n"""
    code += """for _iname in _INTERMEDIATE_NAMES:\n"""
    code += """    _ialias = _NAME_MAP.get(_iname, _iname)\n"""
    code += """    _iobj = doc.getObject(_ialias)\n"""
    code += """    if _iobj:\n"""
    code += """        doc.removeObject(_ialias)\n"""
    code += """doc.recompute()\n"""
    return code


def generate_model_export(parts, joints, output_name="Design", step_path="/tmp/output.step", export_dir=None):
    """Generate complete FreeCAD code including export.
    
    Creates a labeled Part::Feature and exports via Import (preserves Label as PRODUCT name).
    """
    if export_dir is None:
        export_dir = os.path.dirname(step_path)
    code = """import FreeCAD, Part

"""
    code += generate_model(parts, joints, output_name)

    # Derive readable label from part names (exclude intermediates)
    if parts:
        part_names = []
        intermediate_names = set()
        for part in parts:
            name = part.get("params", {}).get("name", "")
            if not name:
                continue
            ptype = part["type"]
            if ptype == "subtract":
                intermediate_names.add(part["params"].get("base", ""))
                for t in part["params"].get("tools", []):
                    intermediate_names.add(t)
            elif ptype == "fuse":
                for p in part["params"].get("part_names", []):
                    intermediate_names.add(p)
        for part in parts:
            name = part.get("params", {}).get("name", "")
            if name and name not in intermediate_names:
                part_names.append(name)
        label = "、".join(part_names[:5])
        if len(part_names) > 5:
            label += f" 等{len(part_names)}件"
        label = label or output_name
    else:
        label = output_name

    cad_dir_for_export = os.path.dirname(step_path)
    design_prefix = os.path.splitext(os.path.basename(step_path))[0]
    escaped_cad = cad_dir_for_export.replace("'", "\\'")
    escaped_prefix = design_prefix.replace("'", "\\'")
    # Create App::Part assembly with only final (non-intermediate) parts
    # Label 用「装配_xxx」前缀,避免与零件 Label 重名(重名会导致 FreeCAD 自动加 001)
    code += f"\n# === Create assembly ===\n"
    code += f"_assy = doc.addObject('App::Part', 'Assembly')\n"
    code += f"_assy.Label = '装配_{label}'\n"
    code += "for _obj in doc.Objects:\n"
    code += "    if hasattr(_obj, 'Shape') and _obj.Shape and _obj.TypeId != 'App::Part':\n"
    code += "        _assy.addObject(_obj)\n"
    code += "doc.recompute()\n"

    code += f"\n# === Export ===\n"
    code += "import os, Mesh, Import\n"
    code += f"_cad_dir = '{escaped_cad}'\n"
    code += f"_design_prefix = '{escaped_prefix}'\n"
    code += "_asm_step = os.path.join(_cad_dir, _design_prefix + '.step')\n"
    code += "_export_objs = [o for o in doc.Objects if hasattr(o, 'Shape') and o.Shape and o.TypeId != 'App::Part']\n"
    code += "Import.export(_export_objs, _asm_step)\n"
    code += "print('EXPORTED:' + _asm_step)\n"
    code += """_all_meshes = []
for _obj in doc.Objects:
    if not hasattr(_obj, 'Shape') or not _obj.Shape or not _obj.Shape.isValid():
        continue
    if getattr(_obj.Shape, 'Volume', 0) <= 0:
        continue
    if _obj.TypeId == 'App::Part':
        continue
    _m = Mesh.Mesh(_obj.Shape.tessellate(0.1))
    _all_meshes.append(_m)
if _all_meshes:
    _combined = Mesh.Mesh()
    for _m in _all_meshes:
        _combined.addMesh(_m)
    _combined.write(os.path.join(_cad_dir, _design_prefix + '.stl'))
    print('STL_EXPORTED:' + os.path.join(_cad_dir, _design_prefix + '.stl'))
print('DONE')
"""
    return code
