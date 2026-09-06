# -*- coding: utf-8 -*-
"""Primordium 拓扑心象求解器（V1 规则式）。

定位分工(2026-09-07 用户定):LLM 只做翻译——语义里不确定的位置参数写 -1,
禁止臆造数值;空间推理归 Primordium:由拓扑心象(每组件 bbox/位置)+约束算子
推导 -1 位的实参。推不出的返回欠约束问题(上层转设计者提问)。

V1 规则集:
- 759 贴边放置: 759,990,N,D,G —— 放在 #N 的 D 侧(1=X+ 2=X- 3=Y+ 4=Y-)外侧,
  表面间隙 G → 体心轴值 = N.bbox 边 ± 体半尺寸 ± G
- 752 XY 中心对齐: 752,990,N —— 未定的 x/y 位取 #N 的 bbox 中心
- z 位 -1: 贴地(体心 z = 体 z 半尺寸)
- 其余位置位 -1 无约束覆盖 → unresolved(提问)
"""
from anvil.encoder.codetable import GEOMETRY_SCHEMA, geo_arity


def _half_extent(code, size, axis):
    """体元某轴半尺寸(方位 0 假设)。axis∈0,1,2 (x,y,z)。"""
    ns = len(GEOMETRY_SCHEMA[code]["size"])
    size = list(size) + [0.0] * max(0, ns - len(size))
    if code == 1:      # 长方体 [长,宽,高]
        return float(size[axis]) / 2.0
    if code in (2, 3):  # 圆柱/圆锥 [半径,(顶半径),高]
        h = float(size[-1])
        r = max(float(size[0]), float(size[1]) if len(size) > 2 else 0.0)
        return (h / 2.0) if axis == 2 else r
    if code == 4:      # 球 [半径]
        return float(size[0])
    if code == 5:      # 圆环 [主半径,管半径]
        return float(size[0]) + float(size[1])
    if code in (7, 8):
        return max((float(s) for s in size if s), default=0.0) / 2.0
    return 0.0


def solve_dltq(dltq, topo):
    """dltq: 含 -1 未定位的矩阵; topo: {seq: {"bbox":[XMin,XMax,YMin,YMax,ZMin,ZMax],
    "center":[x,y,z]}} 心象快照。

    返回 (solved_dltq, unresolved_questions); unresolved 非空时 solved 无效。
    被消费的 759/752 段从结果矩阵摘除(实参已解入参数位,执行层无需再见)。
    """
    d = list(dltq)
    n = len(d)
    unresolved = []

    # 收集约束段:759=(759,990,N,侧码,间隙) 5元; 752=(752,990,N) 3元
    cons759, cons752 = [], []
    i = 0
    while i < n:
        c = int(d[i])
        if c == 759 and i + 5 <= n and int(d[i + 1]) == 990:
            side, gap = int(d[i + 3]), float(d[i + 4])
            if side in (1, 2, 3, 4) and gap >= 0:
                cons759.append({"span": (i, i + 5), "ref": int(d[i + 2]),
                                "side": side, "gap": gap})
                i += 5
                continue
        if c == 752 and i + 3 <= n and int(d[i + 1]) == 990:
            cons752.append({"span": (i, i + 3), "ref": int(d[i + 2])})
            i += 3
            continue
        i += 1

    def _bbox(seq):
        t = topo.get(seq)
        return (t or {}).get("bbox")

    # 逐体元解位置位 -1
    used = set()
    i = 0
    while i < n:
        c = int(d[i])
        if c in GEOMETRY_SCHEMA and 1 <= c <= 99:
            need = geo_arity(c)
            base = i + 1
            ns = len(GEOMETRY_SCHEMA[c]["size"])
            pos_idx = base + ns
            if pos_idx + 2 < n and any(float(d[pos_idx + k]) == -1 for k in range(3)):
                size = [float(x) for x in d[base:base + ns]]
                for k in range(3):
                    if float(d[pos_idx + k]) != -1:
                        continue
                    if k == 2:  # z → 贴地
                        d[pos_idx + k] = _half_extent(c, size, 2)
                        continue
                    # 轴向优先:759(该轴) → 752(中心对齐)
                    val, span = None, None
                    for con in cons759:
                        ax = 0 if con["side"] in (1, 2) else 1
                        if ax == k and con["span"] not in used:
                            bb = _bbox(con["ref"])
                            if not bb:
                                unresolved.append("贴边约束引用 #%d 不在拓扑心象中——只能对已有对象放置" % con["ref"])
                                used.add(con["span"])
                                break
                            half = _half_extent(c, size, k)
                            gap = con["gap"]
                            if con["side"] == 1:
                                val = bb[1] + half + gap
                            elif con["side"] == 2:
                                val = bb[0] - half - gap
                            elif con["side"] == 3:
                                val = bb[3] + half + gap
                            else:
                                val = bb[2] - half - gap
                            span = con["span"]
                            break
                    if val is None and not unresolved:
                        for con in cons752:
                            if con["span"] not in used:
                                bb = _bbox(con["ref"])
                                if not bb:
                                    unresolved.append("对齐约束引用 #%d 不在拓扑心象中" % con["ref"])
                                    used.add(con["span"])
                                    break
                                t = topo.get(con["ref"]) or {}
                                val = (t.get("center") or [0, 0, 0])[k]
                                span = con["span"]
                                break
                    if val is not None:
                        d[pos_idx + k] = round(val, 4)
                        if span:
                            used.add(span)
                    elif not unresolved:
                        unresolved.append("新体的 %s 位置未定(-1)且无约束可推导——"
                                          "请补充:放在哪一侧/距哪个对象边缘多少毫米,或直接给坐标"
                          % ("x" if k == 0 else "y"))
            i = base + need
        else:
            i += 1

    # 摘除被消费的约束段
    if used:
        drop = set()
        for s0, s1 in used:
            drop.update(range(s0, s1))
        d = [x for k, x in enumerate(d) if k not in drop]

    return d, unresolved
