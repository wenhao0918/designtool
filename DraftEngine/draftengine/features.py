"""DraftEngine 模式匹配层:特征识别 + 零件分类。

把几何数据(面/边/环)拆到底层,用模式匹配识别工程语义:
- 通孔:圆柱面 + 两端开口(延伸到包围盒边界)
- 盲孔:圆柱面 + 一端平面封底
- 沉头孔:同轴大小圆柱面
- 轴段:同轴圆柱面序列
- 平面:基准面
- 匹配不上的特征不进列表——出图层降级为"基础视图 + 手动标注提示"

依赖 geometry.face_attrs 提供面属性缓存。
"""

from . import geometry as G

AXIS_NAMES = "XYZ"

# FreeCAD App(经 geometry 模块)
App = G.App


def _axis_name(axis_main):
    return AXIS_NAMES[axis_main]


def _is_concave(face, axis_vec, center):
    """圆柱面凹凸判定:孔(凹)= 法向指向轴线;轴(凸)= 法向背离。

    取面上一点 p,径向向量 (p - 轴线垂足),与法向点积:
      凹(孔): 法向指向轴线 → dot < 0
      凸(轴): 法向背离轴线 → dot > 0
    """
    try:
        p = face.valueAt(0.5, 0.5)
        n = face.normalAt(0.5, 0.5)
        d = axis_vec.normalize()
        t = (p - center).dot(d)
        foot = center + d * t
        rad_vec = p - foot
        return rad_vec.dot(n) < 0
    except Exception:
        return True  # 无法判定时按孔处理(保守)


def _is_coaxial(a1, c1, a2, c2, tol=0.05):
    """两个圆柱面是否同轴(主轴方向一致 + 轴线垂直距离小)。"""
    if a1 != a2:
        return False
    return G.axis_dist2(c1, c2, a1) < tol * tol


class FeatureRecognizer:
    """特征识别器:面属性 → 工程特征列表。"""

    def __init__(self, shape, bbox):
        self.shape = shape
        self.bbox = bbox
        self.faces = shape.Faces
        self.attrs = G.all_face_attrs(shape)
        self.features = []

    # ---- 识别入口 ----
    def recognize(self):
        self._recognize_holes()
        self._recognize_bosses()
        self._recognize_shaft_segments()
        self._recognize_walls()
        return self.features

    # ---- 壁厚(空心壳体:同心球面外壳+内腔) ----
    def _recognize_walls(self):
        spheres = [a for a in self.attrs
                   if a["type"] == "sphere" and a.get("surf_center")]
        groups = {}
        for a in spheres:
            c = a["surf_center"]
            key = (round(c.x, 1), round(c.y, 1), round(c.z, 1))
            groups.setdefault(key, set()).add(round(a["radius"], 2))
        for key, radii in groups.items():
            if len(radii) < 2:
                continue
            rs = sorted(radii)
            t = round(rs[-1] - rs[0], 2)
            # 合理壁厚:不太薄(≥0.5,标注意义),不太厚(≤外径 80%)
            if 0.5 <= t <= rs[-1] * 0.8:
                self.features.append({
                    "type": "wall", "subtype": "sphere",
                    "thickness": t, "r_out": rs[-1], "r_in": rs[0],
                    "center": list(key),
                })
                break

    # ---- 凸台(凸圆柱面,如 complex.step 的 Φ40 圆柱凸台) ----
    def _recognize_bosses(self):
        seen = set()
        for i, a in enumerate(self.attrs):
            if a["type"] != "cylinder" or a["axis_main"] != 2:
                continue
            face = self.faces[i]
            if not _is_concave(face, a["axis"], a["center"]):
                # 凸圆柱 = 凸台侧面
                fb = face.BoundBox
                zmin, zmax = fb.ZMin, fb.ZMax
                key = (round(a["radius"], 2),
                       round(a["center"].x, 1), round(a["center"].y, 1))
                if key in seen:
                    continue
                seen.add(key)
                self.features.append({
                    "type": "boss", "radius": a["radius"],
                    "center": a["center"],
                    "zmin": zmin, "zmax": zmax,
                    "height": zmax - zmin,
                })

    # ---- 孔(通孔/盲孔/沉头孔) ----
    def _cylinder_faces(self):
        return [(i, a) for i, a in enumerate(self.attrs) if a["type"] == "cylinder"]

    def _hole_center(self, attrs):
        """孔中心 = 圆柱面端面圆心,沿轴向移到面中心。

        半圆柱面(布尔切开)只有一端有端面圆边;端面圆 c + 面深 d/2
        沿轴向 = 孔的真实中心。
        """
        face = self.faces[attrs["_idx"]]
        r = attrs["radius"]
        ax = attrs["axis_main"]
        centers = []
        for e in face.Edges:
            try:
                c = e.Curve
            except Exception:
                continue
            if c.TypeId == "Part::GeomCircle" and abs(c.Radius - r) < 0.1:
                centers.append(c.Center)
        if centers:
            n = len(centers)
            c = App.Vector(
                sum(x.x for x in centers) / n,
                sum(x.y for x in centers) / n,
                sum(x.z for x in centers) / n)
            # 沿轴向移到面中心(半圆柱:端面圆心 + 面深一半)
            d = self._face_depth(attrs, ax)
            fb = face.BoundBox
            # 面 bbox 中心
            fc = fb.Center
            # 端面圆心在轴向的投影,和面中心在轴向的差
            axv = [0.0, 0.0, 0.0]
            axv[ax] = 1.0
            c_ax = (c.x * axv[0] + c.y * axv[1] + c.z * axv[2])
            fc_ax = (fc.x * axv[0] + fc.y * axv[1] + fc.z * axv[2])
            shift = fc_ax - c_ax
            return App.Vector(c.x + axv[0] * shift, c.y + axv[1] * shift, c.z + axv[2] * shift)
        # 兜底:bbox 中心
        return face.BoundBox.Center

    def _recognize_holes(self):
        cyls = self._cylinder_faces()

        # 1. 过滤凹圆柱面(孔)
        hole_cyls = []
        for i, attrs in cyls:
            attrs["_idx"] = i
            face = self.faces[i]
            try:
                axis_vec = attrs["axis"]
            except Exception:
                continue
            if _is_concave(face, axis_vec, attrs["center"]):
                hole_cyls.append((i, attrs))

        # 2. 合并同轴同半径的半圆柱(布尔切出的两半)
        merged = []  # (radius, axis, center, depth, members)
        for i, attrs in hole_cyls:
            r = attrs["radius"]
            ax = attrs["axis_main"]
            c = self._hole_center(attrs)
            d = self._face_depth(attrs, ax)
            # 找已合并组里同轴同半径的
            hit = None
            for g in merged:
                if g[0] != r or g[1] != ax:
                    continue
                if not _is_coaxial(ax, c, g[1], g[2], tol=3.0):
                    continue
                hit = g
                break
            if hit:
                # 合并:中心取平均,深度取更大的(半圆柱各占一段)
                hit[2] = App.Vector((hit[2].x + c.x) / 2, (hit[2].y + c.y) / 2, (hit[2].z + c.z) / 2)
                hit[3] = max(hit[3], d)
                hit[4].append(i)
            else:
                merged.append([r, ax, c, d, [i]])

        # 3. 分组成孔:同轴 + 半径不同 + 轴向重叠 = 沉头孔
        #    小径先处理(找大径合并),避免大径先成孔后小径找不到
        used_groups = set()
        order = sorted(range(len(merged)), key=lambda i: merged[i][0])
        for gi in order:
            if gi in used_groups:
                continue
            r, ax, c, d, members = merged[gi]
            # 找同轴、半径更大的组(沉头大径,且更浅)
            cb_r = None
            for gj, g2 in enumerate(merged):
                if gj == gi or gj in used_groups:
                    continue
                r2, ax2, c2, d2, _ = g2
                if r2 <= r:
                    continue
                if not _is_coaxial(ax, c, ax2, c2, tol=3.0):
                    continue
                if d2 < d * 0.8:  # 沉头大径显著浅
                    cb_r = r2
                    used_groups.add(gj)  # 大径组并入沉头
                    break
            if cb_r:
                self.features.append({
                    "type": "hole", "subtype": "counterbore",
                    "radius": r, "diameter": r * 2,
                    "counterbore_radius": cb_r,
                    "counterbore_diameter": cb_r * 2,
                    "axis": ax, "center": (c.x, c.y, c.z),
                    "depth": d,
                })
                used_groups.add(gi)
                continue

            # 通孔/盲孔
            through = self._is_through_merged(c, ax, d, r)
            # 非 Z 向通孔:中心沿轴向对齐到 bbox 中心(通孔必贯穿零件)
            if through and ax != 2:
                if ax == 0:
                    c = App.Vector((self.bbox["xmin"] + self.bbox["xmax"]) / 2, c.y, c.z)
                elif ax == 1:
                    c = App.Vector(c.x, (self.bbox["ymin"] + self.bbox["ymax"]) / 2, c.z)
            self.features.append({
                "type": "hole",
                "subtype": "through" if through else "blind",
                "radius": r, "diameter": r * 2,
                "axis": ax, "center": (c.x, c.y, c.z),
                "depth": d,
            })
            used_groups.add(gi)

    def _is_through_merged(self, center, axis_main, depth, radius):
        """通孔判定:孔沿轴向两端到达零件表面(合并后的中心±深度/2)。"""
        c = center
        bb = self.bbox
        r = radius
        if axis_main == 0:
            lo, hi = c.x - depth / 2, c.x + depth / 2
            return abs(lo - bb["xmin"]) < r * 0.5 or abs(hi - bb["xmax"]) < r * 0.5
        elif axis_main == 1:
            lo, hi = c.y - depth / 2, c.y + depth / 2
            return abs(lo - bb["ymin"]) < r * 0.5 or abs(hi - bb["ymax"]) < r * 0.5
        else:
            lo, hi = c.z - depth / 2, c.z + depth / 2
            return abs(lo - bb["zmin"]) < r * 0.5 or abs(hi - bb["zmax"]) < r * 0.5

    def _face_depth(self, attrs, axis_main):
        """圆柱面深度 = 该面 bbox 沿轴长度(不是零件 bbox!)。

        attrs 里的 face 是圆柱面本身,它的 bbox 沿轴方向长度 = 孔深。
        """
        bb = attrs["_face_bb"]
        return (bb[0], bb[1], bb[2])[axis_main]

    def _is_through(self, attrs, axis_main):
        """通孔判定:圆柱面沿轴向延伸到达包围盒边界(两端开口)。"""
        c = attrs["center"]
        bb = self.bbox
        r = attrs["radius"]
        depth = self._face_depth(attrs, axis_main)
        if axis_main == 0:
            lo, hi = c.x - depth / 2, c.x + depth / 2
            return abs(lo - bb["xmin"]) < r * 0.5 or abs(hi - bb["xmax"]) < r * 0.5
        elif axis_main == 1:
            lo, hi = c.y - depth / 2, c.y + depth / 2
            return abs(lo - bb["ymin"]) < r * 0.5 or abs(hi - bb["ymax"]) < r * 0.5
        else:
            lo, hi = c.z - depth / 2, c.z + depth / 2
            return abs(lo - bb["zmin"]) < r * 0.5 or abs(hi - bb["zmax"]) < r * 0.5

    # ---- 轴段(同轴凸圆柱面序列) ----
    def _recognize_shaft_segments(self):
        cyls = self._cylinder_faces()
        if len(cyls) < 2:
            return
        # 只取凸圆柱面(轴段是外圆柱)
        cyls = [(i, a) for i, a in cyls
                if not _is_concave(self.faces[i], a["axis"], a["center"])]
        if len(cyls) < 2:
            return
        # 按主轴方向分组
        groups = {}
        for i, attrs in cyls:
            groups.setdefault(attrs["axis_main"], []).append((i, attrs))
        for axis_main, group in groups.items():
            if len(group) < 2:
                continue
            # 同轴检查(参考第一个的轴)
            ref = group[0][1]
            if not all(_is_coaxial(ref["axis_main"], ref["center"],
                                   a["axis_main"], a["center"]) for _, a in group):
                continue
            # 按轴向位置排序
            def axial(a):
                c = a["center"]
                return (c.x, c.y, c.z)[axis_main]
            group.sort(key=lambda x: axial(x[1]))
            # 每段一个轴段特征
            for idx, (i, attrs) in enumerate(group):
                self.features.append({
                    "type": "shaft_segment",
                    "radius": attrs["radius"],
                    "diameter": attrs["radius"] * 2,
                    "axis": axis_main,
                    "center": (attrs["center"].x, attrs["center"].y, attrs["center"].z),
                    "position": idx,
                    "axial_pos": axial(attrs),
                })


class PartClassifier:
    """零件类型分类:shaft / plate / general。"""

    @staticmethod
    def classify(bbox, features, shape=None):
        """返回 (part_type, main_axis)。

        shape 可选:用于检查平面存在(板类判断)。
        """
        # 轴类:≥2 个同轴轴段,长径比 > 2
        segs = [f for f in features if f["type"] == "shaft_segment"]
        if len(segs) >= 2:
            max_dia = max(f["diameter"] for f in segs)
            length = max(bbox["L"], bbox["W"], bbox["H"])
            if max_dia > 0 and length / max_dia > 2:
                axis = segs[0]["axis"]
                return "shaft", _axis_name(axis)

        # 板类:有孔 + 有大平面
        holes = [f for f in features if f["type"] == "hole"]
        has_big_plane = False
        if shape is not None:
            big_planes = [a for a in G.all_face_attrs(shape)
                          if a["type"] == "plane" and a["area"] > 50]
            has_big_plane = len(big_planes) >= 2
        if holes and has_big_plane:
            return "plate", "Z"

        # 通用
        return "general", "Z"
