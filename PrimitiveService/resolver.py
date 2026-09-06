"""设计语言演算器 V0 —— 句子 → parts/joints(零决策执行流)。

立场(《设计语言演算架构_V0.md》):结果是算出来的。
本模块不含任何设计决策:体元=数学定义求值,特征=通用算子代数,
关系=约束方程闭式解,全程轨迹可追溯。无 LLM、无概率、无 recipe 表——
"空心球"不是词条,是 壳算子作用在球定义上的一次演算。

执行顺序: 依赖拓扑排序 → 体元求值(含特征分解) → 关系方程解位姿
         → 约束判定(PASS/VIOLATION) → 输出 registry parts。
"""

import math

from grammar import BODY_KINDS, FEATURE_OPS, RELATIONS


# ============ 体元包围盒(锚点语义的唯一事实) ============

def _extents(kind, p):
    """给定体元参数,返回 (bottom, top, xmin, xmax, ymin, ymax) —— 相对锚点局部系。"""
    if kind == "sphere":
        r = float(p["r"])
        return (-r, r, -r, r, -r, r)
    if kind == "cylinder":
        r, h = float(p["r"]), float(p["h"])
        return (0, h, -r, r, -r, r)
    if kind == "box":
        L, W, H = float(p["L"]), float(p["W"]), float(p["H"])
        return (0, H, 0, L, 0, W)
    raise ValueError("unknown kind: %s" % kind)


def _anchor(kind):
    return BODY_KINDS[kind]["anchor"]


# ============ 拓扑排序(关系 a 依赖 b → b 先定位) ============

def _order_bodies(bodies, relations):
    by_id = {b["id"]: b for b in bodies}
    indeg = {i: 0 for i in by_id}
    adj = {i: [] for i in by_id}
    for r in relations:
        a, b = r.get("a"), r.get("b")
        if a in by_id and b in by_id and r["rel"] in ("rests_on_centered", "gap_z"):
            if b not in adj[a]:          # a 踩在 b 上 → b 先
                adj[b].append(a)
                indeg[a] += 1
    order, stack = [], [i for i in by_id if indeg[i] == 0]
    while stack:
        n = stack.pop()
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                stack.append(m)
    if len(order) != len(by_id):
        raise ValueError("关系存在循环依赖,无法拓扑排序")
    return [by_id[i] for i in order]


# ============ 演算主流程 ============

def evaluate(sentence):
    """句子(已过 grammar.validate) → {status, parts, checks, trace}。"""
    bodies = sentence["bodies"]
    relations = sentence.get("relations", [])
    trace, checks = [], []

    # ① 依赖排序 + 默认位姿(无关系定位 → 锚点落在原点)
    ordered = _order_bodies(bodies, relations)
    kind_of = {b["id"]: b["kind"] for b in bodies}
    par_of = {b["id"]: {k: float(v) for k, v in b["params"].items()
                        if k in BODY_KINDS[b["kind"]]["params"]}
              for b in bodies}
    feats_of = {b["id"]: b.get("features", []) for b in bodies}
    pos = {b["id"]: [0.0, 0.0, 0.0] for b in bodies}
    trace.append({"step": "evaluate", "text":
                  "体元求值: " + "; ".join("%s=%s%s" % (b["id"], b["kind"],
 routine_par(par_of[b["id"]])) for b in ordered)})

    # ② 关系方程:逐条闭式解,记录方程与解
    for r in relations:
        rel, a, b = r["rel"], r["a"], r["b"]
        if rel == "rests_on_centered":
            ka, kb = kind_of[a], kind_of[b]
            ext_b = _extents(kb, par_of[b])
            top_b = pos[b][2] + ext_b[1]
            ext_a = _extents(ka, par_of[a])
            if _anchor(ka) == "center":
                z_new = top_b + (-ext_a[0])          # 球: 球心 = 板顶 + r
                eq = "z(%s.center) = z(%s.top) + %g" % (a, b, -ext_a[0])
            else:
                z_new = top_b                        # 盒/筒: 底面 = 板顶
                eq = "z(%s.bottom) = z(%s.top)" % (a, b)
            pos[a][2] = z_new
            pos[a][0] = pos[b][0]
            pos[a][1] = pos[b][1]
            trace.append({"step": "relation", "rel": rel, "eq": eq,
                          "solve": "%s.pos = %s" % (a, [round(v, 6) for v in pos[a]])})
        elif rel == "gap_z":
            ext_b = _extents(kind_of[b], par_of[b])
            top_b = pos[b][2] + ext_b[1]
            g = float(r.get("params", {}).get("g", r.get("g", 0)) or 0)
            ext_a = _extents(kind_of[a], par_of[a])
            pos[a][2] = top_b + g + (-ext_a[0] if _anchor(kind_of[a]) == "center" else 0)
            trace.append({"step": "relation", "rel": rel,
                          "eq": "z(%s.bottom) = z(%s.top) + %g" % (a, b, g),
                          "solve": "%s.pos_z = %g" % (a, pos[a][2])})
        elif rel == "coaxial_z":
            pos[a][0] = pos[b][0]
            pos[a][1] = pos[b][1]
            trace.append({"step": "relation", "rel": rel,
                          "eq": "xy(%s.axis) = xy(%s.axis)" % (a, b),
                          "solve": "%s.xy = %s" % (a, pos[a][:2])})

    # ③ 特征算子代数 → parts 分解
    parts, part_geo = [], {}
    for bid in [b["id"] for b in ordered]:
        kind, p = kind_of[bid], par_of[bid]
        feats = feats_of[bid]
        shell = next((f for f in feats if f["op"] == "shell"), None)
        outer_name = bid + "_outer" if shell else bid
        emit_main(kind, outer_name, p, pos[bid], parts, part_geo, trace)
        if shell:
            t = float(shell["t"])
            inner_p = erode(kind, p, t)
            if inner_p is None:
                checks.append(violation("𝒞ₘ_shell", "%s 壳厚 %g 侵蚀越界(体元尺寸不足)" % (bid, t)))
            else:
                emit_tool(kind, bid + "_cavity", inner_p, pos[bid], t, parts, part_geo, trace)
                parts.append({"type": "subtract", "params": {
                    "name": bid, "base": outer_name, "tools": [bid + "_cavity"]}})
                trace.append({"step": "operator", "op": "shell",
                              "text": "%s = %s ∖ %s (布尔差演算)" % (bid, outer_name, bid + "_cavity")})
        for f in feats:
            if f["op"] not in FEATURE_OPS:
                raise ValueError("未知算子: %s" % f["op"])

    # ④ 约束判定(𝒫/𝒞ₘ,只允许 PASS/VIOLATION)
    _check_shell_sizes(bodies, kind_of, par_of, checks)
    _check_contact(bodies, relations, kind_of, par_of, pos, checks)

    ok = all(c["result"] == "PASS" for c in checks)
    return {"status": "ok" if ok else "violation",
            "parts": parts, "checks": checks, "trace": trace,
            "positions": {k: [round(v, 6) for v in vv] for k, vv in pos.items()}}


# ============ 辅助:参数描述/发射/侵蚀/判定 ============

def routine_par(p):
    return "(" + ",".join("%s=%g" % (k, v) for k, v in sorted(p.items())) + ")"


def emit_main(kind, name, p, cpos, parts, part_geo, trace):
    ext = _extents(kind, p)
    if kind == "sphere":
        pos = list(cpos)
        parts.append({"type": "sphere", "params": {"name": name, "r": p["r"], "pos": pos}})
    elif kind == "cylinder":
        pos = list(cpos)
        parts.append({"type": "cylinder", "params": {"name": name, "r": p["r"], "h": p["h"], "pos": pos}})
    else:
        pos = list(cpos)
        parts.append({"type": "plate", "params": {"name": name, "L": p["L"], "W": p["W"], "t": p["H"], "pos": pos}})
    part_geo[name] = {"kind": kind, "ext": ext, "pos": pos}
    trace.append({"step": "evaluate", "text": "%s = %s%s @ %s (锚点:%s)"
                  % (name, kind, routine_par(p), [round(v, 3) for v in pos], _anchor(kind))})


def emit_tool(kind, name, inner_p, cpos, t, parts, part_geo, trace):
    """内腔工具体:均匀侵蚀 t —— 位置随母体,盒/筒需整体内缩 t。"""
    parts.append({"type": {"sphere": "sphere", "cylinder": "cylinder", "box": "plate"}[kind],
                  "params": tool_params(kind, name, inner_p, cpos, t)})
    part_geo[name] = {"kind": kind, "ext": _extents(kind, inner_p), "pos": list(cpos)}


def tool_params(kind, name, ip, cpos, t):
    if kind == "sphere":
        return {"name": name, "r": ip["r"], "pos": list(cpos)}
    if kind == "cylinder":
        return {"name": name, "r": ip["r"], "h": ip["h"], "pos": [cpos[0], cpos[1], cpos[2] + t]}
    return {"name": name, "L": ip["L"], "W": ip["W"], "t": ip["H"], "pos": [cpos[0], cpos[1], cpos[2] + t]}


def erode(kind, p, t):
    """体.offset(−t):均匀内缩。越界返回 None(交由判定报告 VIOLATION)。"""
    if kind == "sphere":
        r = p["r"] - t
        return None if r <= 0 else {"r": r}
    if kind == "cylinder":
        r, h = p["r"] - t, p["h"] - 2 * t
        return None if r <= 0 or h <= 0 else {"r": r, "h": h}
    L, W, H = p["L"] - 2 * t, p["W"] - 2 * t, p["H"] - 2 * t
    return None if min(L, W, H) <= 0 else {"L": L, "W": W, "H": H}


def violation(axiom, detail):
    return {"constraint": axiom, "result": "VIOLATION", "detail": detail}


def _check_shell_sizes(bodies, kind_of, par_of, checks):
    for b in bodies:
        for f in b.get("features", []):
            if f["op"] == "shell":
                t = float(f["t"])
                p = par_of[b["id"]]
                lim = p["r"] if kind_of[b["id"]] == "sphere" else \
                    (min(p["r"], p["h"] / 2) if kind_of[b["id"]] == "cylinder" else min(p["L"], p["W"], p["H"]) / 2)
                ok = t < lim
                checks.append({"constraint": "𝒞ₘ_shell(%s)" % b["id"], "result": "PASS" if ok else "VIOLATION",
                               "detail": "壳厚 t=%g < 侵蚀极限 %g" % (t, lim) if ok
                               else "壳厚 t=%g 超过侵蚀极限 %g" % (t, lim)})


def _check_contact(bodies, relations, kind_of, par_of, pos, checks):
    """贴合关系:接触面共位且体积不干涉(包围盒级确定性检查)。"""
    for r in relations:
        if r["rel"] != "rests_on_centered":
            continue
        a, b = r["a"], r["b"]
        ext_a = _extents(kind_of[a], par_of[a])
        ext_b = _extents(kind_of[b], par_of[b])
        bottom_a = pos[a][2] + ext_a[0]
        top_b = pos[b][2] + ext_b[1]
        ok = abs(bottom_a - top_b) < 1e-6
        checks.append({"constraint": "𝒫_contact(%s→%s)" % (a, b),
                       "result": "PASS" if ok else "VIOLATION",
                       "detail": "%s.bottom=%g vs %s.top=%g" % (a, bottom_a, b, top_b)})
