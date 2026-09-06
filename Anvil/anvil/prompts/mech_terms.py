"""机械设计术语表——数据库驱动,用户可自助增改。

- 表: mech_terms(term 唯一,definition/geometry/modeling 三字段)
- 内置词条在首次建表时作为种子写入,之后用户可增/改/删
- agent 的 lookup_term / system prompt 注入都从数据库读

每个术语包含:
- definition:准确的专业含义
- geometry:在 3D 建模中对应的几何特征
- modeling:用当前原语体系建模时的指导(方向/深度/刀具选择等)
"""

import os
from datetime import datetime

# 内置种子词条(首次建表时写入;之后以数据库为准)
# 同义词用 aliases 字段表示,查询时自动解析到主术语
SEED_TERMS = {
    # ===== 基础几何体（译码表 1~99 段主词，别名归一第 2 级）=====
    "球": {
        "aliases": "圆球,球体,球形,sphere",
        "definition": "到定点(球心)距离等于定长(半径)的点的集合构成的回转体。",
        "geometry": "完全对称的曲面体,唯一参数=半径;球心=定位锚点(体中心)。",
        "modeling": "Part.makeSphere(r)。空心球=外球(r)−内球(r−壁厚),布尔减表达。",
        "application": "容器、球形把手、关节球、轴承滚珠。",
        "distinction": "与椭球的区别:球三半轴相等;椭球三半轴可不同。",
    },
    "长方体": {
        "aliases": "立方体,方块,方盒,矩形块,box",
        "definition": "六个矩形面围成的直平行六面体,三参数=长宽高。",
        "geometry": "长=宽=高时即正方体(不单占编号)。定位锚点=体中心。",
        "modeling": "Part.makeBox(L,W,H)。OCCT 天然锚在角点,内核平移至体中心。",
        "application": "底座、平板、机架、垫块。",
        "distinction": "正方体是长宽高相等的特例,译码时统一用长方体编码。",
    },
    "圆柱": {
        "aliases": "圆柱体,圆筒,筒,cylinder",
        "definition": "矩形绕其一边旋转形成的回转体,两参数=半径、高度。",
        "geometry": "上下底面为等径圆,轴线默认沿+Z;轴向中点=定位锚点(体中心)。",
        "modeling": "Part.makeCylinder(r,h)。横放用朝向算子(757,90,0),不用换 API。",
        "application": "轴、销、孔刀具、滚筒、立柱。",
        "distinction": "孔=圆柱作减法刀具;轴=圆柱本体。同一编码,角色由布尔算子决定。",
    },
    "圆锥": {
        "aliases": "锥体,锥形,圆台,cone",
        "definition": "直角三角形绕直角边旋转形成的回转体;顶半径>0 时为圆台。",
        "geometry": "三参数=底半径、顶半径、高度;顶半径=0 即尖锥。",
        "modeling": "Part.makeCone(r1,r2,h)。圆台与圆锥同编码,由顶半径区分。",
        "application": "漏斗、锥形定位销、过渡段、喷嘴。",
        "distinction": "与棱锥的区别:圆锥底面为圆,棱锥底面为多边形(用棱柱近似)。",
    },
    "圆环": {
        "aliases": "环形,环,torus",
        "definition": "圆绕同一平面内不与其相交的轴旋转形成的回转体。",
        "geometry": "两参数=主半径(回转轴到截面圆心)、截面半径(管半径)。",
        "modeling": "Part.makeTorus(R,r)。主半径>截面半径才成环。",
        "application": "O型圈、卡环、环形把手。",
        "distinction": "与圆柱孔的区别:圆环是回转管状实体,不是孔。",
    },
    "椭球": {
        "aliases": "椭圆球,ellipsoid",
        "definition": "三半轴 a/b/c 的二次曲面体,球的推广。",
        "geometry": "三参数=三半轴;三半轴相等退化为球。",
        "modeling": "Part.makeSphere(1).transformGeometry(缩放矩阵),底层=球×比例。",
        "application": "蛋形件、胶囊端部、反射面。",
        "distinction": "与球的区别:三半轴可不等。",
    },
    "棱柱": {
        "aliases": "正棱柱,六棱柱,三棱柱,prism",
        "definition": "正多边形底面沿垂直方向拉伸形成的直柱体。",
        "geometry": "三参数=边数、外接半径、高度;六棱柱最常用。",
        "modeling": "Part.makePolygon(顶点)+extrude(h)。外接半径=顶点到中心距离。",
        "application": "六角螺母外形、棱柱导轨、装饰柱。",
        "distinction": "与圆柱的区别:截面为正多边形;边数→∞ 逼近圆柱。",
    },
    # ===== 机械加工术语 =====
    "通孔": {  # 主术语(=盲孔,同义词)
        "aliases": "盲孔,blind hole",
        "definition": "不贯穿零件的孔,有确定深度,底部封闭。与贯穿孔相对。",
        "geometry": "圆柱形凹坑,深度 < 壁厚,孔底有材料。",
        "modeling": "side_hole 或 cylinder 作刀具,through=False,深度取孔深,"
                    "刀具中心在 外表面向内(深度/2)处;孔底必须留在材料内(深度 < 壁厚)。",
        "application": "紧固件安装(螺栓/螺钉孔)、定位孔、简单的流体通道、测量孔。"
                       "底部自然密封,适合需要密封的场合。",
        "distinction": "与贯穿孔的区别:通孔底部封闭,不通透;贯穿孔两端开口,完全贯通。"
                       "通孔深度必须小于壁厚,否则成为贯穿孔。",
    },
    "贯穿孔": {  # 主术语
        "aliases": "through hole,贯穿",
        "definition": "完全贯通材料两侧的孔,两端都开口。与通孔相对。",
        "geometry": "圆柱孔,从一侧表面穿透到另一侧表面,两端可见。",
        "modeling": "刀具长度 >= 壁厚,刀具须穿过基体材料。用 side_hole through=True。"
                    "几何自校验会拦截悬空刀具(未真正穿过基体)。",
        "application": "管道穿越、轴类零件安装、通风孔、连接孔(铆钉/销钉)。"
                       "允许物体或流体完全穿过,常用于需要完全贯通的场合。",
        "distinction": "与通孔的区别:贯穿孔两端开口,完全贯通;通孔底部封闭,不通透。"
                       "贯穿孔需要额外密封措施,通孔底部自然密封。",
    },
    "沉孔": {
        "definition": "上部直径较大的圆柱形凹坑(容纳螺钉头),下部是直径较小的通孔。两段不同直径的同心孔。",
        "geometry": "阶梯孔:大直径浅段 + 小直径深段,同轴。",
        "modeling": "两个同轴刀具:大直径圆柱(浅,盲)+ 小直径圆柱(深,通),分别做两次 subtract。",
    },
    "阶梯孔": {
        "definition": "由两段或更多段不同直径组成的同轴孔。",
        "geometry": "同轴多段圆柱,直径逐段变化。",
        "modeling": "每段用一个圆柱刀具,同轴不同直径/深度,分别 subtract。",
    },
    "相贯": {
        "definition": "两个曲面(如圆柱面与圆柱面、圆柱面与球面)相交,交线称为相贯线。"
                    "相贯孔 = 两个孔在零件内部相交贯通。",
        "geometry": "两个孔轴线相交(垂直/斜交),在内部连通;相交处有相贯线(空间曲线)。",
        "modeling": "两个方向各一个刀具(如 +z 圆柱 与 +x 圆柱),都穿过基体,"
                    "在同一个 subtract 中依次 cut,或分两次 subtract;"
                    "两刀具的轴线必须相交,且都穿过基体材料,才会形成相贯。",
    },
    "盲孔深度": {
        "definition": "盲孔从表面到孔底的距离(不含倒角)。",
        "geometry": "外表面到孔底平面的距离。",
        "modeling": "刀具中心 = 外表面位置 - 深度/2(沿孔轴向);孔底坐标 = 外表面 - 深度。",
    },
    "倒角": {
        "definition": "棱边削成斜面(C角),如 C1=1mm×45°。",
        "geometry": "孔口/棱边的圆锥或平面过渡。",
        "modeling": "当前原语体系暂无直接倒角原语,可用 revolved_solid 或提示用户暂不支持。",
    },
    "圆角": {
        "definition": "棱边修成圆弧过渡(R角)。",
        "geometry": "棱边的圆弧过渡面。",
        "modeling": "当前原语体系暂无直接圆角原语,可用 revolved_solid 或提示用户暂不支持。",
    },
    "螺纹孔": {
        "definition": "内螺纹的孔,用于螺栓连接。",
        "geometry": "孔壁有螺纹牙形。",
        "modeling": "当前原语体系无螺纹建模,建光孔(底孔)并注明螺纹规格即可。",
    },
    "铰孔": {
        "definition": "用铰刀精加工孔,提高尺寸精度和表面质量。",
        "geometry": "高精度圆柱孔。",
        "modeling": "普通圆柱孔,注明铰孔精度要求即可。",
    },
    "轴向": {
        "definition": "沿孔/轴的中心线方向。",
        "geometry": "孔的轴方向(圆柱轴线方向)。",
        "modeling": "cylinder 只能沿 +Z;其他方向(如 +x/+y)的孔用 side_hole 指定 axis_dir。",
    },
    "径向": {
        "definition": "垂直于轴线的方向(半径方向)。",
        "geometry": "孔/轴的垂直截面方向。",
        "modeling": "径向孔(从侧面穿入轴/球)用 side_hole,axis_dir 指向轴/球心。",
    },
    "壁厚": {
        "definition": "壳体零件的内外表面之间的距离。",
        "geometry": "外表面到内表面的最短距离。",
        "modeling": "空心球/壳:壁厚 = 外半径 - 内半径。盲孔深度必须 < 壁厚,否则成为通孔。",
    },
    "正面": {
        "definition": "零件的主视面(通常指 +X 方向或用户指定的基准面)。",
        "geometry": "指代方向的约定:顶部=+Z,正面=+X(或用户明确指定)。",
        "modeling": "正面上的孔 = 沿 +X 方向(或指定方向)开孔,用 side_hole axis_dir='+x'。",
    },
    "垂直": {
        "definition": "与某基准面/轴线成 90°。",
        "geometry": "孔的轴线垂直于所指表面。",
        "modeling": "'正面垂直贯孔' = 孔轴垂直于正面(+X 方向),即沿 +X 开孔。",
    },
}


def _session():
    """获取数据库会话(Anvil 共享 MySQL)。"""
    from anvil.db import SessionLocal
    return SessionLocal()


def ensure_table():
    """确保 mech_terms 表存在,写入种子词条并同步更新已有词条。"""
    from anvil.db import MechTerm
    try:
        db = _session()
        try:
            # 建表(Base.metadata.create_all 由 init_db 做;这里检查表是否存在)
            count = db.query(MechTerm).count()
            if count == 0:
                # 表为空,写入全部种子词条
                for term, fields in SEED_TERMS.items():
                    db.add(MechTerm(
                        term=term,
                        aliases=fields.get("aliases", ""),
                        definition=fields["definition"],
                        geometry=fields["geometry"],
                        modeling=fields["modeling"],
                        application=fields.get("application", ""),
                        distinction=fields.get("distinction", ""),
                        updated_at=datetime.utcnow(),
                    ))
                db.commit()
            else:
                # 表已有数据,同步更新种子词条(确保定义与代码一致)
                for term, fields in SEED_TERMS.items():
                    existing = db.query(MechTerm).filter(MechTerm.term == term).first()
                    if existing:
                        # 更新已有词条
                        existing.aliases = fields.get("aliases", "")
                        existing.definition = fields["definition"]
                        existing.geometry = fields["geometry"]
                        existing.modeling = fields["modeling"]
                        existing.application = fields.get("application", "")
                        existing.distinction = fields.get("distinction", "")
                        existing.updated_at = datetime.utcnow()
                    else:
                        # 新增缺失的种子词条
                        db.add(MechTerm(
                            term=term,
                            aliases=fields.get("aliases", ""),
                            definition=fields["definition"],
                            geometry=fields["geometry"],
                            modeling=fields["modeling"],
                            application=fields.get("application", ""),
                            distinction=fields.get("distinction", ""),
                            updated_at=datetime.utcnow(),
                        ))
                db.commit()
        finally:
            db.close()
    except Exception:
        pass  # 数据库不可用时静默,回退内置词条


def get_all_terms() -> list:
    """从数据库读取全部术语(按 term 排序)。数据库空/不可用时回退内置。"""
    from anvil.db import MechTerm
    try:
        db = _session()
        try:
            rows = db.query(MechTerm).order_by(MechTerm.term).all()
            if rows:
                return [{
                    "id": r.id,
                    "term": r.term,
                    "aliases": getattr(r, 'aliases', '') or "",
                    "definition": r.definition or "",
                    "geometry": r.geometry or "",
                    "modeling": r.modeling or "",
                    "application": getattr(r, 'application', '') or "",
                    "distinction": getattr(r, 'distinction', '') or "",
                } for r in rows]
        finally:
            db.close()
    except Exception:
        pass
    # 回退:内置词条
    return [{"id": 0, "term": k, **v} for k, v in sorted(SEED_TERMS.items())]


def format_term_table() -> str:
    """生成注入 system prompt 的术语速查表(保持精简)。"""
    terms = get_all_terms()
    lines = ["机械设计术语速查(建模时先看这里,不确定再查 lookup_term):"]
    for t in terms:
        aliases = t.get("aliases", "")
        alias_info = " (别名: %s)" % aliases if aliases else ""
        lines.append("- %s%s: %s 建模:%s" % (t["term"], alias_info, (t["definition"] or "")[:60], (t["modeling"] or "")[:60]))
    return "\n".join(lines)


def lookup_term(term: str) -> str:
    """精确或包含匹配术语,返回定义+几何+建模指导。支持别名查询。"""
    term = term.strip()
    terms = get_all_terms()
    
    # 1. 精确匹配主术语
    for t in terms:
        if t["term"] == term:
            return _format_term(t, term)
    
    # 2. 别名匹配:检查 aliases 字段
    for t in terms:
        aliases = t.get("aliases", "")
        if aliases:
            alias_list = [a.strip() for a in aliases.split(",")]
            if term in alias_list:
                return _format_term(t, term)
    
    # 3. 包含匹配:如"盲孔深度"包含"通孔"
    for t in terms:
        if t["term"] in term:
            return _format_term(t, term, is_partial=True)
        # 检查别名是否被包含
        aliases = t.get("aliases", "")
        if aliases:
            for alias in aliases.split(","):
                if alias.strip() in term:
                    return _format_term(t, term, is_partial=True)
    
    return "术语表中未找到'%s'。请按字面理解,或向用户确认其含义。" % term


def _format_term(t: dict, query_term: str, is_partial: bool = False) -> str:
    """格式化术语输出。"""
    prefix = "【%s】" % t["term"]
    if is_partial:
        prefix = "【%s】(术语'%s'包含它)" % (t["term"], query_term)
    elif query_term != t["term"]:
        prefix = "【%s】(别名'%s'→主术语'%s')" % (t["term"], query_term, t["term"])
    
    result = "%s%s\n几何: %s\n建模: %s" % (prefix, t["definition"], t["geometry"], t["modeling"])
    if t.get("application"):
        result += "\n应用: %s" % t["application"]
    if t.get("distinction"):
        result += "\n区别: %s" % t["distinction"]
    return result
