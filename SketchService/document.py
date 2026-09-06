"""SketchDocument — 草图的权威数据结构（Python 端）。

与前端 types/sketch.ts 保持一致，SketchService 用它来验证、解析、存储草图数据。
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ===== 枚举 =====

class SketchScene(str, Enum):
    MECHANICAL = "mechanical"
    ARCHITECTURAL = "architectural"
    ART = "art"
    ANIMATION = "animation"


# ===== 核心类型 =====

@dataclass
class Point:
    x: float
    y: float

@dataclass
class Pressure:
    pressure: float = 0.5

@dataclass
class StrokeData:
    color: str
    width: float
    points: list[dict] = field(default_factory=list)  # [{"x":, "y":}, ...]

@dataclass
class SketchLayer:
    id: int
    name: str
    visible: bool = True
    locked: bool = False
    strokes: list[StrokeData] = field(default_factory=list)

@dataclass
class SketchShape:
    type: str           # cube, cylinder, circle, gear, ...
    x: float
    y: float
    size: Optional[float] = None
    angle: Optional[float] = None

@dataclass
class SketchGesture:
    gesture: str  # confirm, reject, select, point, erase, emphasize, rotate, move
    x: float
    y: float
    note: str = ""

@dataclass
class SketchMeta:
    scene: SketchScene = SketchScene.MECHANICAL
    title: Optional[str] = None
    author: Optional[str] = None
    createdAt: int = 0
    modifiedAt: int = 0

@dataclass
class SketchDocument:
    meta: SketchMeta = field(default_factory=SketchMeta)
    layers: list[SketchLayer] = field(default_factory=list)
    shapes: list[SketchShape] = field(default_factory=list)
    gestures: list[SketchGesture] = field(default_factory=list)
    activeLayerId: int = 0

    def total_strokes(self) -> int:
        return sum(len(l.strokes) for l in self.layers)

    def visible_strokes(self) -> int:
        return sum(len(l.strokes) for l in self.layers if l.visible)


# ===== 场景配置 =====

@dataclass
class SceneConfig:
    id: SketchScene
    label: str
    icon: str
    description: str
    default_layers: list[dict]   # [{"name":, "locked":?}, ...]
    use_case: str


SCENES: dict[SketchScene, SceneConfig] = {
    SketchScene.MECHANICAL: SceneConfig(
        id=SketchScene.MECHANICAL,
        label="机械设计",
        icon="⚙️",
        description="零件结构、装配关系、运动示意",
        default_layers=[
            {"name": "结构轮廓"},
            {"name": "标注尺寸"},
            {"name": "运动示意"},
            {"name": "批注"},
        ],
        useCase="机械结构概念设计：零件外形、装配方式、传动路线、受力分析草图",
    ),
    SketchScene.ARCHITECTURAL: SceneConfig(
        id=SketchScene.ARCHITECTURAL,
        label="建筑设计",
        icon="🏛️",
        description="平面布局、空间关系、立面示意",
        default_layers=[
            {"name": "墙体轴线"},
            {"name": "空间分区"},
            {"name": "标注"},
            {"name": "家具布置"},
        ],
        useCase="建筑空间概念设计：功能分区、流线规划、立面草图",
    ),
    SketchScene.ART: SceneConfig(
        id=SketchScene.ART,
        label="绘画",
        icon="🎨",
        description="线稿、着色、光影层次",
        default_layers=[
            {"name": "线稿", "locked": True},
            {"name": "底色"},
            {"name": "阴影"},
            {"name": "高光"},
        ],
        useCase="绘画创作：线稿描边、分层上色、光影叠加",
    ),
    SketchScene.ANIMATION: SceneConfig(
        id=SketchScene.ANIMATION,
        label="动漫",
        icon="🎬",
        description="分镜草图、角色设计、场景构图",
        default_layers=[
            {"name": "背景"},
            {"name": "角色"},
            {"name": "特效"},
            {"name": "注释"},
        ],
        useCase="动画/漫画分镜：角色造型、场景设定、动作序列草图",
    ),
}


def create_document(scene: SketchScene = SketchScene.MECHANICAL) -> SketchDocument:
    """创建空白 SketchDocument。"""
    import time
    config = SCENES[scene]
    now = int(time.time() * 1000)
    doc = SketchDocument(
        meta=SketchMeta(scene=scene, createdAt=now, modifiedAt=now),
        layers=[
            SketchLayer(
                id=i,
                name=l["name"],
                locked=l.get("locked", False),
            )
            for i, l in enumerate(config.default_layers)
        ],
        activeLayerId=0,
    )
    return doc


def doc_to_dict(doc: SketchDocument) -> dict:
    """序列化为 dict（用于 API 响应 / 缓存）。"""
    return {
        "meta": {
            "scene": doc.meta.scene.value,
            "title": doc.meta.title,
            "author": doc.meta.author,
            "createdAt": doc.meta.createdAt,
            "modifiedAt": doc.meta.modifiedAt,
        },
        "layers": [
            {
                "id": l.id,
                "name": l.name,
                "visible": l.visible,
                "locked": l.locked,
                "strokes": [
                    {"color": s.color, "width": s.width, "points": s.points}
                    for s in l.strokes
                ],
            }
            for l in doc.layers
        ],
        "shapes": [
            {"type": s.type, "x": s.x, "y": s.y, "size": s.size, "angle": s.angle}
            for s in doc.shapes
        ],
        "gestures": [
            {"gesture": g.gesture, "x": g.x, "y": g.y, "note": g.note}
            for g in doc.gestures
        ],
        "activeLayerId": doc.activeLayerId,
    }


def dict_to_doc(data: dict) -> SketchDocument:
    """从 dict 反序列化。"""
    doc = SketchDocument()
    doc.meta = SketchMeta(
        scene=SketchScene(data.get("meta", {}).get("scene", "mechanical")),
        createdAt=data.get("meta", {}).get("createdAt", 0),
        modifiedAt=data.get("meta", {}).get("modifiedAt", 0),
    )
    doc.layers = [
        SketchLayer(
            id=l["id"],
            name=l["name"],
            visible=l.get("visible", True),
            locked=l.get("locked", False),
            strokes=[
                StrokeData(color=s["color"], width=s["width"], points=s.get("points", []))
                for s in l.get("strokes", [])
            ],
        )
        for l in data.get("layers", [])
    ]
    doc.shapes = [
        SketchShape(
            type=s["type"], x=s["x"], y=s["y"],
            size=s.get("size"), angle=s.get("angle"),
        )
        for s in data.get("shapes", [])
    ]
    doc.gestures = [
        SketchGesture(gesture=g["gesture"], x=g["x"], y=g["y"], note=g.get("note", ""))
        for g in data.get("gestures", [])
    ]
    doc.activeLayerId = data.get("activeLayerId", 0)
    return doc


def build_scene_description(doc: SketchDocument) -> str:
    """生成场景描述文本（发给 vision 模型的上下文）。"""
    parts = ["这是一张手绘概念设计草图。"]

    shapes_3d = [s for s in doc.shapes if _category(s.type) == "3d"]
    shapes_2d = [s for s in doc.shapes if _category(s.type) == "2d"]
    shapes_mech = [s for s in doc.shapes if _category(s.type) == "mechanical"]

    if shapes_3d:
        parts.append(f"\n画布上有 {len(shapes_3d)} 个立体几何图形：{', '.join(s.type for s in shapes_3d)}")
    if shapes_2d:
        parts.append(f"有 {len(shapes_2d)} 个平面图形：{', '.join(s.type for s in shapes_2d)}")
    if shapes_mech:
        parts.append(f"有 {len(shapes_mech)} 个机械组件：{', '.join(s.type for s in shapes_mech)}")

    total = sum(len(l.strokes) for l in doc.layers)
    if total:
        parts.append(f"\n手绘了 {total} 笔自由线条，分布在 {len(doc.layers)} 个图层中。")

    parts.append("\n请结合图片和以上描述，理解用户的整体设计意图和结构构想。")
    return "\n".join(parts)


def _category(shape_type: str) -> str:
    """判断形状类别。"""
    _3d = {"cube", "cuboid", "sphere", "cylinder", "cone", "pyramid"}
    _2d = {"circle", "square", "triangle", "diamond", "pentagon", "hexagon", "line", "arrow"}
    _mech = {"gear", "hinge", "actuator", "motor", "bearing", "screw", "slider", "wheel"}
    if shape_type in _3d: return "3d"
    if shape_type in _2d: return "2d"
    if shape_type in _mech: return "mechanical"
    return "2d"
