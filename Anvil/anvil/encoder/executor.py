"""收报机 — 数字矩阵 → 查表 → stub 执行（不接真 OCCT，打印调用链）

按数字顺序盲扫描，每个功能编号查译码表得 OCCT 入口，打印"调用OCCT: BRepPrimAPI_MakeSphere(r=50)"。
真接 OCCT 时替换 stub_print 为真实调用即可。
"""
from anvil.encoder.codetable import get, is_reference, segment_of, valid


def execute(dltq, seq, ledger=None):
    """执行一条 ΔQ 数字矩阵（stub：打印调用链，不接真 OCCT）

    Args:
        dltq: 数字数组
        seq: 指令序号
        ledger: dltQ 账本（用于记录执行结果、查引用对象）
    Returns:
        list[dict] 执行步骤列表 [{step, impl, params, note}]
    """
    steps = []
    i = 0
    n = len(dltq)
    while i < n:
        code = int(dltq[i])
        entry = get(code)
        if entry is None:
            steps.append({"step": i, "code": code, "impl": None, "params": {}, "note": "非法编码 %d" % code})
            i += 1
            continue

        if is_reference(code):
            # 引用算子，不单独执行，作为元信息记录
            if code == 990:
                ref = int(dltq[i + 1])
                steps.append({"step": i, "code": code, "impl": "ref", "params": {"ref": ref}, "note": "引用 #%d" % ref})
                i += 2
            else:
                steps.append({"step": i, "code": code, "impl": "ref", "params": {}, "note": entry["term"]})
                i += 1
            continue

        # 功能/算子：查表得底层实现入口 + 参数
        impl = entry["impl"]
        term = entry["term"]
        params = entry["params"]
        consumed = {}
        i += 1
        j = 0
        while j < len(params) and i < n:
            pname = params[j]
            # 可选参数省略判断
            if pname.startswith("[") and i < n:
                nxt = int(dltq[i])
                if is_reference(nxt) or valid(nxt):
                    break
            if any(k in pname for k in ("引用", "对象", "目标", "面1", "面2", "轴1", "轴2")):
                if int(dltq[i]) == 990:
                    consumed[pname] = "#%d" % int(dltq[i + 1])
                    i += 2
                else:
                    consumed[pname] = "当前/上一"
                    i += 1
            else:
                consumed[pname] = dltq[i]
                i += 1
            j += 1
        # stub 打印
        param_repr = ", ".join("%s=%s" % (k, v) for k, v in consumed.items())
        stub_line = "调用实现: %s(%s)  // %s" % (impl, param_repr, term)
        print("[stub #%d] %s" % (seq, stub_line))
        steps.append({"step": i - 1 - len(consumed), "code": code, "impl": impl, "params": consumed, "note": stub_line})

    # 标记账本
    if ledger:
        ledger.mark_executed(seq, {"steps": steps, "stub": True})

    return steps
