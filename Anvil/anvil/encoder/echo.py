"""回显 — 数字矩阵 → 中文（给用户确认/纠正）

解析 dltQ 数字数组，按译码表查主词+参数+引用，拼成人类可读中文。
例如 [4,50.0,202,10.0] → "#1: 球(r=50)·抽壳(壁厚=10)"
体元按参数表 v2 定长(尺寸+位置[体心]+方位)：长方体(长=100,宽=60,高=10)@(50,30,5)
"""
from anvil.encoder.codetable import get, is_reference, GEOMETRY_SCHEMA, geo_params, CODETABLE

_OPSET = set(CODETABLE.keys())

# 引用型参数名（参数值是 990+序号 而非数值）
_REF_PARAM_KEYS = ("引用", "对象", "目标", "面1", "面2", "轴1", "轴2")


def _is_ref_param(name):
    return any(k in name for k in _REF_PARAM_KEYS)


def _is_optional(name):
    return name.startswith("[")


def _fmt_num(x):
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def dltq_to_echo(dltq, seq=None):
    """数字数组 → 中文回显串

    Args:
        dltq: [4, 50.0, 202, 10.0] 数字数组
        seq: 指令序号（None 则不前缀 #seq:）
    Returns:
        "#1: 球(r=50)·抽壳(壁厚=10)" 中文串
    """
    i = 0
    parts = []
    n = len(dltq)
    while i < n:
        code = int(dltq[i])
        entry = get(code)
        if entry is None:
            parts.append("?(%d)" % code)
            i += 1
            continue

        # 引用算子 990/991/992
        if code == 990:
            ref = int(dltq[i + 1]) if i + 1 < n else 0
            parts.append("[#%d]" % ref)
            i += 2
            continue
        if code == 991:
            parts.append("[当前]")
            i += 1
            continue
        if code == 992:
            parts.append("[上一]")
            i += 1
            continue

        # 体元(参数表 v2:定长全参 尺寸+位置+方位)
        g = GEOMETRY_SCHEMA.get(code)
        if g:
            i += 1  # 跳过编号
            ps = geo_params(code)
            n_full = len(ps)
            vals = [(float(dltq[i + k]) if i + k < n else 0.0) for k in range(n_full)]
            i += min(n_full, n - i)
            ns = len(g["size"])
            size = vals[:ns]
            pos = vals[ns:ns + 3]
            orient = vals[ns + 3:ns + 5] if not g.get("no_orient") else []
            term_str = "%s(%s)" % (entry["term"], ",".join(
                "%s=%s" % (g["size"][k], _fmt_num(size[k])) for k in range(ns)))
            if any(abs(p) > 1e-9 for p in pos):
                term_str += "@(%g,%g,%g)" % (pos[0], pos[1], pos[2])
            if orient and any(abs(o) > 1e-9 for o in orient):
                term_str += "↺%g°,%g°" % (orient[0], orient[1])
            parts.append(term_str)
            continue

        # 打孔 207 段(段式:引用+半径+(深度)+(756孔心))——多段各回显
        if code == 207:
            i += 1
            ref = None; r = None; depth = None; xy = None
            while i < n:
                c2 = int(dltq[i])
                if c2 == 990 and i + 1 < n:
                    ref = "#%d" % int(dltq[i + 1]); i += 2
                elif c2 in (991, 992):
                    ref = "当前" if c2 == 991 else "上一"; i += 1
                elif c2 == 756 and i + 3 < n:
                    xy = (dltq[i + 1], dltq[i + 2]); i += 4
                elif c2 in (750, 751, 752):
                    i += 1
                elif r is None:
                    r = dltq[i]; i += 1  # 引用后首数值=半径(位置优先,码值不歧义)
                elif depth is None and int(dltq[i]) not in _OPSET:
                    depth = dltq[i]; i += 1
                else:
                    break
            parts.append("打孔(目标=%s,r=%s%s%s)" % (
                ref or "缺省", _fmt_num(r) if r is not None else "?",
                ",深=%s" % _fmt_num(depth) if depth is not None else "",
                "@(%g,%g)" % xy if xy else "（中心孔）"))
            continue

        # 功能/算子 + 参数
        term = entry["term"]
        params = entry["params"]
        consumed = []
        j = 0
        i += 1  # 跳过功能编号
        while j < len(params) and i < n:
            pname = params[j]
            if _is_optional(pname):
                # 可选参数：若下一个是引用算子或新功能编号，则省略
                if is_reference(int(dltq[i])) or (i < n and int(dltq[i]) in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                                                            100, 101, 102, 103, 200, 201, 202, 203, 204, 205, 206, 207, 208,
                                                                            300, 301, 302, 303, 400, 401, 402, 403, 404,
                                                                            750, 751, 752, 753, 754, 755, 990, 991, 992, 999)):
                    break  # 省略该可选参数
            if _is_ref_param(pname):
                # 引用型参数：990+序号 或 991/992
                if int(dltq[i]) == 990:
                    ref = int(dltq[i + 1])
                    consumed.append("%s=#%d" % (pname, ref))
                    i += 2
                elif int(dltq[i]) in (991, 992):
                    consumed.append("%s=%s" % (pname, "当前" if int(dltq[i]) == 991 else "上一"))
                    i += 1
                else:
                    break
            else:
                consumed.append("%s=%s" % (pname, _fmt_num(dltq[i])))
                i += 1
            j += 1
        param_str = ",".join(consumed) if consumed else ""
        parts.append("%s(%s)" % (term, param_str))

    echo = " · ".join(parts)
    # Δ 前缀：区分译码账本序号与 chat 设计日志序号(两套体系,避免"序号重复"歧义)
    return "Δ#%d: %s" % (seq, echo) if seq is not None else echo
