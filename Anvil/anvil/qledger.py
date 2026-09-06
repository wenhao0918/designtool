"""Primordium V0.1 — Q 账本 + ΔQ 加法器 + 回显 + Q→建模适配（简化纵切面）。

设计依据：《需求矩阵Q定义_V0.md》《语义数值映射定义_V0.md》
- Q 活账本：项目目录 .q_ledger.json（entries + 版本链 + 快照）
- ΔQ 加法器：唯一写入通道，增/删/改三型；校验（词表/必填/引用）不过不落账（422 式报错带 op 序号+字段）
- 回显：落账后生成结构化中文摘要
- Q→建模：把 inst/param/feat 编译为 ModelState 的 parts（复用既有 model_build→8103→8102）
- V0.1 词表（FreeCAD-8 中旧管线可执行子集）：sphere/cylinder/plate + feat:shell + op:subtract/fuse
"""
import json
import os
import re
import time

# ---------- 词表（数值面单一来源的 V0.1 子集） ----------
KINDS = {
    "sphere":   {"params": {"r": True}},
    "cylinder": {"params": {"r": True, "h": True}},
    "plate":    {"params": {"L": True, "W": True, "t": True}},
}
FEATS = {"shell": {"t": True}}           # 空心 = 基体 + 同形内腔 subtract
NUM_KEYS = ("r", "h", "L", "W", "t")

TOOL_Q_APPLY = {
    "type": "function",
    "function": {
        "name": "q_apply",
        "description": "把一条设计指令翻译为 ΔQ 并落账到需求矩阵 Q（唯一写入通道）。"
                       "每个 op 三型之一：add(新增条目)/update(改字段)/remove(删条目)。"
                       "family: inst=体的存在(kind,name) / param=数值(挂 ref) / feat=变形(op 挂 base)。"
                       "空心球=sphere + feat shell(t)。禁止编造词表外 kind/op/参数键。",
        "parameters": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "update", "remove"]},
                            "family": {"type": "string", "enum": ["inst", "param", "feat"]},
                            "name": {"type": "string", "description": "inst 的体名；param/feat 引用名填 ref"},
                            "kind": {"type": "string", "enum": sorted(KINDS)},
                            "params": {"type": "object", "description": "数值键值（词表内）。直径给 d（加法器自动换 r=d/2），也可直接给 r"},
                            "op_feat": {"type": "string", "enum": sorted(FEATS), "description": "feat 的 op 名"},
                        },
                        "required": ["op", "family"],
                    },
                },
                "source": {"type": "string", "description": "指令原文（溯源用）"},
            },
            "required": ["ops"],
        },
    },
}


def _num(x):
    try:
        return round(float(x), 3)
    except Exception:
        return None


def fmt_cell(c):
    """唯一显示格式: Θ[42,p/r]=50"""
    return "%s[%d,%s]=%s" % (c["mat"], c["row"], c["col"], c["val"])


def fmt_cells(cells):
    return " ".join(fmt_cell(c) for c in cells)


class QLedger:
    """Q 账本：唯一权威 + 版本链 + 快照。状态全在文件，内核（本模块函数）只带逻辑。"""

    def __init__(self, project_dir):
        self.dir = project_dir
        self.path = os.path.join(project_dir, ".q_ledger.json")
        self.snap_dir = os.path.join(project_dir, "q_snapshots")
        self.state = self._load()

    # ---- 存储 ----
    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path))
            except Exception:
                pass
        return {"entries": [], "version": 0, "seq": 0, "retired": [], "log": []}

    def _save(self):
        tmp = self.path + ".tmp"
        json.dump(self.state, open(tmp, "w"), ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- 查询 ----
    def find(self, name, family=None):
        for e in self.state["entries"]:
            if e["value"].get("name") == name and (family is None or e["family"] == family):
                return e
        return None

    # ---- 指令序号发放(唯一权威,2026-09-06 用户定) ----
    def next_seq(self):
        """对外发号:dltQ 数字链等外部账本的指令序号(Δ#N)一律从此取,
        禁止自行递增——防止多处分配导致错号/复用。号=单调整数,永不复用。"""
        self.state["seq"] = self.state.get("seq", 0) + 1
        self._save()
        return self.state["seq"]

    # ---- ΔQ 加法器：唯一写入通道 ----
    def apply(self, ops, source=""):
        """ops: LLM 翻译出的 ΔQ。返回 (ok, echo_or_errors, applied_count)。"""
        errs, plan = [], []
        pending_add, pending_del = set(), set()

        def exists(name):
            return (self.find(name, "inst") or name in pending_add) and name not in pending_del

        for i, op in enumerate(ops):
            kind = op.get("op")
            family = op.get("family")
            if kind not in ("add", "update", "remove"):
                errs.append(f"op[{i}] op 非法: {kind}（增/删/改）")
                continue
            if family not in ("inst", "param", "feat"):
                errs.append(f"op[{i}] family 非法: {family}")
                continue
            name = op.get("name") or ""
            if family == "inst":
                e = self._check_inst(i, kind, op, name, errs, exists)
                if e:
                    plan.append(e)
                    if e["_act"] == "add":
                        pending_add.add(name)
                    elif e["_act"] == "remove":
                        pending_del.add(name)
                        pending_add.discard(name)
            elif family == "param":
                e = self._check_param(i, kind, op, name, errs, exists)
                if e:
                    plan.append(e)
            else:
                e = self._check_feat(i, kind, op, name, errs, exists)
                if e:
                    plan.append(e)
        if errs:
            return False, {"status": "invalid", "errors": errs,
                           "message": "ΔQ 未落账——修正词汇/参数后重新提交"}, 0
        cells = []
        for e in plan:
            rid = None
            self._commit(e, source)
            # 落账后按指称取行, 生成稀疏单元格（ΔQ 本体=矩阵增量）
            if e["family"] == "inst":
                rid = self.find(e["value"]["name"], "inst")["id"]
            elif e["family"] == "feat":
                for x in self.state["entries"]:
                    if x["family"] == "feat" and x["value"].get("name") == e["value"].get("name") and x["value"].get("op") == e["value"].get("op"):
                        rid = x["id"]
            if rid is not None:
                cells += self.sparse_cells(dict(e, id=rid))
        self._last_cells = cells
        self.state["version"] += 1
        self.state["log"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  "version": self.state["version"],
                                  "source": source[:200], "ops": len(plan),
                                  "cells": self._last_cells})
        self._save()
        return True, {"echo": self.echo(), "cells": self._last_cells}, len(plan)

    def _commit(self, e, source):
        act, tgt = e["_act"], e.get("_target_id")
        e.pop("_act", None)
        e.pop("_target_id", None)
        if act == "add":
            self.state["seq"] = self.state.get("seq", 0) + 1   # 指称=单调整数(矩阵行号), 永不复用
            e["id"] = self.state["seq"]                        # "q-N" 仅为显示格式, 存储与计算一律用数
            e["attrs"] = {"authority": "strong", "status": "active",
                          "confirmed": False, "source": source[:60] or "inst"}
            self.state["entries"].append(e)
        elif act == "upsert":
            self.state["entries"] = [x for x in self.state["entries"] if x.get("id") != tgt]
            e["attrs"] = {"authority": "strong", "status": "active", "confirmed": False,
                          "source": source[:60] or "inst"}
            self.state["entries"].append(e)
        elif act == "update":
            for old in self.state["entries"]:
                if old["id"] == tgt:
                    old["value"] = e["value"]
                    old["attrs"]["source"] = source[:60] or old["attrs"].get("source", "")
                    old["attrs"]["status"] = "active"
                    break
        else:  # remove
            dead = [x for x in self.state["entries"] if x["id"] == tgt]
            self.state["entries"] = [x for x in self.state["entries"] if x["id"] != tgt]
            for d in dead:  # 要素消失, 指称退役(记录在案, 永不复用)
                self.state.setdefault("retired", []).append(
                    {"id": d["id"], "family": d["family"], "name": d["value"].get("name"),
                     "retired_at_version": self.state["version"]})

    # ---- 校验器（词表/必填/引用；错误带 op 序号+字段） ----
    def _check_inst(self, i, kind, op, name, errs, exists):
        if kind == "remove":
            if not exists(name):
                errs.append(f"op[{i}] remove: 体「{name}」不存在")
                return None
            e = self.find(name, "inst")
            return {"family": "inst", "value": {"name": name}, "_act": "remove", "_target_id": e["id"]}
        if not name:
            errs.append(f"op[{i}] inst 缺 name")
            return None
        k = op.get("kind")
        if k not in KINDS:
            errs.append(f"op[{i}] kind「{k}」不在词表（{sorted(KINDS)}）")
            return None
        value = {"name": name, "kind": k}
        src = dict(op.get("params") or {})
        if "d" in src and "r" not in src:   # 符号→数: 直径换算, 加法器唯一除法点(同映射定义 §3.1)
            dv = _num(src.pop("d"))
            src["r"] = round(dv / 2, 3) if dv else None
        for pk, pv in src.items():
            if pk not in KINDS[k]["params"]:
                errs.append(f"op[{i}] {k} 不接受参数「{pk}」（词表：{sorted(KINDS[k]['params'])}）")
                return None
            v = _num(pv)
            if v is None or v <= 0:
                errs.append(f"op[{i}] {k}.{pk} 必须为正数，得到 {pv}")
                return None
            value[pk] = v
        for pk, req in KINDS[k]["params"].items():
            if req and pk not in value:
                errs.append(f"op[{i}] {k} 缺必填参数 {pk}")
                return None
        if kind == "add" and exists(name):
            errs.append(f"op[{i}] 体「{name}」已存在（改用 update）")
            return None
        if kind == "update":
            e = self.find(name, "inst") or ({"value": {"kind": op.get("kind"), "name": name}} if exists(name) else None)
            if not e:
                errs.append(f"op[{i}] update: 体「{name}」不存在")
                return None
            value.update({kk: vv for kk, vv in e["value"].items() if kk not in value and kk != "name"})
            return {"family": "inst", "value": value, "_act": "update", "_target_id": e["id"]}
        return {"family": "inst", "value": value, "_act": "add"}

    def _check_param(self, i, kind, op, name, errs, exists):
        ref = name
        tgt = self.find(ref, "inst")
        if not tgt and exists(ref):
            tgt = {"value": {"kind": "sphere", "name": ref}}  # 批内新增体的参数检查按词表在 _check_inst 已做
        if not tgt:
            errs.append(f"op[{i}] param 引用的体「{ref}」不存在")
            return None
        params = {k: _num(v) for k, v in (op.get("params") or {}).items()}
        params = {k: v for k, v in params.items() if v is not None}
        if kind == "remove" or not params:
            errs.append(f"op[{i}] param 需要至少一个数值键（{NUM_KEYS}）")
            return None
        for k in params:
            if k not in KINDS[tgt["value"]["kind"]]["params"]:
                errs.append(f"op[{i}] 体「{ref}」({tgt['value']['kind']}) 不接受参数「{k}」")
                return None
        value = dict(tgt["value"])
        value.update(params)
        return {"family": "param", "refs": [ref], "value": {"name": ref, "kind": tgt["value"]["kind"], **value},
                "_act": "update", "_target_id": tgt["id"]}

    def _check_feat(self, i, kind, op, name, errs, exists):
        ref = name
        tgt = self.find(ref, "inst")
        if not tgt and exists(ref):
            tgt = {"value": {"kind": op.get("base_kind", "sphere"), "name": ref}}
        if not tgt:
            errs.append(f"op[{i}] feat 引用的体「{ref}」不存在")
            return None
        opf = op.get("op_feat")
        if opf not in FEATS:
            errs.append(f"op[{i}] feat op「{opf}」不在词表（{sorted(FEATS)}）")
            return None
        params = {k: _num(v) for k, v in (op.get("params") or {}).items()}
        params = {k: v for k, v in params.items() if v is not None and k in FEATS[opf]}
        if kind == "remove":
            for e in self.state["entries"]:
                if e["family"] == "feat" and e["value"].get("op") == opf and e["refs"] == [ref]:
                    return {"family": "feat", "id": e["id"], "refs": [ref],
                            "value": {"op": opf, "name": ref}, "_act": "remove", "_target_id": e["id"]}
            errs.append(f"op[{i}] remove: feat {opf} 于「{ref}」不存在")
            return None
        if not params:
            errs.append(f"op[{i}] feat {opf} 缺参数（{sorted(FEATS[opf])}）")
            return None
        for e in self.state["entries"]:   # 存活同型 feat → 原指称 update（id 不变）
            if e["family"] == "feat" and e["value"].get("op") == opf and e["refs"] == [ref]:
                return {"family": "feat", "refs": [ref], "id": e["id"],
                        "value": {"op": opf, "name": ref, **params}, "_act": "update", "_target_id": e["id"]}
        return {"family": "feat", "refs": [ref], "value": {"op": opf, "name": ref, **params},
                "_act": "add"}                           # 新指称由 seq 发放

    # ---- 稀疏矩阵单元格（记法规范唯一实现，规范见 语义数值映射定义 §7.5） ----
    def sparse_cells(self, entry):
        """数据形式: {"row":int指称, "mat":"I|Θ|F|T", "col":规范列名, "val":数}
        列名规范: I→kind/<kind>  Θ→p/<key>  F→op/<op>  T→op/<op>/<param>
        显示形式(仅展示层): Θ[42,p/r]=50，由 fmt_cell 生成，禁止另造记法。"""
        v = entry["value"]
        cells = []
        if entry["family"] == "inst":
            k = v.get("kind")
            cells.append({"row": entry["id"], "mat": "I", "col": "kind/%s" % k, "val": 1})
            for pk in KINDS.get(k, {}).get("params", {}):
                if pk in v:
                    cells.append({"row": entry["id"], "mat": "Θ", "col": "p/%s" % pk, "val": v[pk]})
        elif entry["family"] == "feat":
            opf = v.get("op")
            cells.append({"row": entry["id"], "mat": "F", "col": "op/%s" % opf, "val": 1})
            for pk, pv in v.items():
                if pk not in ("op", "name"):
                    cells.append({"row": entry["id"], "mat": "T", "col": "op/%s/%s" % (opf, pk), "val": pv})
        return cells


    # ---- 回显 ----
    def echo(self):
        lines = ["本次 Q 状态："]
        for e in self.state["entries"]:
            v = e["value"]
            if e["family"] == "inst":
                ps = {k: v[k] for k in KINDS.get(v.get("kind"), {}).get("params", {}) if k in v}
                lines.append("  + %s %s %s" % (v.get("kind"), v.get("name"), ps))
            elif e["family"] == "feat":
                lines.append("  + %s(%s) 于 %s" % (v.get("op"), {k: val for k, val in v.items() if k not in ("op", "name")}, v.get("name")))
        lines.append("  版本 v%d" % self.state["version"])
        return "\n".join(lines)

    def _find_part(self, model_state, name):
        for p in model_state.state.get("parts", []):
            if p.get("params", {}).get("name") == name:
                return p
        return None

    # ---- 快照/加载 ----
    def snapshot(self, tag=None):
        os.makedirs(self.snap_dir, exist_ok=True)
        tag = tag or ("v%d" % self.state["version"])
        path = os.path.join(self.snap_dir, "%s_%s.json" % (time.strftime("%Y%m%d_%H%M%S"), tag))
        json.dump(self.state, open(path, "w"), ensure_ascii=False, indent=1)
        return path

    def load_snapshot(self, path):
        """整体置换：读回快照后仍经 _save 落账（唯一通道原则不变）。"""
        st = json.load(open(path))
        self.state = st
        self._save()
        return True


# ---------- Q → ModelState 编译（简化 Ω：V0.1 词表子集） ----------
def q_to_parts(ledger):
    """把 Q 编译为 legacy parts 列表（sphere/cylinder/plate + shell=subtract 内腔）。"""
    parts, feats = [], []
    for e in ledger.state["entries"]:
        v = e["value"]
        if e["family"] == "inst":
            k = v["kind"]
            params = {k2: v[k2] for k2 in KINDS[k]["params"] if k2 in v}
            params["name"] = v["name"]
            parts.append({"type": k, "params": params})
        elif e["family"] == "feat" and v.get("op") == "shell":
            feats.append(v)
    for f in feats:  # 空心：外体 + 内腔 subtract
        base = f["name"]
        t = f["t"]
        tgt = ledger.find(base, "inst")
        if not tgt:
            continue
        k = tgt["value"]["kind"]
        inner_name = "%s_inner" % base
        if k == "sphere":
            parts.append({"type": "sphere", "params": {"name": inner_name, "r": max(0.5, tgt["value"]["r"] - t)}})
            parts.append({"type": "subtract", "params": {"name": "%s_hollow" % base, "base": base, "tools": [inner_name]}})
        elif k == "cylinder":
            parts.append({"type": "cylinder", "params": {"name": inner_name, "r": max(0.5, tgt["value"]["r"] - t), "h": tgt["value"]["h"] + 2}})
            parts.append({"type": "subtract", "params": {"name": "%s_hollow" % base, "base": base, "tools": [inner_name]}})
        # plate 壳 V0.2
    return parts


def sync_to_model_state(ledger, model_state):
    """Q → ModelState 全量对账：parts 与 Q 保持一致（幂等）。"""
    want = {p["params"]["name"]: p for p in q_to_parts(ledger)}
    have = {p.get("params", {}).get("name"): p for p in model_state.state.get("parts", [])}
    for name in have:
        if name not in want and not name.endswith("_inner"):
            model_state.remove_part(name)
    for name, p in want.items():
        if name in have:
            model_state.update_part(name, p["params"])
        else:
            model_state.add_part(p["type"], dict(p["params"]))
    return len(want)


# ============================================================
# 内核序列（简化实现，过程序列严格按 Primordium 框架）
#   Σ 阶段检查 → ΔQ 加法器 → Π 编译 → Δ 调度 → Ω 执行 → 判定 → S 落账
#   每步计算可以简单，但序列必须按框架；全程 trace 可追溯
# ============================================================
STAGES = ["S0", "S1", "S2", "S3", "S4"]
PRECISION = {"S0": "粗", "S1": "粗", "S2": "中", "S3": "严格", "S4": "定型"}


class Kernel:
    """一次设计会话的内核序列。状态(阶段/Q/S)全在本对象与账本文件——模块函数无隐式状态。"""

    def __init__(self, project_dir, model_state=None):
        self.ledger = QLedger(project_dir)
        self.model_state = model_state
        self.stage = self.ledger.state.get("stage", "S0")
        self.trace = []

    def _log(self, step, detail):
        self.trace.append("[%-9s] %s" % (step, detail))

    # ---- Σ：阶段与精度档（阶段=精度档位的管控机制） ----
    def sigma(self):
        self._log("Σ 阶段", "%s（精度档：%s）" % (self.stage, PRECISION[self.stage]))
        return self.stage

    def sigma_to(self, stage):
        assert stage in STAGES
        self._log("Σ 转移", "%s → %s" % (self.stage, stage))
        self.stage = stage

    # ---- ΔQ 加法器：唯一写入通道 ----
    def apply_dq(self, ops, source=""):
        self.sigma()
        ok, res, n = self.ledger.apply(ops, source)
        if ok:
            cell_str = fmt_cells(res["cells"])
            self._log("ΔQ 加法器", "落账 %d 条 → 稀疏增量: %s" % (n, cell_str))
        else:
            self._log("ΔQ 加法器", "拒绝: %s" % res.get("errors"))
        if ok and self.stage == "S0":
            self.sigma_to("S1")   # 首次落账 → 概念求解
        elif ok and self.stage in ("S2", "S3", "S4"):
            self.sigma_to("S1")   # S_edit 增量修改 → 回概念求解（Q 微分）
        return ok, res

    # ---- Π：编译 Q → 任务 DAG（V0.1：每 inst 一条 task_csg，feat 依赖其后） ----
    def pi_compile(self):
        tasks, feats = [], []
        for e in self.ledger.state["entries"]:
            v = e["value"]
            if e["family"] == "inst":
                tasks.append({"id": "csg:%s" % v["name"], "kind": "task_csg",
                              "ref": v["name"], "params": {k: v[k] for k in KINDS.get(v["kind"], {}).get("params", {}) if k in v},
                              "target": "CPU", "precision": PRECISION[self.stage], "deps": []})
            elif e["family"] == "feat" and v.get("op") == "shell":
                feats.append(v)
        for f in feats:  # feat 依赖其 base（算子依赖）
            tasks.append({"id": "feat:shell:%s" % f["name"], "kind": "task_shell",
                          "ref": f["name"], "params": {"t": f["t"]},
                          "target": "CPU", "precision": PRECISION[self.stage], "deps": ["csg:%s" % f["name"]]})
        self.tasks = tasks
        self._log("Π 编译", "%d 个任务（异构标注 %s）" % (
            len(tasks), {t: sum(1 for x in tasks if x["target"] == t) for t in ("CPU", "NPU")}))
        return tasks

    # ---- Δ：按依赖序调度（V0.1：拓扑序串行，失败只许重执行） ----
    def delta_run(self):
        done, results = set(), []
        pending = list(self.tasks)
        while pending:
            runnable = [t for t in pending if all(d in done for d in t["deps"])]
            if not runnable:
                raise RuntimeError("DAG 死锁: %s" % [t["id"] for t in pending])
            for t in runnable:
                out = self.omega_execute(t)
                results.append((t["id"], out))
                done.add(t["id"])
                self._log("Δ 调度", "%s → Ω 执行 %s" % (t["id"], "ok"))
            pending = [t for t in pending if t["id"] not in done]
        return results

    # ---- Ω：执行原语（V0.1 三个原语，绑 legacy ModelState） ----
    def omega_execute(self, task):
        assert self.model_state is not None, "Ω 需要绑定 ModelState（几何载体）"
        name, k = task["ref"], task["kind"]
        if k == "task_csg":
            e = self.ledger.find(name, "inst")
            kind = e["value"]["kind"]
            params = {kk: e["value"][kk] for kk in KINDS[kind]["params"] if kk in e["value"]}
            have = self.ledger._find_part(self.model_state, name)
            if have:
                self.model_state.update_part(name, params)
            else:
                self.model_state.add_part(kind, {"name": name, **params})
            return {"part": name}
        if k == "task_shell":
            t = task["params"]["t"]
            e = self.ledger.find(name, "inst")
            inner = "%s_inner" % name
            r_in = max(0.5, e["value"]["r"] - t)
            if e["value"]["kind"] == "sphere":
                ip = {"name": inner, "r": r_in}
            else:
                ip = {"name": inner, "r": r_in, "h": e["value"].get("h", 10) + 2}
            if self.ledger._find_part(self.model_state, inner):
                self.model_state.update_part(inner, ip)
            else:
                self.model_state.add_part(e["value"]["kind"], ip)
            hollow = "%s_hollow" % name
            if not self.ledger._find_part(self.model_state, hollow):
                self.model_state.add_part("subtract", {"name": hollow, "base": name, "tools": [inner]})
            return {"part": hollow}
        raise RuntimeError("Ω 无此原语: %s" % k)

    # ---- 判定（V0.1：词表/正数已在加法器前哨，此处占位硬律检查） ----
    def verify(self):
        verdict = "PASS"
        self._log("判定", verdict + "（V0.1 占位：硬律/𝒞ₘ 检查 V0.2 接入）")
        return verdict

    # ---- S 落账 ----
    def commit_s(self, files=None):
        self.ledger.state["stage"] = self.stage
        self.ledger.state["s"] = {"stage": self.stage, "files": files or [], "verdict": "PASS",
                                  "parts": [t["id"] for t in getattr(self, "tasks", [])]}
        self.ledger._save()
        self._log("S 落账", "阶段=%s 版本=v%d" % (self.stage, self.ledger.state["version"]))

    def deliver(self, build=True):
        """设计定型：终验 → S4 → 交付解（交付解仅在 S4）"""
        verdict = self.verify()
        if verdict != "PASS":
            return {"status": "violation", "verdict": verdict}
        self.sigma_to("S4")
        files = self.model_state.build().get("files", []) if (build and self.model_state) else []
        self.commit_s(files)
        self._log("交付", "设计定型（S4）: %s" % files)
        return {"status": "ok", "files": files}

    # ---- 完整一拍：ΔQ 落账 → 编译 → 调度执行 → 判定 → S ----
    def run_instruction(self, ops, source="", build=False):
        ok, res = self.apply_dq(ops, source)
        if not ok:
            return {"status": "invalid", **res, "trace": self.trace}
        if self.stage in ("S0", "S1"):
            self.sigma_to("S2")          # 概念求解→建模执行
        self.pi_compile()
        self.delta_run()
        verdict = self.verify()
        if self.stage == "S2" and verdict == "PASS":
            self.sigma_to("S3")
        files = None
        if build and self.model_state is not None:
            out = self.model_state.build()
            files = out.get("files", [])
        self.commit_s(files)
        return {"status": "ok", "verdict": verdict, "echo": self.ledger.echo(), "trace": list(self.trace)}
