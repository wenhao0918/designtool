"""
Anvil integration: material_client — query mn-material standard parts library.

5 tables: part_category / standard_part / nonstandard_part / supplier_info / web_search_cache
Client: reuse SampleClient (RuoYi-Cloud-Plus encrypted login + token auto-refresh)
vendored at repo utils/matNgineClient.py.
"""

import sys
from pathlib import Path

# RuoYi-Cloud-Plus 兼容客户端(已内置仓库根 utils/matNgineClient.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils.matNgineClient import MatNgineClient as SampleClient  # noqa: E402

MATERIAL_URL = "http://127.0.0.1:8080/material"

# 单例客户端：首次调用自动加密登录，401 自动重登
_client = SampleClient(host="127.0.0.1", port=8080)


def _call(endpoint, params):
    ok, data = _client.get(MATERIAL_URL + endpoint, params)
    if ok:
        return data
    return {"status": "error", "message": str(data)[:200]}


def list_categories():
    """零件分类树（part_category，51 条，含规格模板 specSchema）"""
    return _call("/partCategory/list", {"pageSize": 100})


# 分类缓存(避免每次查询都拉分类树)
_cat_cache: dict | None = None


def _load_cats():
    global _cat_cache
    if _cat_cache is None:
        r = list_categories()
        _cat_cache = {c["id"]: c for c in (r.get("rows") or []) if isinstance(r, dict)}
    return _cat_cache


def expand_category_ids(cat_id):
    """递归展开分类:返回 cat_id 及其所有子孙分类 id(含自己)。
    支持传入单个 id 或 id 列表;用于"选父类查所有子类"。
    """
    if cat_id is None:
        return None
    if isinstance(cat_id, (list, tuple, set)):
        out = []
        for c in cat_id:
            out.extend(expand_category_ids(c))
        return sorted(set(out)) or None
    cats = _load_cats()
    ids = [int(cat_id)]
    changed = True
    while changed:
        changed = False
        for cid, c in cats.items():
            if c.get("parentId") in ids and cid not in ids:
                ids.append(cid)
                changed = True
    return sorted(ids)


def _search_with_cats(query_fn, name, category_id, brand=None, page=1, page_size=20, **kw):
    """按分类查询:category_id 是父类时展开为所有子孙,逐个查合并。"""
    ids = expand_category_ids(category_id)
    if not ids or len(ids) == 1:
        return query_fn(name=name, category_id=category_id, brand=brand, page=page, page_size=page_size, **kw)
    # 多分类:逐个查,合并 rows(去重)
    merged_rows, total = [], 0
    for cid in ids:
        r = query_fn(name=name, category_id=cid, brand=brand, page=page, page_size=page_size, **kw)
        if isinstance(r, dict) and r.get("rows"):
            seen = {x.get("id") for x in merged_rows}
            for row in r["rows"]:
                if row.get("id") not in seen:
                    merged_rows.append(row)
            total += r.get("total", 0)
    return {"total": total, "rows": merged_rows, "code": 200, "msg": "查询成功"}


def search_standard_parts(name=None, category_id=None, brand=None, page=1, page_size=20):
    """搜索标准件（standard_part，228 条）：按名称/分类/品牌过滤;父分类自动展开子类"""
    return _search_with_cats(_call_single_standard, name, category_id, brand, page, page_size)


def _call_single_standard(name=None, category_id=None, brand=None, page=1, page_size=20, **kw):
    return _call("/standardPart/list", {
        "pageNum": page, "pageSize": page_size,
        "name": name, "categoryId": category_id, "brand": brand,
    })


def match_standard_parts(name=None, category_id=None, constraints=None, limit=10):
    """按设计约束选用标准件：
    constraints 示例: {"thread": "M6", "length_mm": {"min": 20}, "load_dynamic": {"min": 10}}
      - 标量值 → specs 字段精确相等
      - {"min": x} / {"max": x} / {"min": x, "max": x} → 数值范围
      - 值匹配失败则该约束不命中(不淘汰,用于评分)
    返回: 按命中约束数降序,命中数相同按参考价升序。
    """
    import json as _json
    constraints = constraints or {}
    # 候选:分类 + 名称粗筛,分页拉取(每页 50,最多 4 页 = 200 条;网关 pageSize 上限 ~50)
    rows = []
    for pg in range(1, 5):
        resp = search_standard_parts(name=name, category_id=category_id, page=pg, page_size=50)
        page_rows = resp.get("rows") if isinstance(resp, dict) else None
        if page_rows is None:
            return resp
        rows.extend(page_rows)
        if len(page_rows) < 50:
            break
    if not rows:
        return {"status": "ok", "total": 0, "matches": []}

    def _parse_specs(s):
        if not s:
            return {}
        try:
            return _json.loads(s) if isinstance(s, str) else (s or {})
        except Exception:
            return {}

    def _val_match(spec_val, req):
        """判断 specs 字段值是否满足约束。返回 True/False"""
        if spec_val is None:
            return False
        if isinstance(req, dict) and ("min" in req or "max" in req):
            # 数值范围:双方转数值
            try:
                sv = float(str(spec_val).replace(",", ""))
            except (ValueError, TypeError):
                return False
            if "min" in req and req["min"] is not None and sv < float(req["min"]):
                return False
            if "max" in req and req["max"] is not None and sv > float(req["max"]):
                return False
            return True
        # 精确/包含:字符串比较(忽略大小写),数字转字符串
        sreq = str(req).strip().lower()
        sval = str(spec_val).strip().lower()
        if sreq in sval or sval in sreq:
            return True
        # 数字等价(M6 vs m6)
        return sreq == sval

    scored = []
    for row in rows:
        specs = _parse_specs(row.get("specs"))
        hit = []
        miss = []
        for k, req in constraints.items():
            if k in specs and _val_match(specs[k], req):
                hit.append(k)
            else:
                miss.append(k)
        # 名称/分类兜底:name 关键词命中名称也算加分
        if name:
            nm = (row.get("name") or "").lower()
            if str(name).lower() in nm:
                hit.append("__name__")
        price = row.get("referencePrice")
        try:
            price = float(price) if price is not None else 1e9
        except (ValueError, TypeError):
            price = 1e9
        scored.append({
            "part": row,
            "score": len(hit),
            "hit": hit,
            "miss": miss,
            "price": price,
        })

    scored.sort(key=lambda x: (-x["score"], x["price"]))
    matches = [s for s in scored if s["score"] > 0 or not constraints]
    return {
        "status": "ok",
        "total": len(matches),
        "limit": limit,
        "matches": [
            {
                "part_code": m["part"].get("partCode"),
                "name": m["part"].get("name"),
                "brand": m["part"].get("brand"),
                "model": m["part"].get("model"),
                "specs": m["part"].get("specs"),
                "reference_price": m["part"].get("referencePrice"),
                "unit": m["part"].get("unit"),
                "supplier": m["part"].get("supplier"),
                "material": m["part"].get("material"),
                "score": m["score"],
                "hit": m["hit"],
                "miss": m["miss"],
            }
            for m in matches[:limit]
        ],
    }


# 选型策略优先级:企业自有 > 行业件 > 标准件 > 非标件
# 各层独立表:enterprise_part / industry_part / standard_part / nonstandard_part
STRATEGY_CATEGORIES = {
    "enterprise": [53, 58, 59],   # 企业自有件(企业标准件/自制非标件)
    "industry": [52, 54, 55, 56, 57],  # 行业件(汽车/机器人/食品医药/半导体)
    "standard": None,             # 标准件(standard_part 其余分类)
    "nonstandard": [46, 47, 48, 49, 50, 51],  # 非标定制件
}

# 层 → 查询函数(延迟到文件尾部定义,避免函数定义顺序问题)
_TIER_QUERY = None


def _rows_to_matches(rows, tier, name, constraints, limit):
    """把某层表的 rows 转成统一 match 条目(规格比对评分)。"""
    import json as _json

    def _parse(s):
        if not s:
            return {}
        try:
            return _json.loads(s) if isinstance(s, str) else (s or {})
        except Exception:
            return {}

    def _val_match(sv, req):
        if sv is None:
            return False
        if isinstance(req, dict) and ("min" in req or "max" in req):
            try:
                fv = float(str(sv).replace(",", ""))
            except (ValueError, TypeError):
                return False
            if "min" in req and req["min"] is not None and fv < float(req["min"]):
                return False
            if "max" in req and req["max"] is not None and fv > float(req["max"]):
                return False
            return True
        sreq, sval = str(req).strip().lower(), str(sv).strip().lower()
        return sreq in sval or sval in sreq or sreq == sval

    out = []
    for r in rows or []:
        if not r.get("partCode"):
            continue
        specs = _parse(r.get("specs") or r.get("paramSchema") or r.get("defaultParams"))
        hit, miss = [], []
        for k, req in (constraints or {}).items():
            if k in specs and _val_match(specs[k], req):
                hit.append(k)
            else:
                miss.append(k)
        if name:
            nm = (r.get("name") or "").lower()
            if str(name).lower() in nm:
                hit.append("__name__")
        price = r.get("referencePrice")
        try:
            price = float(price) if price is not None else 1e9
        except (ValueError, TypeError):
            price = 1e9
        out.append({
            "part_code": r.get("partCode"),
            "name": r.get("name"),
            "brand": r.get("brand"),
            "model": r.get("model"),
            "specs": r.get("specs") or r.get("paramSchema") or r.get("defaultParams"),
            "reference_price": r.get("referencePrice"),
            "unit": r.get("unit") or r.get("priceUnit") or "件",
            "supplier": r.get("supplier"),
            "material": r.get("material"),
            "score": len(hit),
            "hit": hit,
            "miss": miss,
            "tier": tier,
        })
    out.sort(key=lambda x: (-x["score"], x.get("reference_price") if isinstance(x.get("reference_price"), (int, float)) else 1e9))
    return out[:limit]


def select_with_strategy(name=None, constraints=None, limit=10, prefer=None):
    """按优先级选型:企业自有 → 行业 → 标准 → 非标。

    各层查独立表(enterprise_part/industry_part/standard_part/nonstandard_part),
    每层内按规格命中评分排序;高优先级层有匹配则选用,不再看低优先级。
    prefer 可指定只看某层("enterprise"/"industry"/"standard"/"nonstandard")。
    返回各层匹配情况,便于前端展示"用了哪一层"。
    """
    order = ["enterprise", "industry", "standard", "nonstandard"]
    if prefer:
        order = [prefer] if prefer in order else order

    layers = []
    for tier in order:
        query_fn = _TIER_QUERY[tier]
        resp = query_fn(name=name, page=1, page_size=50)
        rows = resp.get("rows") if isinstance(resp, dict) else []
        matches = _rows_to_matches(rows, tier, name, constraints, limit)
        layers.append({"tier": tier, "matches": matches})

    # 优选:按优先级取第一个"有可用数据"的层。
    # 有约束时看 score>0(规格命中);无约束时看层里有没有条目(默认主库=standard)
    has_constraints = bool(constraints)
    chosen = None
    for layer in layers:
        if has_constraints:
            good = [m for m in layer["matches"] if m.get("score", 0) > 0]
        else:
            good = layer["matches"]
        if good:
            chosen = layer
            break
    if chosen is None:
        # 都没命中:默认回到标准件层(最通用);standard 空则给空结果
        std = next((l for l in layers if l["tier"] == "standard"), None)
        chosen = std if std else layers[-1]
        chosen = {"tier": chosen["tier"], "matches": chosen["matches"][:limit]}

    return {
        "status": "ok",
        "strategy": "enterprise > industry > standard > nonstandard",
        "chosen_tier": chosen["tier"],
        "layers": layers,
        "matches": chosen["matches"][:limit],
    }


def _call_single_nonstandard(name=None, category_id=None, page=1, page_size=20, **kw):
    return _call("/nonstandardPart/list", {
        "pageNum": page, "pageSize": page_size,
        "name": name, "categoryId": category_id,
    })


def search_nonstandard_parts(name=None, category_id=None, page=1, page_size=20):
    """搜索非标件（nonstandard_part，25 条）：按名称/分类过滤;父分类自动展开"""
    return _search_with_cats(_call_single_nonstandard, name, category_id, page=page, page_size=page_size)


def _call_single_industry(name=None, category_id=None, page=1, page_size=20, **kw):
    return _call("/industryPart/list", {
        "pageNum": page, "pageSize": page_size,
        "name": name, "categoryId": category_id,
    })


def search_industry_parts(name=None, category_id=None, page=1, page_size=20):
    """搜索行业件（industry_part，12 条）：汽车/机器人/食品医药/半导体专用;父分类自动展开"""
    return _search_with_cats(_call_single_industry, name, category_id, page=page, page_size=page_size)


def _call_single_enterprise(name=None, category_id=None, page=1, page_size=20, **kw):
    return _call("/enterprisePart/list", {
        "pageNum": page, "pageSize": page_size,
        "name": name, "categoryId": category_id,
    })


def search_enterprise_parts(name=None, category_id=None, page=1, page_size=20):
    """搜索企业自有件（enterprise_part，7 条）：企标件/自制件;父分类自动展开"""
    return _search_with_cats(_call_single_enterprise, name, category_id, page=page, page_size=page_size)


# 层 → 查询函数(所有函数定义后)
_TIER_QUERY = {
    "enterprise": search_enterprise_parts,
    "industry": search_industry_parts,
    "standard": search_standard_parts,
    "nonstandard": search_nonstandard_parts,
}


def list_suppliers(name=None):
    """供应商列表（supplier_info）"""
    return _call("/supplierInfo/list", {"pageSize": 100, "name": name})


def search_cache(keyword=None):
    """搜索缓存（web_search_cache）"""
    return _call("/searchCache/list", {"pageSize": 20, "keyword": keyword})


# ===== Tool definitions for Anvil agent =====

def _tool_list_categories():
    return {
        "type": "function",
        "function": {
            "name": "material_list_categories",
            "description": "物料库：查询零件分类树（标准件/非标件分类，含规格参数模板）。用于设计选型时浏览有哪些零件类别。",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _tool_search_standard():
    return {
        "type": "function",
        "function": {
            "name": "material_search_standard",
            "description": "物料库：搜索标准件（GB标准件库，228条：紧固件/轴承/导轨/丝杠/联轴器/电机/气缸等）。"
                           "设计选型时按名称/分类/品牌查询规格、材质、参考价。返回含 specs 规格JSON、referencePrice 参考价、supplier。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "零件名称关键词，如'轴承'、'六角头螺栓'、'HGH15'"},
                    "category_id": {"type": "number", "description": "分类ID（可先调 material_list_categories 获取）"},
                    "brand": {"type": "string", "description": "品牌，如 HIWIN/THK/SKF"},
                    "page": {"type": "number", "description": "页码，默认1"},
                    "page_size": {"type": "number", "description": "每页数量，默认20"},
                },
                "required": [],
            },
        },
    }


def _tool_search_nonstandard():
    return {
        "type": "function",
        "function": {
            "name": "material_search_nonstandard",
            "description": "物料库：搜索非标件（25条：护理机器人姿态切换/集污排污/底盘/座椅/钣金件等，可配置参数模板）。"
                           "查自定义件时用。返回含 paramSchema 参数模板、defaultParams 默认参数、materialOptions 可选材质。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "零件名称关键词，如'集污箱'、'铰链'"},
                    "category_id": {"type": "number", "description": "分类ID"},
                    "page": {"type": "number", "description": "页码，默认1"},
                    "page_size": {"type": "number", "description": "每页数量，默认20"},
                },
                "required": [],
            },
        },
    }


def _tool_list_suppliers():
    return {
        "type": "function",
        "function": {
            "name": "material_list_suppliers",
            "description": "物料库：查询供应商列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "供应商名称关键词"},
                },
                "required": [],
            },
        },
    }


ALL_MATERIAL_TOOLS = [
    _tool_list_categories(),
    _tool_search_standard(),
    _tool_search_nonstandard(),
    _tool_list_suppliers(),
]

TOOL_IMPL = {
    "material_list_categories": lambda a: list_categories(),
    "material_search_standard": lambda a: search_standard_parts(
        name=a.get("name"), category_id=a.get("category_id"),
        brand=a.get("brand"), page=a.get("page", 1), page_size=a.get("page_size", 20)),
    "material_search_nonstandard": lambda a: search_nonstandard_parts(
        name=a.get("name"), category_id=a.get("category_id"),
        page=a.get("page", 1), page_size=a.get("page_size", 20)),
    "material_list_suppliers": lambda a: list_suppliers(name=a.get("name")),
}
