"""跨链状态迁移（方案 A·迁移入账）— chat 链对象 → dltQ 账本

chat 链(.model_state.json parts)对象按类型映射表转等价 ΔQ 矩阵入账，
顺延分配 Δ#N。echo 以「(迁移) 名称｜」开头——名称是角色/功能指称，
不是形状描述（用户 2026-09-06）；译码 LLM 据此把"底板"等名称映射到 990,序号。

坐标换算：chat 链 pos 语义 → 参数表 v2 体心参数（第 4-6 位）
- plate/shell_box/u_channel/wedge_box: pos=底面角点(makeBox at pos) → 体心=pos+(L/2,W/2,H/2)
- cylinder: pos=底面中心 → 体心=pos+(0,0,h/2)
- sphere: pos=球心 → 体心=pos
- side_hole: pos=孔轴线中心 → 刀具圆柱体心=pos；用布尔减(101)表达——
  207 打孔只支持目标中心位孔，任意位置孔走 刀具圆柱+减（圆柱全参数含方位位）

幂等：按名称续迁——已迁移条目(echo 前缀"(迁移) 名称｜")跳过该零件；
部分失败下轮自动补迁，不重复入账。9998 清零由调用方同步清 model_state，
防止清零后 chat 对象复活。
"""
import json
import os

MIGRATE_SRC = "(迁移)"


def _migrated_names(entries):
    """账本中已迁移的零件名集合（echo 前缀解析）。"""
    names = {}
    for e in entries:
        echo = e.get("echo", "")
        if e.get("source") == MIGRATE_SRC and echo.startswith(MIGRATE_SRC):
            body = echo[len(MIGRATE_SRC):].lstrip()
            name = body.split("｜", 1)[0].strip()
            if name:
                names[name] = e["seq"]
    return names


def _num(q, key, default):
    try:
        return float(q.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def part_to_dltq(p, name_seq):
    """单个 part → (dltq, approx_note)；不可迁移返回 None。

    矩阵按参数表 v2（体元全参数=尺寸+体心+方位,缺省 0 占位）。
    name_seq: {零件名: 已迁移序号}（side_hole 的 base 名称 → 990 引用）。
    """
    t = p.get("type")
    q = p.get("params", {})
    pos = list(q.get("pos") or [0, 0, 0])[:3]
    pos = [float(pos[i]) if i < len(pos) and pos[i] is not None else 0.0 for i in range(3)]

    def _r(v):
        return round(float(v), 6)

    if t in ("plate", "box"):
        L = _num(q, "L", 10); W = _num(q, "W", 10)
        H = _num(q, "H", _num(q, "t", 10))
        return ([1, L, W, H, _r(pos[0] + L / 2), _r(pos[1] + W / 2), _r(pos[2] + H / 2), 0, 0], "")

    if t == "shell_box":
        L = _num(q, "L", 10); W = _num(q, "W", 10); H = _num(q, "H", 10)
        tt = _num(q, "t", 0)
        d = [1, L, W, H, _r(pos[0] + L / 2), _r(pos[1] + W / 2), _r(pos[2] + H / 2), 0, 0]
        approx = ""
        if tt > 0:
            d += [202, tt]
            approx = "抽壳近似，开口方向未区分"
        return d, approx

    if t == "cylinder":
        r = _num(q, "r", 5); h = _num(q, "h", 10)
        return ([2, r, h, _r(pos[0]), _r(pos[1]), _r(pos[2] + h / 2), 0, 0], "")

    if t == "sphere":
        r = _num(q, "r", 5)
        return ([4, r, _r(pos[0]), _r(pos[1]), _r(pos[2])], "")

    if t == "side_hole":
        base = q.get("base") or ""
        base_seq = name_seq.get(base)
        if not base_seq:
            return None  # 基体未入账（group/外建/未迁移）→ 跳过该孔
        r = _num(q, "radius", 1) or 1.0
        depth = q.get("depth")
        if q.get("through") or not depth:
            # 贯通：深度给足（depth+1 余量；depth 缺省给 20 覆盖常见板厚）
            h = (_num(q, "depth", 20) if depth else 20.0) + 1.0
        else:
            h = _num(q, "depth", 10)
        # 孔轴向(chat 链 axis_dir) → 方位参数位(倾角,转角);z 向缺省 0,0
        axis = str(q.get("axis_dir", "z")).lower()
        tilt, azim = (90, 0) if axis == "x" else ((90, 90) if axis == "y" else (0, 0))
        d = [2, r, h, _r(pos[0]), _r(pos[1]), _r(pos[2]), tilt, azim,
             101, 990, base_seq, 991]
        return d, ""

    if t in ("wedge_box", "u_channel", "u_channel_bellows"):
        L = _num(q, "L", 10); W = _num(q, "W", 10); H = _num(q, "H", 10)
        return ([1, L, W, H, _r(pos[0] + L / 2), _r(pos[1] + W / 2), _r(pos[2] + H / 2), 0, 0],
                "近似为长方体（原类型 %s）" % t)

    return None  # group/hinge/extruded_profile 等未知类型：跳过


def migrate_chat_objects(project_dir, ledger):
    """读 .model_state.json parts → 等价 ΔQ 入账（幂等，按名称续迁）。

    返回本轮迁入的 [(seq, echo)]；无 chat 对象/已全迁/全不可映射 → []。
    """
    ms_path = os.path.join(project_dir, ".model_state.json")
    if not os.path.exists(ms_path):
        return []
    try:
        with open(ms_path) as f:
            parts = json.load(f).get("parts") or []
    except Exception:
        return []
    parts = [p for p in parts if p.get("type") != "group" and p.get("params")]
    if not parts:
        return []

    done = _migrated_names(ledger.all_entries())  # {name: seq} 既有迁移
    migrated = []
    from anvil.encoder.echo import dltq_to_echo
    for p in parts:
        name = (p.get("params") or {}).get("name", "")
        if not name or name in done:
            continue
        r = part_to_dltq(p, done)
        if not r:
            continue
        dltq, approx = r
        echo = "%s %s｜%s%s" % (MIGRATE_SRC, name, dltq_to_echo(dltq, None),
                                ("（%s）" % approx) if approx else "")
        seq, _entry = ledger.apply(dltq, source=MIGRATE_SRC, echo=echo, names=[name])
        done[name] = seq  # 后续 side_hole 的 base 可引用
        migrated.append((seq, echo))
    return migrated
