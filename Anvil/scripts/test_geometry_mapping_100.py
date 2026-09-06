"""几何体→数字映射 LLM 压力测试(100 题 × 每题 3 个几何体)。

约定: 1=球, 2=空心球, 3=正方体, 4=长方体, 5=圆柱体
每题混合下单 3 个几何体(类型不重复、顺序随机), LLM 按出现顺序输出 3 个数字。
判分: 整题全对 / 槽位对(300 槽) / 无序集合对 / 类型级识别率 / 混淆分析。

用法: cd Anvil && ANVIL_LLM_BASE_URL=... ANVIL_LLM_API_KEY=... python3 scripts/test_geometry_mapping_100.py
"""
import os
import re
import sys
import json
import random
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

LABELS = {1: "球", 2: "空心球", 3: "正方体", 4: "长方体", 5: "圆柱体"}

# 每类的下单措辞模板(随机抽), {d}直径 {r}半径 {a}边长 {l}{w}{h}长宽高 {t}壁厚
TEMPLATES = {
    1: ["球，直径{d}mm", "实心球，半径{r}", "钢球，D={d}", "球体，球径{d}毫米"],
    2: ["空心球，直径{d}mm", "空心球，外径{d}，壁厚{t}", "中空球体，外径{d}", "薄壁球壳，外径{d}，壁厚{t}"],
    3: ["正方体，边长{a}mm", "立方体，{a}X{a}X{a}", "正方块，边长{a}", "正方体块，三边都是{a}"],
    4: ["长方体，尺寸：{l}X{w}X{h}", "长方体，长{l}宽{w}高{h}", "矩形块，{l}X{w}X{h}", "方块料，L={l},W={w},H={h}"],
    5: ["圆柱体，直径{d}，高{h}", "圆柱，D{d}xH{h}", "圆柱形轴段，半径{r}，长度{h}", "圆棒料，直径{d}，长度{h}"],
}

# 句式: 连接 3 个件的引导语
FRAMES = [
    "设计一个{a}，一个{b}，一个{c}。",
    "帮我做三个零件：{a}；{b}；{c}。",
    "我需要：{a}，{b}，还有{c}。",
    "画三个体：{a}、{b}、{c}。",
    "建三个模型——{a}；{b}；{c}。",
]

SYSTEM = (
    "你是一个几何体分类器。数字约定：1=球，2=空心球，3=正方体，4=长方体，5=圆柱体。"
    "用户的一条设计指令里会包含 3 个几何体，你只需按出现顺序输出 3 个数字(1-5)，"
    "用逗号分隔，禁止输出任何其他文字。"
)


def gen_questions(n: int, seed: int = 42):
    rng = random.Random(seed)
    questions = []
    seen = set()
    while len(questions) < n:
        types = rng.sample(sorted(LABELS), 3)  # 3 个不同类型, 顺序随机
        parts, dims_sig = [], []
        for t in types:
            dims = dict(d=rng.choice([20, 30, 40, 50, 60, 80, 100, 120]),
                        r=rng.choice([10, 15, 20, 25, 30, 40, 50, 60]),
                        a=rng.choice([30, 40, 50, 60, 80, 100]),
                        l=rng.choice([80, 100, 120, 150, 200]),
                        w=rng.choice([30, 40, 50, 60, 80]),
                        h=rng.choice([20, 30, 40, 50, 60, 80]),
                        t=rng.choice([3, 5, 8, 10]))
            parts.append(rng.choice(TEMPLATES[t]).format(**dims))
            dims_sig.append((t, tuple(sorted(dims.items()))))
        sig = (tuple(types), tuple(dims_sig))
        if sig in seen:  # 避免完全重复的题
            continue
        seen.add(sig)
        questions.append((types, rng.choice(FRAMES).format(a=parts[0], b=parts[1], c=parts[2])))
    return questions


def ask(desc: str, retries: int = 5) -> str:
    last = ""
    for i in range(retries):
        try:
            resp = chat([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": desc}], temperature=0)
            last = (resp.choices[0].message.content or "").strip()
            return last
        except Exception as e:
            last = f"<error {e}>"
            import time
            time.sleep(min(60, 5 * (i + 1)))  # 429 限流: 逐步退避 5/10/15/20/25s
    return last


CODE = {v: k for k, v in LABELS.items()}


def summarize(results):
    full = set_ok = order_swaps = errors = 0
    slot_total = slot_ok = 0
    type_stat = {t: [0, 0] for t in LABELS}
    confusions = {}
    for types, desc, raw, digits in results:
        expect = [str(t) for t in types]
        if raw.startswith("<error"):
            errors += 1
            continue
        if digits == expect:
            full += 1
        if sorted(digits) == sorted(expect):
            set_ok += 1
            if digits != expect:
                order_swaps += 1
        for k in range(3):
            slot_total += 1
            t = types[k]
            type_stat[t][1] += 1
            if k < len(digits) and digits[k] == expect[k]:
                slot_ok += 1
                type_stat[t][0] += 1
            else:
                got = digits[k] if k < len(digits) else "缺"
                key = (LABELS[t], LABELS.get(int(got), got) if str(got).isdigit() else got)
                confusions[key] = confusions.get(key, 0) + 1
    print("\n=== 汇总(100 题 × 3 几何体) ===")
    print(f"整题全对(含顺序): {full}/100")
    print(f"无序集合全对:     {set_ok}/100  (其中仅顺序错: {order_swaps})")
    print(f"槽位正确率:       {slot_ok}/{slot_total} = {slot_ok / max(1, slot_total):.1%}")
    print(f"调用失败:         {errors}")
    for t, name in LABELS.items():
        ok, total = type_stat[t]
        print(f"  {t}={name}: 槽位 {ok}/{total} = {ok / total:.1%}" if total else f"  {t}={name}: 未出现")
    if confusions:
        print("槽位混淆(期望→误判): ")
        for (e, g), c in sorted(confusions.items(), key=lambda x: -x[1]):
            print(f"  {e}→{g}: {c} 次")


def main() -> None:
    questions = gen_questions(100)
    out = ROOT / "data" / "geometry_mapping_100_result.json"
    out.parent.mkdir(exist_ok=True)

    # 断点续跑: 已有结果里成功的不重测, 只补失败/缺失(串行防限流)
    results = [None] * len(questions)
    if out.exists():
        try:
            saved = json.loads(out.read_text())
            for i, row in enumerate(saved):
                if i < len(results) and row and not row["raw"].startswith("<error"):
                    results[i] = ([CODE[c] for c in row["codes"]], row["q"], row["raw"], row["digits"])
        except Exception as e:
            print("读取已有结果失败, 全量重跑:", e)

    todo = [i for i in range(len(questions)) if results[i] is None]
    print(f"需新测/重测: {len(todo)} 题", flush=True)

    import time

    def work(idx):
        types, desc = questions[idx]
        raw = ask(desc)
        digits = re.findall(r"[1-5]", raw)
        return idx, types, desc, raw, digits

    done_total = 0
    with ThreadPoolExecutor(max_workers=1) as pool:  # 串行: glm-4.5-flash 限流严格
        futures = [pool.submit(work, i) for i in todo]
        for f in as_completed(futures):
            idx, types, desc, raw, digits = f.result()
            results[idx] = (types, desc, raw, digits)
            done_total += 1
            if done_total % 10 == 0:
                print(f"...进度 {done_total}/{len(todo)}", flush=True)
            if not raw.startswith("<error"):
                time.sleep(1)  # 限流保护

    summarize(results)
    with open(out, "w") as fp:
        json.dump([{"codes": [str(t) for t in ty], "types": [LABELS[t] for t in ty],
                    "q": q, "raw": r, "digits": d} for ty, q, r, d in results],
                  fp, ensure_ascii=False, indent=1)
    print(f"\n明细已存: {out}")


if __name__ == "__main__":
    main()
