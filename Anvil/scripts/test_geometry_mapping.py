"""几何体→数字映射 LLM 测试。

约定: 1=球, 2=空心球, 3=正方体, 4=长方体, 5=圆柱体
20 个自然语言描述(每类 4 题: 直称/特征/类比混出), 让 LLM 只回数字, 统计正确率。

用法: cd Anvil && python3 scripts/test_geometry_mapping.py
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 载入 .env(start.sh 同款逻辑, 脚本独立运行也能拿到 key)
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT))

from anvil.llm import chat  # noqa: E402

LABELS = {"1": "球", "2": "空心球", "3": "正方体", "4": "长方体", "5": "圆柱体"}

# 20 题: (期望数字, 设计指令) —— 每类 4 题, 用户真实下单风格(带尺寸参数)
QUESTIONS = [
    # 球(1)
    (1, "设计一个球，直径100mm。"),
    (1, "设计一个实心球，半径50。"),
    (1, "来一个钢球，D=60。"),
    (1, "画一个球体，球径80毫米。"),
    # 空心球(2)
    (2, "设计一个空心球，直径100mm。"),
    (2, "设计一个空心球，外径100，壁厚5。"),
    (2, "做一个中空球体，外径80。"),
    (2, "设计一个薄壁球壳，外径120，壁厚3。"),
    # 正方体(3)
    (3, "设计一个正方体，边长50mm。"),
    (3, "设计一个立方体，50X50X50。"),
    (3, "做一个边长为80的正方体块。"),
    (3, "来一个正方块，三边都是60。"),
    # 长方体(4)
    (4, "设计一个长方体，尺寸：10X20X50。"),
    (4, "设计一个长方体，长100宽50高30。"),
    (4, "做一个矩形块，120X60X15。"),
    (4, "来一块方料，L=200,W=100,H=40。"),
    # 圆柱体(5)
    (5, "设计一个圆柱体，直径50，高100。"),
    (5, "设计一个圆柱，D40xH80。"),
    (5, "做一个圆柱形轴段，半径20，长度60。"),
    (5, "来一根圆棒料，直径25，长度200。"),
]

SYSTEM = (
    "你是一个几何体分类器。数字约定：1=球，2=空心球，3=正方体，4=长方体，5=圆柱体。"
    "用户会给出一段几何体描述，你只需输出一个数字(1-5)，禁止输出任何其他文字。"
)


def ask(desc: str) -> str:
    resp = chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": desc}],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def main() -> None:
    results = []  # (expect, got, ok, raw)
    for i, (expect, desc) in enumerate(QUESTIONS, 1):
        raw = ask(desc)
        m = re.search(r"[1-5]", raw)
        got = m.group(0) if m else "?"
        results.append((expect, got, got == str(expect), raw))
        mark = "✓" if got == str(expect) else "✗"
        print(f"[{i:02d}] {mark} 期望={expect}({LABELS[str(expect)]})  实际={got}  原始输出={raw!r}")
        print(f"     题目: {desc}")

    total = len(results)
    correct = sum(1 for r in results if r[2])
    print("\n=== 汇总 ===")
    print(f"总正确率: {correct}/{total} = {correct / total:.0%}")
    for n, name in LABELS.items():
        sub = [r for r in results if str(r[0]) == n]
        ok = sum(1 for r in sub if r[2])
        print(f"  {n}={name}: {ok}/{len(sub)}")
    confusions = [(LABELS[str(e)], LABELS.get(g, "?")) for e, g, ok, _ in results if not ok]
    if confusions:
        print("混淆对(期望→误判):", confusions)


if __name__ == "__main__":
    main()
