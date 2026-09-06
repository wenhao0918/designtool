"""约束校验引擎 — Primordium 理论的约束层(服务端强制)。

从 Anvil system prompt 下沉的机械设计约束规则(2026-08-26 起,
规则跟着原语走,不跟 Agent 走——任何 LLM 用原语都自动获得校验)。

规则分级(对齐 Primordium 层级约束框架):
  hard   硬律:违反则几何/物理不成立(孔深>壁厚仍称盲孔=错误几何)
  feas   可行性:影响可制造/可装配
  value  价值:更好的工程实践(提示,不阻断)
"""

from . import primitives as registry

HARD = "hard"
FEAS = "feas"
VALUE = "value"


def _part_name(p):
    return (p.get("params") or {}).get("name", "")


def _get(part, key):
    return (part.get("params") or {}).get(key)


def _bbox_size(parts):
    """粗略包围盒(L/W/H)从 plate/box 类零件估算,供壁厚类规则用。"""
    L = W = H = 0
    for p in parts:
        t = p.get("type")
        if t == "plate":
            L = max(L, _get(p, "L") or 0)
            W = max(W, _get(p, "W") or 0)
            H = max(H, _get(p, "t") or 0)
        elif t in ("shell_box", "u_channel"):
            L = max(L, _get(p, "L") or 0)
            W = max(W, _get(p, "W") or 0)
            H = max(H, _get(p, "H") or 0)
    return L, W, H


def _find(parts, name):
    for p in parts:
        if _part_name(p) == name:
            return p
    return None


def validate(parts, joints=None):
    """parts/joints(model_state 状态结构)→ 违规列表。

    返回 [{level, part, rule, message, hint}]——LLM 拿到后自行修正,
    hard 级违规 compose_design 会拒绝执行(几何必然错误)。
    """
    violations = []
    joints = joints or []
    L, W, H = _bbox_size(parts)

    def add(level, part, rule, msg, hint=""):
        violations.append({"level": level, "part": part, "rule": rule,
                           "message": msg, "hint": hint})

    # ---- hard:孔类几何律 ----
    for p in parts:
        if p.get("type") != "side_hole":
            continue
        name = _part_name(p)
        depth = _get(p, "depth") or 0
        radius = _get(p, "radius") or 0
        through = bool(_get(p, "through"))
        if radius <= 0:
            add(HARD, name, "hole_radius_positive", "孔半径必须 > 0")
        if not through and depth <= 0:
            add(HARD, name, "blind_hole_depth", "盲孔深度必须 > 0")
        # 壁厚参照:取包围盒最小方向的近似厚度(plate 用 t 精确)
        thick = None
        base = _find(parts, _get(p, "base") or "") if _get(p, "base") else None
        if base and base.get("type") == "plate":
            thick = _get(base, "t")
        if thick and not through and depth >= thick:
            add(HARD, name, "blind_vs_wall",
                "盲孔深度 %.1f ≥ 基体厚度 %.1f——底部无材料,实际为贯穿孔"
                % (depth, thick),
                "改 through=true,或 depth < %.1f" % thick)

    # ---- hard:布尔引用存在性 ----
    for p in parts:
        t = p.get("type")
        if t == "subtract":
            base = _get(p, "base")
            if base and not _find(parts, base):
                add(HARD, _part_name(p), "subtract_base_missing",
                    "subtract 的 base '%s' 不存在" % base)
            for tool in (_get(p, "tools") or []):
                if not _find(parts, tool):
                    add(HARD, _part_name(p), "subtract_tool_missing",
                        "subtract 刀具 '%s' 不存在" % tool)
        elif t == "fuse":
            for n in (_get(p, "part_names") or []):
                if not _find(parts, n):
                    add(HARD, _part_name(p), "fuse_member_missing",
                        "fuse 成员 '%s' 不存在" % n)

    # ---- feas:未知原语/参数 ----
    for p in parts:
        t = p.get("type")
        if t not in registry.PRIMITIVE_REGISTRY:
            add(FEAS, _part_name(p), "unknown_primitive",
                "未知原语 '%s'" % t,
                "调 list_primitives 查看可用原语")
        else:
            dropped = _unknown_params(t, p.get("params") or {})
            if dropped:
                add(FEAS, _part_name(p), "unknown_params",
                    "参数 %s 不被原语 '%s' 接受(将被忽略)" % (dropped, t),
                    "以 list_primitives 的 schema 为准")

    # ---- value:工程惯例 ----
    for p in parts:
        t = p.get("type")
        if t in ("plate", "shell_box", "u_channel"):
            thick = _get(p, "t") or 0
            if 0 < thick < 2:
                add(VALUE, _part_name(p), "min_wall_thickness",
                    "壁厚 %.1fmm 偏薄(金属件常规 ≥3mm)" % thick,
                    "金属件 3-8mm,塑料件 4-6mm;或查国标(query_standard)")

    return violations


def _unknown_params(ptype, params):
    import inspect
    fn = registry.PRIMITIVE_REGISTRY.get(ptype, {}).get("fn")
    if fn is None:
        return []
    try:
        sig = set(inspect.signature(fn).parameters)
    except (ValueError, TypeError):
        return []
    aliases = registry._PARAM_ALIASES
    known_alias = set()
    for canon, al in aliases.items():
        known_alias.update(al)
    return [k for k in params
            if k not in sig and k not in known_alias and k != "name"]


def hard_failures(parts, joints=None):
    """仅 hard 违规(compose_design 执行前判定)。"""
    return [v for v in validate(parts, joints) if v["level"] == HARD]
