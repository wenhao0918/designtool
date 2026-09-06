"""已知结构知识库——DB 保全 + RAG 排序融合检索。

复用现有模式:
- DB 查询: 参照 prompts/mech_terms.py 的 _session() + ORM 查询
- RAG 融合: 参照 rag/ragflow.py 的 lookup_term_hybrid() (DB first → RAG fallback)
- 工具定义: 参照 qledger.py 的 TOOL_Q_APPLY

架构依据: Primordium/已知结构知识库架构_V0.md
"""

import json

# ---------- 工具定义（LLM 可调用）----------

TOOL_STRUCTURE_SEARCH = {
    "type": "function",
    "function": {
        "name": "structure_search",
        "description": "检索已知结构模板，输入设计意图和参数，返回结构骨架 JSON。"
                       "拿到骨架后，基于其中的 components 翻译为 ΔQ（add inst/param/feat/rel），再 q_apply 落账。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "设计意图关键词，如 '储油罐'、'轴承座'、'减速箱'",
                },
                "params": {
                    "type": "object",
                    "description": "已知设计参数，如 {\"volume\": 50, \"pressure\": 0.6, \"contents\": \"柴油\"}",
                    "additionalProperties": True,
                },
            },
            "required": ["query"],
        },
    },
}


# ---------- DB 会话 ----------

def _session():
    """获取数据库会话(Anvil 共享 MySQL)。"""
    from anvil.db import SessionLocal
    return SessionLocal()


def _parse_json(text, default=None):
    """解析 Text 字段存储的 JSON，失败返回 default。"""
    if not text:
        return default if default is not None else []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


# ---------- 核心检索函数 ----------

def search_structure(query, params=None):
    """融合检索：DB 保全组件清单 + RAG 排序/上下文。

    流程:
    1. DB 查 structure_template（name LIKE + aliases 匹配）→ 命中模板
    2. 若命中 → get_structure_detail() 全量召回骨架
    3. RAG 检索标准条文/案例 → 作为上下文附加
    4. 返回结构 JSON

    Args:
        query: 设计意图关键词（如 "储油罐"）
        params: 已知参数 dict（如 {"volume": 50, "pressure": 0.6}）

    Returns:
        结构 JSON dict（含 template/components/params/constraints/assembly/rag_context）
    """
    params = params or {}

    # 1. DB 查模板（name + aliases 匹配）
    from anvil.db import StructureTemplate
    db = _session()
    try:
        # name 精确/LIKE 匹配
        templates = (
            db.query(StructureTemplate)
            .filter(StructureTemplate.status == 0)
            .filter(StructureTemplate.name.like(f"%{query}%"))
            .all()
        )

        # aliases 匹配（Text 存 JSON，应用层解析）
        if not templates:
            all_templates = db.query(StructureTemplate).filter(StructureTemplate.status == 0).all()
            for t in all_templates:
                aliases = _parse_json(t.aliases, [])
                if any(query in alias or alias in query for alias in aliases):
                    templates.append(t)

        if not templates:
            return {"status": "not_found", "message": f"未找到与'{query}'匹配的结构模板"}

        # 取第一个命中（多命中时返回列表供选择）
        if len(templates) == 1:
            result = get_structure_detail(templates[0].id)
        else:
            # 多命中：返回简表供 LLM 选择
            result = {
                "status": "multiple_match",
                "message": f"找到 {len(templates)} 个匹配模板，请选择",
                "templates": [
                    {"id": t.id, "code": t.code, "name": t.name,
                     "category": t.category, "description": (t.description or "")[:100]}
                    for t in templates
                ],
            }
            return result

        # 2. RAG 检索上下文（可选，不阻断）
        rag_context = None
        try:
            from anvil.rag import get_backend
            rag = get_backend()
            rag_query = f"{query} {' '.join(f'{k}:{v}' for k,v in params.items())}"
            rag_result = rag.search(rag_query, top_k=3)
            if isinstance(rag_result, list) and rag_result:
                rag_context = [
                    {"content": r.get("content", "")[:500],
                     "similarity": r.get("similarity", 0),
                     "document": r.get("document_name", "")}
                    for r in rag_result[:2]
                ]
        except Exception:
            pass  # RAG 不可用不阻断 DB 检索

        if rag_context:
            result["rag_context"] = rag_context

        result["status"] = "ok"
        return result

    finally:
        db.close()


def get_structure_detail(template_id):
    """全量召回结构骨架：template + components（递归）+ params + constraints + assembly。

    Args:
        template_id: structure_template.id

    Returns:
        完整结构 JSON dict
    """
    from anvil.db import (
        StructureTemplate, StructureParamDef,
        StructureConstraint, StructureAssemblyRule,
    )

    db = _session()
    try:
        # 模板主信息
        tpl = db.query(StructureTemplate).filter_by(id=template_id).first()
        if not tpl:
            return {"status": "not_found", "message": f"模板 ID {template_id} 不存在"}

        # 组件清单（递归树）
        components = _get_components_recursive(db, template_id, parent_id=None)

        # 参数定义
        param_defs = (
            db.query(StructureParamDef)
            .filter_by(template_id=template_id)
            .order_by(StructureParamDef.sort_order)
            .all()
        )
        params = [
            {
                "key": p.param_key,
                "label": p.param_label or "",
                "type": p.param_type,
                "unit": p.unit or "",
                "required": bool(p.required),
                "default": p.default_value or "",
                "enum": _parse_json(p.enum_values, []) if p.enum_values else [],
                "validation": p.validation_rule or "",
                "formula": p.formula_expr or "",
                "formula_refs": _parse_json(p.formula_refs, []) if p.formula_refs else [],
            }
            for p in param_defs
        ]

        # 约束规则
        constraints = (
            db.query(StructureConstraint)
            .filter_by(template_id=template_id)
            .order_by(StructureConstraint.sort_order)
            .all()
        )
        constraint_list = [
            {
                "layer": c.constraint_layer or "P",
                "target": c.target_component or "",
                "rule_type": c.rule_type or "",
                "description": c.description,
                "clause": c.standard_clause or "",
                "formula": c.formula_expr or "",
                "severity": c.severity or "hard",
            }
            for c in constraints
        ]

        # 装配规则
        assemblies = (
            db.query(StructureAssemblyRule)
            .filter_by(template_id=template_id)
            .order_by(StructureAssemblyRule.sort_order)
            .all()
        )
        assembly_list = [
            {
                "from": a.from_component,
                "to": a.to_component,
                "type": a.connection_type or "",
                "relation": a.relation_expr or "",
                "principle": a.principle_note or "",
                "constraint": a.constraint_note or "",
            }
            for a in assemblies
        ]

        return {
            "template_id": tpl.id,
            "template_code": tpl.code,
            "template_name": tpl.name,
            "category": tpl.category or "",
            "subcategory": tpl.subcategory or "",
            "description": tpl.description or "",
            "standard_ref": tpl.standard_ref or "",
            "applicable_scope": tpl.applicable_scope or "",
            "aliases": _parse_json(tpl.aliases, []),
            "components": components,
            "params": params,
            "constraints": constraint_list,
            "assembly": assembly_list,
        }
    finally:
        db.close()


def _get_components_recursive(db, template_id, parent_id=None):
    """递归获取组件树（支持 sub_structure 嵌套引用）。"""
    from anvil.db import StructureComponent

    comps = (
        db.query(StructureComponent)
        .filter_by(template_id=template_id)
        .filter(StructureComponent.parent_id == parent_id if parent_id else StructureComponent.parent_id.is_(None))
        .order_by(StructureComponent.sort_order)
        .all()
    )

    result = []
    for c in comps:
        item = {
            "id": c.id,
            "name": c.name,
            "type": c.component_type,
            "quantity": c.quantity_expr or "1",
            "required": bool(c.required),
            "sort_order": c.sort_order,
            "principle": c.principle_note or "",
        }
        if c.component_type == "sub_structure" and c.ref_template_id:
            item["ref_template_id"] = c.ref_template_id
            # 不递归展开子模板（避免深度爆炸），仅标注引用
            item["note"] = "子结构，需单独调用 get_structure_detail 展开"
        elif c.component_type == "standard_part" and c.ref_part_category:
            item["ref_part_category"] = c.ref_part_category
        elif c.component_type == "geometry":
            item["geometry_hint"] = "直接映射 Q 的 inst 条目"

        # 递归子组件
        children = _get_components_recursive(db, template_id, parent_id=c.id)
        if children:
            item["children"] = children

        result.append(item)
    return result


# ---------- Agent 工具处理 ----------

def handle_structure_search(arguments):
    """Agent 工具处理函数：接收 LLM 的 structure_search 调用参数，返回 JSON 字符串。

    供 DesignAgent.handle_tool 调用。
    """
    query = arguments.get("query", "")
    params = arguments.get("params")

    if not query:
        return json.dumps({"status": "error", "message": "缺少 query 参数"}, ensure_ascii=False)

    result = search_structure(query, params)
    return json.dumps(result, ensure_ascii=False)
