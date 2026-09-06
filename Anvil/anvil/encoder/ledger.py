"""dltQ 账本(全需求矩阵 Q)—— 每条指令一个自动递增序号(永不复用)

存储(2026-09-04 起):DB 表 dltq_ledger,每项目一行。
- project_id: projects.id(bigint),主键
- seq: 加法器递增项当前值(整数行号,永不复用;重置不归零、快照重载不回退)
- entries: 全需求矩阵 JSON blob([{seq,dltq,source,echo,executed,result}...])

职责:
- apply(dltq, source): 落账一条 ΔQ,分配序号,返回 (seq, entry)
- get(seq): 查指定序号条目
- all_entries(): 全部条目(= 当前全需求矩阵 Q)
- clear(): 重置——清空 entries(设计结果),seq 保留递增
- archive(): 重置前归档——cad 产物移本地归档目录,返回 Q 快照 blob(由调用方写 design_log.q_snapshot)
"""
import json
import os
import time


def _dir_to_pid(project_dir):
    """项目目录 → projects.id(bigint)。复用 history_db 的 path 反查(单一实现)。"""
    from ..history_db import _pid
    return _pid(project_dir)


class DltQLedger:
    """dltQ 账本:状态全在 DB(dltq_ledger 表),模块无隐式状态。"""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.pid = _dir_to_pid(project_dir)
        self.state = self._load()

    def _load(self):
        from ..db import SessionLocal, DltqLedgerRow
        with SessionLocal() as s:
            row = s.query(DltqLedgerRow).filter_by(project_id=self.pid).first()
            if row:
                return {"entries": json.loads(row.entries or "[]"),
                        "seq": int(row.seq or 0)}
        return {"entries": [], "seq": 0}

    def _save(self):
        from ..db import SessionLocal, DltqLedgerRow
        with SessionLocal() as s:
            row = s.query(DltqLedgerRow).filter_by(project_id=self.pid).first()
            if row is None:
                row = DltqLedgerRow(project_id=self.pid)
                s.add(row)
            row.seq = self.state["seq"]
            row.entries = json.dumps(self.state["entries"], ensure_ascii=False)
            s.commit()

    def apply(self, dltq, source="", echo="", names=None):
        """落账一条 ΔQ。返回 (seq, entry)。

        指令序号由 Primordium(QLedger.next_seq)统一发放(唯一权威,2026-09-06
        用户定)——本账本不自增,防止多处分配错号/复用。首次取号前做历史对齐
        (Primordium 计数器不落后于本账本存量,历史号视为已由其发放)。

        names: 指称索引初始别名集(角色名,如 ["底板"])——指称=整数行号,
        names 是人可读的角色指称锚,供译码 LLM 把"底板"映射到 990,seq。
        """
        from ..qledger import QLedger
        q = QLedger(self.project_dir)
        if q.state.get("seq", 0) < self.state["seq"]:
            q.state["seq"] = self.state["seq"]
            q._save()
        seq = q.next_seq()
        entry = {
            "seq": seq,
            "dltq": [float(x) if isinstance(x, float) else (int(x) if float(x).is_integer() else float(x)) for x in dltq],
            "source": source,
            "echo": echo,
            "names": list(names or []),
            "executed": False,
            "result": None,
        }
        self.state["entries"].append(entry)
        self.state["seq"] = seq
        self._save()
        return seq, entry

    def set_topo(self, seq, topo):
        """心象快照回写(2026-09-07):执行成功后把该组件真实几何摘要
        (bbox/center/volume)存进 entry.topo——Primordium 空间推理的
        单一事实来源;759 求解/谓词验证由此驱动。"""
        for e in self.state["entries"]:
            if e["seq"] == seq:
                e["topo"] = topo
                break
        else:
            return False
        self._save()
        return True

    def topo_map(self):
        """心象视图:{seq: {bbox,center,volume}}(供求解器/谓词验证)。"""
        return {e["seq"]: e.get("topo") for e in self.state["entries"]
                if e.get("topo")}

    def add_alias(self, seq, name):
        """指称索引强化:为 seq 登记别名(去重)。返回是否新增。

        生命周期·锚的生长:LLM 备注中「名称(#N)」括注执行成功后回写——
        用户话术中的指称词随使用固化为该对象的锚,上下文再长也不丢。
        """
        name = (name or "").strip()
        if not name or len(name) > 24:
            return False
        for e in self.state["entries"]:
            if e["seq"] == seq:
                names = e.setdefault("names", [])
                if name in names:
                    return False
                names.append(name)
                self._save()
                return True
        return False

    def mark_executed(self, seq, result):
        """标记某序号已执行,存执行结果"""
        for e in self.state["entries"]:
            if e["seq"] == seq:
                e["executed"] = True
                e["result"] = result
                self._save()
                return True
        return False

    def get(self, seq):
        """查指定序号条目(返回 entry 或 None)"""
        for e in self.state["entries"]:
            if e["seq"] == seq:
                return e
        return None

    def all_entries(self):
        """返回全部条目(= 当前全需求矩阵 Q)"""
        return self.state["entries"]

    def last_seq(self):
        """当前最大序号(加法器递增项当前值)"""
        return self.state["seq"]

    def pop_last(self):
        """撤销最后一条 ΔQ(用户重做)。移除 entry,seq 计数器保留递增
        (撤销的编号作废不再复用);返回被撤条目,账本为空返回 None。"""
        if not self.state["entries"]:
            return None
        entry = self.state["entries"].pop()
        self._save()
        return entry

    def archive(self, cad_dir=None, history_watermark=None):
        """重置前归档:cad 产物(S)移本地归档目录,返回 Q 快照 blob。

        Q 快照(entries+seq+水位)不再落文件,由调用方写入 design_log_rows.q_snapshot,
        可随时重新装载到 Primordium 做回撤/分支(重载时 seq 取 max,不回退)。
        cad 二进制产物移到 <cad_dir>/_archive/<时间戳>_seq<N>/(本地工作区;MinIO 持久化为下一步)。

        Returns:
            快照 dict;账本为空(无设计可存)时返回 None。
        """
        import shutil
        if not self.state["entries"]:
            return None
        ts = time.strftime("%Y%m%d_%H%M%S")
        seq = self.state["seq"]
        moved, archive_rel = [], None
        if cad_dir and os.path.isdir(cad_dir):
            arch_cad = os.path.join(cad_dir, "_archive", "%s_seq%d" % (ts, seq))
            os.makedirs(arch_cad, exist_ok=True)
            for fn in sorted(os.listdir(cad_dir)):
                src = os.path.join(cad_dir, fn)
                if os.path.isfile(src) and fn.lower().endswith((".stl", ".step", ".stp")):
                    shutil.move(src, os.path.join(arch_cad, fn))
                    moved.append(fn)
            archive_rel = os.path.relpath(arch_cad, self.project_dir)
        return {
            "archived_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seq": seq,
            "entries": self.state["entries"],
            "history_watermark": history_watermark,
            "cad_archive": archive_rel,
            "cad_files": moved,
        }

    def clear(self):
        """重置:清空 entries(设计结果/Q 置空),seq 保留继续递增——指称序号永不复用。"""
        self.state["entries"] = []
        # seq 不归零:对象指称 = 整数行号,永不复用(用户规则)
        self._save()
