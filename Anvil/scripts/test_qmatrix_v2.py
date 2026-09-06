"""需求矩阵 Q 翻译测试 V2 —— FreeCAD 原语枚举 + 约束输出 vs 自由文本对照。

几何体枚举以 FreeCAD Part 原语为准(8 种实体):
  box{L,W,H} cylinder{r,h} sphere{r} ellipsoid{r1,r2,r3}
  cone{r1,r2,h} torus{r1,r2} prism{n,r,h} wedge{L,W,H}
  (helix 为曲线体不入实体枚举; PartDesign 同此 8 种)

输出矩阵(Q 简化版, 对齐 需求矩阵Q定义_V0.md 的 inst/param/feat 结构):
  bodies[i] = {kind, params, rot_axis, rot_deg}   # inst+param+方位(旋转)
  ops[j]    = {op: fuse|cut|common, base, tool}   # 布尔运算关系(按 bodies 下标)

对照两种翻译模式:
  tool: 智谱 function calling, schema 约束输出(词表注入, 一词一义)
  free: 自由文本输出 JSON(基线)
指标: 一次译过率 / kind槽位 / 参数槽位 / 旋转 / 运算 / 解析失败率 / 类型混淆

用法: cd Anvil && python3 scripts/test_qmatrix_v2.py [--mode tool|free|both] [--n 100]
断点续跑: 结果文件存在时自动只补失败/缺失项。
"""
import os
import re
import sys
import json
import random
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT))

from anvil.llm import chat  # noqa: E402

# ---------- FreeCAD 原语枚举(定值 schema) ----------
KINDS = {
    "box":       {"freecad": "Part Box",       "params": ["L", "W", "H"],        "zh": "长方体/立方体"},
    "cylinder":  {"freecad": "Part Cylinder",  "params": ["r", "h"],             "zh": "圆柱"},
    "sphere":    {"freecad": "Part Sphere",    "params": ["r"],                  "zh": "球"},
    "ellipsoid": {"freecad": "Part Ellipsoid", "params": ["r1", "r2", "r3"],     "zh": "椭球"},
    "cone":      {"freecad": "Part Cone",      "params": ["r1", "r2", "h"],      "zh": "圆锥/圆台"},
    "torus":     {"freecad": "Part Torus",     "params": ["r1", "r2"],           "zh": "圆环"},
    "prism":     {"freecad": "Part Prism",     "params": ["n", "r", "h"],        "zh": "正棱柱"},
    "wedge":     {"freecad": "Part Wedge",     "params": ["L", "W", "H"],        "zh": "楔形体"},
}
PARAM_KEYS = sorted({k for v in KINDS.values() for k in v["params"]})
OPS = ["fuse", "cut", "common"]
AXES = ["x", "y", "z"]

# ---------- 下单措辞模板 ----------
TEMPLATES = {
    "box":       ["长方体，尺寸{L}X{W}X{H}", "长{L}宽{W}高{H}的方块", "方块，{L}X{W}X{H}"],
    "cylinder":  ["圆柱，半径{r}，高{h}", "圆柱，直径{d}，高{h}", "圆柱，r{r}xh{h}"],
    "sphere":    ["球，半径{r}", "球，直径{d}", "钢球，r={r}"],
    "ellipsoid": ["椭球，三轴半径{r1}、{r2}、{r3}", "椭球体，{r1}/{r2}/{r3}"],
    "cone":      ["圆锥，底半径{r1}，高{h}", "圆台，上半径{r2}下半径{r1}，高{h}", "锥台，底半径{r1}顶半径{r2}高{h}"],
    "torus":     ["圆环，环半径{r1}，管半径{r2}", "圆环体，R{r1}r{r2}"],
    "prism":     ["正{n}棱柱，外接圆半径{r}，高{h}", "正{n}棱柱体，r{r}xh{h}"],
    "wedge":     ["楔形体，底面{L}x{W}，高{H}", "楔形块，{L}X{W}X{H}"],
}
FRAMES = [
    "设计一个{b0}。", "设计一个{b0}，一个{b1}。", "设计一个{b0}，一个{b1}，一个{b2}。",
    "帮我做：{b0}；{b1}；{b2}。", "我需要{b0}，还有{b1}。",
]
CUT_FRAMES = ["从{base}里切掉{tool}", "在{base}上把{tool}位置切掉", "{base}减去{tool}"]
FUSE_FRAMES = ["把{base}和{tool}融合成一个体", "{base}与{tool}合并", "将{base}和{tool}做并集"]
COMMON_FRAMES = ["取{base}和{tool}的公共部分", "{base}与{tool}求交集"]
ROT_FRAMES = ["绕{axis}轴旋转{deg}度", "旋转{deg}度（绕{axis}轴）"]

SYSTEM_GRAMMAR = """你是 CAD 需求翻译器。把用户设计指令翻译成 JSON 矩阵。词表(一词一义, 禁止编造):
kind 枚举(FreeCAD Part 原语)与参数:
- box: L,W,H (长方体; 三边全等即立方体)
- cylinder: r,h (圆柱; r=半径)
- sphere: r (球)
- ellipsoid: r1,r2,r3 (椭球三轴半径)
- cone: r1,r2,h (r1=底半径 r2=顶半径; r2=0 为尖圆锥, r2>0 为圆台)
- torus: r1,r2 (r1=环中心半径 r2=管半径)
- prism: n,r,h (正n棱柱, n>=3, r=外接圆半径)
- wedge: L,W,H (楔形体, 底面LxW高H)
尺寸说明: 用户说"直径d"时 r=d/2; 严禁引入词表外的参数。
布尔运算 op 枚举: fuse(并) cut(差) common(交); base/tool 为 bodies 下标(0起)。
旋转: rot_axis ∈ x|y|z, rot_deg 单位度, 未提旋转则为 none/0。
输出: 只输出一个 JSON 对象, 结构为 {"bodies":[{"kind","params","rot_axis","rot_deg"}],"ops":[{"op","base","tool"}]}, 无 ops 时为空数组, 禁止 markdown 代码块与任何解释。"""

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "emit_q_matrix",
        "description": "输出翻译后的需求矩阵",
        "parameters": {
            "type": "object",
            "properties": {
                "bodies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": sorted(KINDS)},
                            "params": {
                                "type": "object",
                                "properties": {k: {"type": "number"} for k in PARAM_KEYS},
                            },
                            "rot_axis": {"type": "string", "enum": AXES + ["none"]},
                            "rot_deg": {"type": "number"},
                        },
                        "required": ["kind", "params", "rot_axis", "rot_deg"],
                    },
                },
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": OPS},
                            "base": {"type": "integer"},
                            "tool": {"type": "integer"},
                        },
                        "required": ["op", "base", "tool"],
                    },
                },
            },
            "required": ["bodies", "ops"],
        },
    },
}


def _dims(rng):
    return dict(d=rng.choice([20, 30, 40, 50, 60, 80, 100]),
                r=rng.choice([10, 15, 20, 25, 30, 40, 50]),
                r1=rng.choice([10, 15, 20, 30, 40, 50]),
                r2=rng.choice([0, 5, 10, 15, 20, 30]),
                r3=rng.choice([10, 15, 20, 30, 40]),
                n=rng.choice([3, 4, 5, 6, 8]),
                a=rng.choice([30, 40, 50, 60, 80, 100]),
                L=rng.choice([60, 80, 100, 120, 150, 200]),
                W=rng.choice([30, 40, 50, 60, 80]),
                H=rng.choice([20, 30, 40, 50, 60, 80]),
                h=rng.choice([20, 30, 40, 50, 60, 80, 100]),
                t=rng.choice([3, 5, 8, 10]))


def gen_questions(n: int, seed: int = 7):
    rng = random.Random(seed)
    qs = []
    seen = set()
    while len(qs) < n:
        nb = rng.choices([1, 2, 3], weights=[30, 40, 30])[0]
        kinds = rng.sample(sorted(KINDS), nb)
        bodies, gt_bodies, phr = [], [], []
        for kind in kinds:
            dims = _dims(rng)
            if kind == "box":
                gt = {"L": dims["L"], "W": dims["W"], "H": dims["H"]}
            elif kind == "cylinder":
                gt = {"r": dims["r"], "h": dims["h"]}
            elif kind == "sphere":
                gt = {"r": dims["r"]}
            elif kind == "ellipsoid":
                gt = {"r1": dims["r1"], "r2": dims["r2"] if dims["r2"] else 10,
                      "r3": dims["r3"]}
            elif kind == "cone":
                gt = {"r1": dims["r1"], "r2": dims["r2"], "h": dims["h"]}
            elif kind == "torus":
                gt = {"r1": max(dims["r1"], 20), "r2": min(dims["r"] // 2 + 3, 10)}
            elif kind == "prism":
                gt = {"n": dims["n"], "r": dims["r1"], "h": dims["h"]}
            else:
                gt = {"L": dims["L"], "W": dims["W"], "H": dims["H"]}
            # 旋转(35% 概率)
            rot = None
            if rng.random() < 0.35:
                rot = (rng.choice(AXES), rng.choice([15, 30, 45, 90, 180]))
            view = dict(gt)
            if "r" in gt and kind in ("cylinder", "sphere") and rng.random() < 0.5:
                view = {k: ("直径%d" % (v * 2) if k == "r" else v) for k, v in gt.items()}
            tmpl = rng.choice(TEMPLATES[kind])
            fmt = {**dims, **gt}
            fmt.update({k: v for k, v in view.items() if isinstance(v, str)})
            fmt["d"] = gt.get("r", 0) * 2 if "r" in gt else dims["d"]
            ph = tmpl.format(**fmt)
            if rot:
                ph += "，" + rng.choice(ROT_FRAMES).format(axis=rot[0], deg=rot[1])
            bodies.append({"kind": kind, "params": gt, "rot": rot})
            gt_bodies.append({"kind": kind, "params": gt,
                              "rot_axis": rot[0] if rot else "none",
                              "rot_deg": rot[1] if rot else 0})
            phr.append(ph)
        # 布尔运算(>=2 体时 35%)
        ops = []
        if nb >= 2 and rng.random() < 0.35:
            op = rng.choice(OPS)
            bi, ti = rng.sample(range(nb), 2)
            ops.append({"op": op, "base": bi, "tool": ti})
            frame = {"cut": CUT_FRAMES, "fuse": FUSE_FRAMES, "common": COMMON_FRAMES}[op]
            phr.append(rng.choice(frame).format(base=phr[bi].split("，")[0], tool=phr[ti].split("，")[0]))
        sig = json.dumps([gt_bodies, ops])
        if sig in seen:
            continue
        seen.add(sig)
        tail = phr[len(kinds):]
        main = [phr[i] for i in range(len(kinds))]
        text = rng.choice(FRAMES[:nb] if nb < 3 else [FRAMES[2], FRAMES[3]]).format(
            b0=main[0], b1=main[1] if nb > 1 else "", b2=main[2] if nb > 2 else "")
        if tail:
            text += "布尔：" + "；".join(tail) + "。"
        qs.append({"text": text, "gt": {"bodies": gt_bodies, "ops": ops}})
    return qs


def norm_num(x):
    try:
        return round(float(x), 2)
    except Exception:
        return None


def ask(desc: str, mode: str, retries: int = 5):
    """返回 (raw, parsed_dict|None, parse_ok)"""
    last_err = ""
    for i in range(retries):
        try:
            if mode == "tool":
                resp = chat([{"role": "system", "content": SYSTEM_GRAMMAR},
                             {"role": "user", "content": desc}],
                            temperature=0, tools=[TOOL_SCHEMA])
                msg = resp.choices[0].message
                calls = getattr(msg, "tool_calls", None)
                raw = (calls[0].function.arguments if calls else (msg.content or ""))
            else:
                resp = chat([{"role": "system", "content": SYSTEM_GRAMMAR},
                             {"role": "user", "content": desc}], temperature=0)
                raw = resp.choices[0].message.content or ""
            txt = raw.strip()
            txt = re.sub(r"^```(json)?|```$", "", txt, flags=re.M).strip()
            m = re.search(r"\{.*\}", txt, re.S)
            if not m:
                last_err = raw
                continue
            try:
                data = json.loads(m.group(0))
                return raw, data, True
            except json.JSONDecodeError:
                last_err = raw
        except Exception as e:
            last_err = f"<error {e}>"
            import time
            time.sleep(min(45, 6 * (i + 1)))
            continue
        import time
        time.sleep(1)
    return last_err, None, False


def score(gt, data):
    """返回 (全对, kind对数, param对数, rot对数, op对数, 细节错误)"""
    ok_kind = ok_param = ok_rot = ok_op = 0
    errs = []
    gtb, db = gt["bodies"], (data or {}).get("bodies") or []
    if len(db) != len(gtb):
        errs.append(f"体数 {len(gtb)}→{len(db)}")
    for k, g in enumerate(gtb):
        if k >= len(db):
            break
        d = db[k]
        if d.get("kind") == g["kind"]:
            ok_kind += 1
        else:
            errs.append(f"[{k}]kind {g['kind']}→{d.get('kind')}")
        gp = g["params"]
        dp = d.get("params") or {}
        if not isinstance(dp, dict):
            dp = {}
        if all(norm_num(dp.get(pk)) == norm_num(pv) for pk, pv in gp.items()):
            ok_param += 1
        else:
            errs.append(f"[{k}]params {gp}→{ {pk: dp.get(pk) for pk in gp} }")
        if (d.get("rot_axis") or "none") == g["rot_axis"] and norm_num(d.get("rot_deg") or 0) == g["rot_deg"]:
            ok_rot += 1
        else:
            errs.append(f"[{k}]rot {g['rot_axis']}/{g['rot_deg']}→{d.get('rot_axis')}/{d.get('rot_deg')}")
    g_ops, d_ops = gt["ops"], (data or {}).get("ops") or []
    gset = {(o["op"], o["base"], o["tool"]) for o in g_ops}
    dset = {(o.get("op"), int(float(o.get("base", -1))), int(float(o.get("tool", -1)))) for o in d_ops}
    ok_op = len(gset & dset)
    if gset != dset:
        errs.append(f"ops {gset}→{dset}")
    total_ok = ok_kind + ok_param + ok_rot + ok_op
    total = len(gtb) * 3 + len(g_ops)
    return total_ok == total, ok_kind, ok_param, ok_rot, ok_op, errs


def run_mode(mode: str, questions, workers: int = 2):
    out = ROOT / "data" / f"geometry_qmatrix_v2_{mode}.json"
    out.parent.mkdir(exist_ok=True)
    results = [None] * len(questions)
    if out.exists():
        try:
            saved = json.loads(out.read_text())
            for i, row in enumerate(saved):
                if row and not row["raw"].startswith("<error"):
                    results[i] = row
        except Exception as e:
            print(f"[{mode}] 读取已有结果失败, 全量重跑:", e)
    todo = [i for i in range(len(questions)) if results[i] is None]
    print(f"[{mode}] 需新测/重测: {len(todo)}/{len(questions)}", flush=True)
    import time

    def work(idx):
        q = questions[idx]
        raw, data, parse_ok = ask(q["text"], mode)
        return idx, q, raw, data, parse_ok

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, i) for i in todo]
        for f in as_completed(futures):
            idx, q, raw, data, parse_ok = f.result()
            full, ok_kind, ok_param, ok_rot, ok_op, errs = score(q["gt"], data) if parse_ok else (False, 0, 0, 0, 0, ["parse_fail"])
            results[idx] = {"q": q["text"], "gt": q["gt"], "raw": str(raw)[:500],
                            "data": data, "parse_ok": parse_ok, "full": full,
                            "errs": errs[:6]}
            done += 1
            if done % 10 == 0:
                print(f"[{mode}] ...{done}/{len(todo)}", flush=True)
            time.sleep(0.6)

    # 汇总
    n = len(questions)
    parse_fail = sum(1 for r in results if r and not r["parse_ok"])
    full_ok = sum(1 for r in results if r and r["full"])
    tot_kind = tot_param = tot_rot = tot_op = 0
    acc_kind = acc_param = acc_rot = acc_op = 0
    kind_stat = {k: [0, 0] for k in KINDS}
    for r in results:
        if not r or not r["parse_ok"]:
            continue
        gtb = r["gt"]["bodies"]
        dd = (r["data"] or {}).get("bodies") or []
        for k, g in enumerate(gtb):
            kind_stat[g["kind"]][1] += 1
            if k < len(dd):
                if dd[k].get("kind") == g["kind"]:
                    acc_kind += 1
                    kind_stat[g["kind"]][0] += 1
                gp = g["params"]
                dp = dd[k].get("params") or {}
                if not isinstance(dp, dict):
                    dp = {}
                if all(norm_num(dp.get(pk)) == norm_num(pv) for pk, pv in gp.items()):
                    acc_param += 1
                if (dd[k].get("rot_axis") or "none") == g["rot_axis"] and norm_num(dd[k].get("rot_deg") or 0) == g["rot_deg"]:
                    acc_rot += 1
        g_ops = r["gt"]["ops"]
        d_ops = (r["data"] or {}).get("ops") or []
        gset = {(o["op"], o["base"], o["tool"]) for o in g_ops}
        dset = {(o.get("op"), int(float(o.get("base", -1))), int(float(o.get("tool", -1)))) for o in d_ops}
        tot_op += len(gset)
        acc_op += len(gset & dset)
        tot_kind += len(gtb)
        tot_param += len(gtb)
        tot_rot += len(gtb)
    print(f"\n=== [{mode}] 汇总({n} 题) ===")
    print(f"一次译过率(解析OK+全对): {full_ok}/{n} = {full_ok / n:.0%}")
    print(f"解析失败: {parse_fail}")
    print(f"kind 槽位: {acc_kind}/{tot_kind} = {acc_kind / max(1, tot_kind):.1%}")
    print(f"参数槽位: {acc_param}/{tot_param} = {acc_param / max(1, tot_param):.1%}")
    print(f"旋转槽位: {acc_rot}/{tot_rot} = {acc_rot / max(1, tot_rot):.1%}")
    print(f"运算槽位: {acc_op}/{tot_op} = {acc_op / max(1, tot_op):.1%}")
    for k, v in KINDS.items():
        ok, tot = kind_stat[k]
        if tot:
            print(f"  {k}: {ok}/{tot} = {ok / tot:.0%}")
    with open(out, "w") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=1)
    print(f"明细: {out}")
    return {"mode": mode, "full": full_ok, "n": n, "parse_fail": parse_fail,
            "kind": [acc_kind, tot_kind], "param": [acc_param, tot_param],
            "rot": [acc_rot, tot_rot], "op": [acc_op, tot_op]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both", choices=["tool", "free", "both"])
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    questions = gen_questions(args.n)
    modes = ["tool", "free"] if args.mode == "both" else [args.mode]
    summary = [run_mode(m, questions) for m in modes]
    if len(summary) == 2:
        print("\n=== 对照: tool(约束) vs free(自由文本) ===")
        for s in summary:
            print(f"  {s['mode']}: 一次译过 {s['full']}/{s['n']}, 解析失败 {s['parse_fail']}, "
                  f"kind {s['kind'][0]}/{s['kind'][1]}, 参数 {s['param'][0]}/{s['param'][1]}, "
                  f"旋转 {s['rot'][0]}/{s['rot'][1]}, 运算 {s['op'][0]}/{s['op'][1]}")


if __name__ == "__main__":
    main()
