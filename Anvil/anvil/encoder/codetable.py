"""译码系统 · 译码表（编号 ↔ DSL词汇 ↔ 底层实现 三层对齐）

设计依据：《Anvil_Translator_Spec_V1.md》《OCCT_Codetable_V1.md》
         PrimitiveService/grammar.py（设计语言文法 V0，单一事实源）

三层结构：
  编号（码） → DSL 词汇（grammar.py 冻结词汇表） → 底层实现（8103/OCCT 背后）

收编标准（2026-09-03 用户定）：
- 有直接参数化生成 API 的基本体 → 收编进 1~99，一步译出
- 需布尔组合逻辑的组合体 → 不收编，LLM 用基本码组合表达
  （例：空心球 = 球(d) − 球(d−2t)，表里没有"空心球"词条）

编号段是分配空间（半开），不是 OCCT 类目录镜像：
- 每段预留扩展位，新基本体/算子按需依序分配，永不复用
- 扩展落地路径走 PrimitiveService 自进化（缺口→新原语→注册→译码表同号新增）

别名/同义词不进本表——知音/mech_terms 层归一（主词唯一，防主表爆炸）。
对象指称 = 指令序号 #N（运行时自动递增，永不复用），引用算子 990。
"""
# 段位划分（分配空间，段内按需扩展）
SEGMENTS = {
    (1, 99): "基础几何（体元）",
    (100, 199): "布尔算子",
    (200, 299): "修饰算子",
    (300, 399): "变换算子",
    (400, 499): "坐标系",
    (500, 599): "材质",
    (600, 699): "约束",
    (700, 749): "IO",
    (750, 799): "空间关系/装配定位",
    (800, 899): "复合与标准件",
    (900, 989): "预留",
    (990, 999): "引用与控制算子",
}

# 译码表：编号 → {term, dsl, impl, params, example}
#   term  主词（知音归一后的标准词，唯一）
#   dsl   8103 grammar.py 词汇（None=待扩入，走自进化机制）
#   impl  底层实现入口（8103 背后执行，注释性质；LLM 不可见）
#   params 参数名列表（紧跟编号后进数字串）
CODETABLE = {
    # ===== 1~99 基础几何（体元） =====
    # OCCT 原生六体（BRepPrimAPI）+ FreeCAD 扩展两体；正方体=长宽高相等，不单占编号
    1: {"term": "长方体", "dsl": "box", "impl": "BRepPrimAPI_MakeBox",
        "params": ["长", "宽", "高"], "example": "长100宽50高30的长方体（长宽高相等即正方体）"},
    2: {"term": "圆柱", "dsl": "cylinder", "impl": "BRepPrimAPI_MakeCylinder",
        "params": ["半径", "高度"], "example": "半径20高100的圆柱"},
    3: {"term": "圆锥", "dsl": None, "impl": "BRepPrimAPI_MakeCone",
        "params": ["底半径", "顶半径", "高度"], "example": "底30顶0高50的圆锥（顶半径>0即圆台）"},
    4: {"term": "球", "dsl": "sphere", "impl": "BRepPrimAPI_MakeSphere",
        "params": ["半径"], "example": "半径50的球"},
    5: {"term": "圆环", "dsl": None, "impl": "BRepPrimAPI_MakeTorus",
        "params": ["主半径", "截面半径"], "example": "主半径50截面半径10的圆环"},
    6: {"term": "楔形", "dsl": None, "impl": "BRepPrimAPI_MakeWedge",
        "params": ["dx", "dy", "dz", "ltx"], "example": "楔形块"},
    7: {"term": "椭球", "dsl": None, "impl": "FreeCAD Part Ellipsoid",
        "params": ["a", "b", "c"], "example": "三半轴50/40/30的椭球"},
    8: {"term": "棱柱", "dsl": None, "impl": "FreeCAD Part Prism",
        "params": ["边数", "外接半径", "高度"], "example": "六棱柱"},

    # ===== 100~199 布尔算子 =====
    # grammar V0 无独立布尔词汇（shell 内隐含减）；组合几何体全靠这段表达
    100: {"term": "并", "dsl": None, "impl": "BRepAlgoAPI_Fuse", "params": [], "example": "合并两体"},
    101: {"term": "减", "dsl": None, "impl": "BRepAlgoAPI_Cut",
          "params": [], "example": "空心球=大球减小球；正方体挖圆柱洞"},
    102: {"term": "交", "dsl": None, "impl": "BRepAlgoAPI_Common", "params": [], "example": "取相交部分"},
    103: {"term": "分割", "dsl": None, "impl": "BRepAlgoAPI_Splitter", "params": [], "example": "分割实体"},

    # ===== 200~299 修饰算子 =====
    200: {"term": "倒圆角", "dsl": None, "impl": "BRepFilletAPI_MakeFillet",
          "params": ["边", "半径"], "example": "倒R5圆角"},
    201: {"term": "倒角", "dsl": None, "impl": "BRepFilletAPI_MakeChamfer",
          "params": ["边", "距离"], "example": "倒C2角"},
    202: {"term": "抽壳", "dsl": "shell", "impl": "体∖体.offset(−t)（通用掏壳，闭式定义）",
          "params": ["壁厚"], "example": "壁厚10的空心（通用算子；空心球也可用两球相减表达）"},
    203: {"term": "拔模", "dsl": None, "impl": "BRepOffsetAPI_DraftAngle",
          "params": ["面", "角度"], "example": "拔模3度"},
    204: {"term": "线性阵列", "dsl": None, "impl": "BRepBuilderAPI_Transform(复制)",
          "params": ["方向", "数量", "间距"], "example": "5个均布"},
    205: {"term": "旋转阵列", "dsl": None, "impl": "BRepBuilderAPI_Transform(旋转复制)",
          "params": ["轴", "数量", "角度"], "example": "6个圆周均布"},
    206: {"term": "镜像复制", "dsl": None, "impl": "gp_Trsf(镜像)+BRepBuilderAPI_Transform",
          "params": ["镜像面"], "example": "镜像一份"},
    207: {"term": "打孔", "dsl": None, "impl": "BRepFeat_MakeCylindricalHole",
          "params": ["目标对象", "半径", "[深度]"], "example": "省略深度=贯穿通孔（通孔/盲孔语义见 mech_terms）"},
    208: {"term": "开槽", "dsl": None, "impl": "BRepFeat_MakeDPrism",
          "params": ["轮廓", "长度"], "example": "开键槽"},

    # ===== 300~399 变换算子 =====
    300: {"term": "平移", "dsl": None, "impl": "gp_Trsf+BRepBuilderAPI_Transform",
          "params": ["dx", "dy", "dz"], "example": "平移到位置"},
    301: {"term": "旋转", "dsl": None, "impl": "gp_Trsf+BRepBuilderAPI_Transform",
          "params": ["轴", "角度"], "example": "绕Z转45度"},
    302: {"term": "缩放", "dsl": None, "impl": "gp_GTrsf+BRepBuilderAPI_Transform",
          "params": ["比例"], "example": "放大2倍"},
    303: {"term": "对称", "dsl": None, "impl": "gp_Trsf(镜像)+BRepBuilderAPI_Transform",
          "params": ["镜像面"], "example": "关于XY面对称"},

    # ===== 400~499 坐标系 =====
    400: {"term": "建坐标系", "dsl": None, "impl": "gp_Ax2/gp_Ax3",
          "params": ["原点", "方向"], "example": "建局部坐标系"},
    401: {"term": "X轴偏移", "dsl": None, "impl": "gp_Trsf(平移)",
          "params": ["距离"], "example": "沿X偏移50"},
    402: {"term": "Y轴偏移", "dsl": None, "impl": "gp_Trsf(平移)",
          "params": ["距离"], "example": "沿Y偏移50"},
    403: {"term": "Z轴偏移", "dsl": None, "impl": "gp_Trsf(平移)",
          "params": ["距离"], "example": "沿Z偏移50"},
    404: {"term": "旋转坐标系", "dsl": None, "impl": "gp_Trsf(旋转)",
          "params": ["轴", "角度"], "example": "坐标系绕轴旋转"},

    # ===== 500~599 材质 =====
    500: {"term": "钢", "dsl": None, "impl": "材质属性", "params": [], "example": "钢材质"},
    501: {"term": "铝", "dsl": None, "impl": "材质属性", "params": [], "example": "铝材质"},
    502: {"term": "铜", "dsl": None, "impl": "材质属性", "params": [], "example": "铜材质"},
    503: {"term": "塑料", "dsl": None, "impl": "材质属性", "params": [], "example": "塑料材质"},

    # ===== 600~699 约束 =====
    600: {"term": "固定", "dsl": None, "impl": "约束", "params": [], "example": "固定不动"},
    601: {"term": "同轴", "dsl": "coaxial_z", "impl": "约束",
          "params": [], "example": "同轴对齐（Z向）"},
    602: {"term": "平行", "dsl": None, "impl": "约束", "params": [], "example": "两面平行"},
    603: {"term": "相切", "dsl": None, "impl": "约束", "params": [], "example": "相切接触"},
    604: {"term": "垂直", "dsl": None, "impl": "约束", "params": [], "example": "两面垂直"},

    # ===== 700~749 IO =====
    700: {"term": "导出STEP", "dsl": None, "impl": "STEPControl_Writer",
          "params": ["文件名"], "example": "导出step文件"},
    701: {"term": "导出IGES", "dsl": None, "impl": "IGESControl_Writer",
          "params": ["文件名"], "example": "导出iges文件"},
    702: {"term": "导出STL", "dsl": None, "impl": "StlAPI_Writer",
          "params": ["文件名"], "example": "导出stl文件"},
    703: {"term": "导出OBJ", "dsl": None, "impl": "OBJ导出",
          "params": ["文件名"], "example": "导出obj文件"},
    704: {"term": "导入STEP", "dsl": None, "impl": "STEPControl_Reader",
          "params": ["文件名"], "example": "导入step文件"},

    # ===== 750~799 空间关系/装配定位 =====
    # 对齐 grammar V0 RELATIONS：rests_on_centered / coaxial_z / gap_z
    # 几何体三属性框架（2026-09-03 用户定）：位置/尺寸/方位
    #   尺寸=体元参数；位置=756(绝对)+750~755(相对,内核计算)；方位=757(缺省+Z)
    #   缺省约定：位置=原点(0,0,0)、方位=+Z，均无需补参数
    #   位置锚点统一=体中心（球心/板中心/圆柱轴向中点；旋转不变，2026-09-03 用户定）
    750: {"term": "下方贴合定位", "dsl": "rests_on_centered(反向)", "impl": "装配定位",
          "params": ["引用对象"], "example": "放在它正下方贴合（=引用对象 rests_on 当前体）"},
    751: {"term": "上方定位", "dsl": "rests_on_centered", "impl": "装配定位",
          "params": ["引用对象"], "example": "放在它正上方"},
    752: {"term": "XY中心对齐", "dsl": None, "impl": "装配定位",
          "params": ["引用对象"], "example": "中心对齐（rests_on_centered 内含 xy 对中，单独对中待扩）"},
    753: {"term": "面贴合", "dsl": None, "impl": "装配定位",
          "params": ["面1", "面2"], "example": "两面贴合"},
    754: {"term": "轴对齐", "dsl": "coaxial_z", "impl": "装配定位",
          "params": ["轴1", "轴2"], "example": "同轴对齐"},
    755: {"term": "距离偏移", "dsl": "gap_z", "impl": "装配定位",
          "params": ["引用对象", "方向", "距离"], "example": "间距50"},
    756: {"term": "定位于", "dsl": None, "impl": "gp_Trsf(平移至体中心)/设锚点坐标",
          "params": ["x", "y", "z"], "example": "体中心坐标（球心/板中心/圆柱轴向中点）；缺省=原点(0,0,0)"},
    757: {"term": "朝向", "dsl": None, "impl": "gp_Ax2(方向)/设方位",
          "params": ["倾角(度)", "转角(度)"], "example": "单位=度。倾角：0=竖(+Z) 90=横 180=倒扣(-Z)；转角：绕Z方位（横+X=90,0 横+Y=90,90）。缺省=0,0（竖放）"},
    759: {"term": "贴边放置", "dsl": None, "impl": "Primordium 求解(2026-09-07):配合体元位置位 -1 使用——内核由拓扑心象推实体心,LLM 不算坐标",
          "params": ["目标引用", "侧码(1=X+ 2=X- 3=Y+ 4=Y-)", "间隙"], "example": "759,990,1,1,10 = 放在 #1 的 X+ 侧、表面间隙10mm"},

    # ===== 990~999 引用与控制算子 =====
    990: {"term": "引用对象", "dsl": None, "impl": "元算子",
          "params": ["序号"], "example": "引用#1对象"},
    991: {"term": "当前对象", "dsl": None, "impl": "元算子",
          "params": [], "example": "本指令最新创建的体"},
    992: {"term": "上一对象", "dsl": None, "impl": "元算子",
          "params": [], "example": "本指令次新创建的体（空心球=外球992−内球991）"},
    993: {"term": "条件分支", "dsl": None, "impl": "元算子",
          "params": ["条件", "真分支", "假分支"], "example": "预留"},
    994: {"term": "循环", "dsl": None, "impl": "元算子",
          "params": ["次数", "体"], "example": "预留"},
    9998: {"term": "重置", "dsl": None, "impl": "元算子·控制",
           "params": [], "example": "重新设计/从头开始/清空之前所有设计"},
    9999: {"term": "无法映射", "dsl": None, "impl": "元算子·报警",
           "params": [], "example": "无法映射的词输出9999"},
}

# 主词→编号 反查索引（LLM 拿到知音归一化后的主词，反查编号）
TERM_INDEX = {v["term"]: k for k, v in CODETABLE.items()}


# ===== 几何体参数表 v2（单一来源，2026-09-06 用户定）=====
# 每个几何体固定全参数 = 尺寸 + 位置(体心/圆心 x,y,z 绝对坐标) + 方位(倾角,转角)。
# 矩阵中紧跟编号后的参数顺序 = params 列表顺序,全部写满(缺省 0 占位)——
# 彻底定长,消除"参数值被误判为译码项"的歧义。球旋转不变,无方位位。
# LLM 译码时经 MCP 工具 get_geometry_schema 查询本表(prompt 不内嵌体元细节)。
GEOMETRY_SCHEMA = {
    1: {"term": "长方体", "size": ["长", "宽", "高"]},
    2: {"term": "圆柱", "size": ["半径", "高度"]},
    3: {"term": "圆锥", "size": ["底半径", "顶半径", "高度"]},
    4: {"term": "球", "size": ["半径"], "no_orient": True},
    5: {"term": "圆环", "size": ["主半径", "截面半径"]},
    7: {"term": "椭球", "size": ["半轴a", "半轴b", "半轴c"]},
    8: {"term": "棱柱", "size": ["边数", "外接半径", "高度"]},
}


def geo_params(code):
    """体元 → 全参数名列表(尺寸+位置+方位)。未知体元返回 None。"""
    g = GEOMETRY_SCHEMA.get(int(code))
    if not g:
        return None
    ps = list(g["size"]) + ["中心x", "中心y", "中心z"]
    if not g.get("no_orient"):
        ps += ["倾角", "转角"]
    return ps


def geo_arity(code):
    """体元 → 全参数个数(定长解析用)。"""
    ps = geo_params(code)
    return len(ps) if ps else 0


def get_geometry_schema(name):
    """MCP 工具执行体：几何体名/编号 → 固定参数表。"""
    code = TERM_INDEX.get((name or "").strip())
    if code is None and str(name).strip().isdigit():
        code = int(name.strip())
    g = GEOMETRY_SCHEMA.get(code)
    if not g:
        return {"error": "未知几何体：%s（可用：%s）"
                % (name, "、".join(v["term"] for v in GEOMETRY_SCHEMA.values()))}
    return {
        "term": g["term"], "code": code, "params": geo_params(code),
        "note": "矩阵写法=编号后按 params 顺序写满全部参数(缺省值写 0 占位);"
                "位置=体中心绝对坐标mm(板中心/球心/圆柱轴向中点);"
                "方位=度,倾角0=竖(+Z) 90=横,转角=绕Z;两参数必须写满",
    }


GEOMETRY_SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": "get_geometry_schema",
        "description": "查询几何体的固定参数表(尺寸+位置+方位)。译码涉及几何体时必须先调本工具,"
                      "按返回的 params 顺序在矩阵中跟在编号后写满全部参数(缺省写0)。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "几何体名:长方体/圆柱/圆锥/球/圆环/椭球/棱柱"},
            },
            "required": ["name"],
        },
    },
}


def get(code):
    """编号 → 条目（不存在返回 None）"""
    return CODETABLE.get(int(code))


def lookup_term(term):
    """主词 → 编号（不命中返回 None）"""
    return TERM_INDEX.get(term)


def is_operator(code):
    """是否为算子（布尔/修饰/变换/空间关系/引用，无几何体创建）"""
    c = int(code)
    return (100 <= c <= 199) or (200 <= c <= 299) or (300 <= c <= 399) or (750 <= c <= 799) or (990 <= c <= 999)


def is_reference(code):
    """是否为引用算子（990~999）"""
    return 990 <= int(code) <= 999


def segment_of(code):
    """编号 → 所属段位名"""
    c = int(code)
    for (lo, hi), name in SEGMENTS.items():
        if lo <= c <= hi:
            return name
    return "未知段"


def valid(code):
    """编号是否在表内（1~999 且已分配）"""
    return int(code) in CODETABLE


def direct_hits(text):
    """三级fallback·第1级：文本中直接命中的主词"""
    return [v["term"] for v in CODETABLE.values() if v["term"] in text]


def dsl_anchored():
    """已锚定 DSL 词汇的条目（对齐 8103 grammar.py 快照）"""
    return {k: v["dsl"] for k, v in CODETABLE.items() if v.get("dsl")}


# 译码表文本（供 LLM prompt 注入，让 LLM 知道编号→主词映射）
# 坐标系段(400~499)为内核内部机制(gp_Ax2)，不暴露给译码员——位置/方位唯一入口=756/757+750~755，
# 避免双码歧义（实测 LLM 会误用 400 当定位，导致扫描错乱）
INTERNAL_SEGMENTS = {(400, 499)}


def prompt_text():
    """生成译码表文本，供 LLM 译码员 prompt 使用。

    v2：体元只列名(参数表经 get_geometry_schema 工具查询——prompt 不内嵌,
    扩体元只改工具);算子部分保持详细(含参数名)。
    """
    lines = ["译码表（编号→主词；体元参数=尺寸+体心(x,y,z)+方位(倾角,转角),调工具 get_geometry_schema 查询）："]
    cur_seg = None
    for code in sorted(CODETABLE.keys()):
        seg = segment_of(code)
        if seg != cur_seg:
            if (lo_hi := next(((lo, hi) for (lo, hi) in SEGMENTS if SEGMENTS[(lo, hi)] == seg), None)) and lo_hi in INTERNAL_SEGMENTS:
                continue
            lines.append("# %s" % seg)
            cur_seg = seg
        if any(lo <= code <= hi for (lo, hi) in INTERNAL_SEGMENTS):
            continue
        e = CODETABLE[code]
        if 1 <= code <= 99:  # 体元:参数表在工具
            lines.append("%d=%s [参数表→工具查询]" % (code, e["term"]))
            continue
        params = ",".join(e["params"]) if e["params"] else "无"
        lines.append("%d=%s [%s]" % (code, e["term"], params))
    return "\n".join(lines)


if __name__ == "__main__":
    print(prompt_text())
    print("---")
    print("lookup 球 =", lookup_term("球"), get(4))
    print("is_operator 101 =", is_operator(101), "is_reference 990 =", is_reference(990))
    print("dsl_anchored =", dsl_anchored())
