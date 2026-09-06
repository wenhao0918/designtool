"""技术要求自动推荐:按零件类型/特征/尺寸,套用机械设计常用出图规范。

规则来源:机械设计手册出图规范——GB/T 1804(未注尺寸公差)、GB/T 1184(形位公差)、
GB/T 699(优质碳素钢)、GB/T 9439(灰铸铁)等,结合 DraftEngine 特征识别结果
(holes/bosses/shaft_segment)做条件推荐。

输出结构化条目 [{text, reason, standard}]:
- text     渲染进图纸左上角"技术要求"
- reason   推荐依据(前端悬浮/列表展示,让用户知道为什么)
- standard 对应国标号(可追溯)
"""

MAX_ITEMS = 5


def recommend(part_type, main_axis, bbox, features):
    """(part_type, main_axis, bbox, features) → (items, material)

    items: 按优先级排序、截断到 MAX_ITEMS 的技术要求条目
    material: 推荐材料(标题栏 + meta.material_suggestion)
    """
    holes = [f for f in features if f.get("type") == "hole"]
    bosses = [f for f in features if f.get("type") == "boss"]
    L, W, H = bbox["L"], bbox["W"], bbox["H"]
    items = []

    def add(text, reason, standard=""):
        items.append({"text": text, "reason": reason, "standard": standard})

    # 1) 未注公差——所有零件必备
    add("未注尺寸公差按 GB/T 1804-m", "通用线性/角度尺寸未注公差(中等级 m)", "GB/T 1804-2000")

    material = "Q235B"
    if part_type == "shaft":
        # 轴类:调质 + 轴端倒角
        material = "45钢"
        add("调质处理,硬度 220~250HBW", "轴类零件提高综合力学性能与切削性能", "GB/T 699")
        add("轴端未注倒角 C1", "台阶轴装配导向,保护配合面")
    elif bosses:
        # 带凸台:按铸件工艺出图
        material = "HT200"
        add("铸件不得有砂眼、气孔、缩松、裂纹", "带凸台/搭子结构按铸造工艺出图", "GB/T 9439")
        add("未注铸造圆角 R3", "铸造工艺必需,减小尖角应力集中")
        add("铸件时效处理", "消除铸造残余应力,稳定尺寸")
    else:
        # 板类/机加工件
        add("锐边倒钝 C0.5", "机加工锐边去毛刺,安全防护")
        add("未注圆角 R0.5", "未注过渡圆角统一要求")

    # 2) 特征相关
    if any(h.get("subtype") == "counterbore" for h in holes):
        add("沉头孔德平端面,与螺钉头贴合", "沉头孔端面需平整,保证连接可靠")
    elif len(holes) >= 2:
        add("孔口去毛刺", "多孔结构机加工后清理孔口毛刺")

    # 3) 大件补充形位公差
    if max(L, W, H) >= 200:
        add("未注形位公差按 GB/T 1184-K", "外形尺寸≥200mm,补充未注形位公差要求", "GB/T 1184-1996")

    return items[:MAX_ITEMS], material
