"""国标分类目录 — GbstdService 的路由账本。

分类(category)的标准形式(2026-08-27 定稿):
  {name, label, keywords, service, dataset_id, status}
  · dataset_id  — 知识本体指针(当前=RAGFlow dataset)
  · service     — 服务方法类型(当前统一 "ragflow"=向量检索;
                  未来可扩 "table"参数化查表 等,服务方法签名不变:
                  query(q, top_k) → hits)
分类之间零个性化行为:智能在库里,外壳只做 命名/路由/生命周期。

目录持久化在 data/catalog.json;新增分类两条路:
  ① POST /api/gbstd/categories(auto_create=true 自动建库并登记)
  ② 直接编辑 catalog.json 后重启(字段同 SEED)

分类状态:
  active   已绑定 dataset,可检索可路由
  planned  占位(尚无内容库),不可路由(建库后自动转 active)
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("GBSTD_DATA_DIR", os.path.join(HERE, "data"))
CATALOG_PATH = os.path.join(DATA_DIR, "catalog.json")

# 现有 RAGFlow「工程图纸国标」库(42 册制图/标注/公差类国标)归入 draw 分类
# service 字段显式声明服务方法类型;所有分类统一方法签名 query(q, top_k)→hits
SEED = {
    "draw": {
        "label": "制图与标注",
        "keywords": ["制图", "图纸", "视图", "投影", "剖视", "断面", "尺寸标注",
                     "标注", "公差", "配合", "粗糙度", "焊缝", "符号", "图幅",
                     "比例", "标题栏", "明细栏", "螺纹", "齿轮", "花键", "弹簧",
                     "中心孔", "倒角", "圆角"],
        "service": "ragflow",
        "dataset_id": "64cc97e4a0ef11f19e5b7eb885516d10",
        "status": "active",
    },
    "fasteners": {
        "label": "紧固件",
        "keywords": ["螺栓", "螺钉", "螺母", "垫圈", "销轴", "铆钉", "紧固",
                     "挡圈", "键联接"],
        "service": "ragflow",
        "dataset_id": "",
        "status": "planned",
    },
    "materials": {
        "label": "材料与牌号",
        "keywords": ["材料", "钢材", "铝合金", "牌号", "力学性能", "热处理",
                     "不锈钢", "铸铁"],
        "service": "ragflow",
        "dataset_id": "",
        "status": "planned",
    },
    "safety": {
        "label": "安全与防护",
        "keywords": ["安全", "防护", "警告", "危险", "接地"],
        "service": "ragflow",
        "dataset_id": "",
        "status": "planned",
    },
}

# 服务方法注册表:service 类型 → 检索实现。
# 统一签名:fn(query, dataset_ids, top_k) → hits;新增方法类型在此登记。
SERVICES = {
    "ragflow": None,  # api.py 启动时绑定 ragflow_client.retrieve
}


def load_catalog():
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, encoding="utf-8") as f:
                c = json.load(f)
            # 迁移:旧条目缺 service 字段 → 补默认 ragflow(统一服务方法)
            dirty = False
            for v in c.values():
                if "service" not in v:
                    v["service"] = "ragflow"
                    dirty = True
            if dirty:
                save_catalog(c)
            return c
        except Exception:
            pass
    return json.loads(json.dumps(SEED))


def save_catalog(catalog):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CATALOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CATALOG_PATH)


def upsert(catalog, name, label, keywords, dataset_id="", status=None,
           service="ragflow"):
    """新增/更新分类。绑定了 dataset 的分类自动视为 active。

    service 声明该分类的服务方法类型(见 SERVICES);默认 ragflow。
    """
    entry = catalog.get(name) or {}
    if dataset_id:
        entry["dataset_id"] = dataset_id
    entry["label"] = label or entry.get("label", name)
    entry["keywords"] = keywords or entry.get("keywords", [])
    entry["service"] = service or entry.get("service", "ragflow")
    if status:
        entry["status"] = status
    if entry.get("dataset_id"):
        entry["status"] = "active"
    elif not entry.get("status"):
        entry["status"] = "planned"
    catalog[name] = entry
    return entry


def routable(catalog):
    """可路由分类:active 且绑定了 dataset。"""
    return {k: v for k, v in catalog.items()
            if v.get("dataset_id") and v.get("status") == "active"}
