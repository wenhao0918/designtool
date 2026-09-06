"""POST /api/translate — 译码系统入口

自然语言设计指令 → LLM 译码员（纯数字串）→ dltQ 账本落账 → 收报机 stub 执行 → 中文回显

跟 /api/chat 并行，走纯数字串哲学（Spec_V1）。不污染现有 qledger 符号 JSON 链路。
"""
from fastapi import APIRouter, Depends

import os

from anvil.deps import get_agent
from anvil.db import User
from anvil.auth import get_current_user
from anvil.encoder.ledger import DltQLedger
from anvil.encoder.encoder import translate
from anvil.encoder.echo import dltq_to_echo

router = APIRouter()


@router.post("/api/translate")
async def translate_design(req: dict, user: User = Depends(get_current_user)):
    """译码入口：用户设计指令 → 纯数字矩阵 → 落账 → stub 执行 → 回显

    请求体: {"project": "xxx", "message": "设计一个空心球直径100壁厚10"}
    返回体: {"seq": 1, "dltq": [4,50.0,202,10.0], "echo": "#1: 球(r=50)·抽壳(壁厚=10)", "steps": [...], "raw": "LLM原始返回"}
    """
    project = req.get("project", "default")
    message = req.get("message", "").strip()
    if not message:
        return {"error": "message required"}

    agent = get_agent(project, user.username)
    if not agent:
        return {"error": "project not found"}

    return run_round(agent, message)


def _pos_str(topo):
    """心象位置速记:topo dict → 'x[a,b] y[c,d] z[e,f]'(无 topo 返回空)。"""
    if not topo or not topo.get("bbox"):
        return ""
    b = topo["bbox"]
    return "x[%.1f,%.1f] y[%.1f,%.1f] z[%.1f,%.1f]" % tuple(b[:6])


def run_round(agent, message, enc_result=None, _interfere_retried=False):
    """译码执行核心：落账 → 执行 → 日志/流水 → 结果 dict。

    enc_result: 预译码结果（chat 自动路由传入,避免二次 LLM 调用）；
    None 时自行调 translate()（此时要求矩阵非空）。
    _interfere_retried: 干涉反馈重译已用（防循环,只重试一次）。
    """
    ledger = DltQLedger(agent.project_dir)

    # 跨链迁移（方案A）：chat 链对象(.model_state.json) → 等价 ΔQ 入账。
    # echo 带「(迁移) 名称｜」——名称是角色指称，供 LLM 后续 990,序号 引用。
    # 幂等(按名称续迁)；失败不阻断本轮译码。
    migrated = []
    try:
        from anvil.encoder.migrate import migrate_chat_objects
        migrated = migrate_chat_objects(agent.project_dir, ledger)
    except Exception as e:
        print("[migrate] skip:", e)
    if migrated:
        agent.project.append_log({
            "action": "state_migrate",
            "instruction": "(自动)chat 链对象迁移入账",
            "llm_response": "; ".join(e for _, e in migrated),
            "output_dir": "cad",
            "result_log": {"status": "ok", "migrated": len(migrated)},
        })

    # 已有对象指称索引快照（供 LLM 引用 #1/#2...）
    # names=角色指称锚(迁移自带/括注回写生长)；source=用户原指令——
    # 上下文会丢,索引不丢:指称管理外置于系统数据结构(2026-09-06 用户定)
    # pos=心象位置(entry.topo bbox,2026-09-07)——LLM 写 -1 约束时可引用,
    # 空间算术归内核,索引只给只读事实
    history = [{"seq": e["seq"], "names": "／".join(e.get("names") or []),
                "echo": e.get("echo", ""),
                "source": (e.get("source") or "")[:60],
                "pos": _pos_str(e.get("topo"))} for e in ledger.all_entries()]

    # 1) LLM 译码员：自然语言 → 数字矩阵(ΔQ) + 备注
    user_id = getattr(agent, "user_id", None)
    try:
        from anvil.history_db import get_recent_dialog as _recent_dialog
        _recent = _recent_dialog(agent.project_dir)
    except Exception:
        _recent = None
    if enc_result is None:
        enc_result = translate(message, user_id=user_id, history=history, recent=_recent)
    if not enc_result["ok"]:
        # 修正反馈只进 LLM 重译对话,不进设计者界面(2026-09-06 用户定):
        # 技术细节(校验问题/漂移原因)留服务端日志,用户只见友好文案;
        # 全量留痕写设计日志(action=encode_fail,持久化便于后续优化失败模式)
        _internal = enc_result["error"] or "未知译码失败"
        print("[encode] 译码失败(内部详情):", _internal, "| raw:",
              (enc_result.get("raw") or "")[:200], flush=True)
        if "9999" in _internal or "无法映射" in _internal:
            _user_msg = "指令中有译码器暂不认识的词汇，请换用常见的几何表述（如长方体/圆柱/球/打孔）"
        else:
            _user_msg = "这句指令没能译成有效的设计矩阵，请换种说法，或明确尺寸与位置（如：直径10、高20、中心在底板上）"
        agent.project.append_log({
            "action": "encode_fail",
            "instruction": message,
            "llm_response": _user_msg,
            "output_dir": "",
            "result_log": {
                "status": "encode_fail",
                "internal": _internal,
                "raw": (enc_result.get("raw") or "")[:500],
                "trace": enc_result.get("_trace") or [],
            },
        })
        return {"error": _user_msg, "internal": _internal,
                "raw": enc_result.get("raw", "")}
    result = enc_result
    note = (result.get("note") or "").strip()

    dltq = result["dltq"]

    # 空矩阵拦截:纯回应/漂移残留不落账(空条目会污染指称索引与重放)
    if not dltq:
        return {"error": "译码结果为空矩阵（纯回应，不应进入执行轮）",
                "note": note, "raw": result.get("raw", "")}

    # 清零:9998=重新设计/从头开始 → 先存档(Q快照+S产物)再清设计,日志连续保留
    reset_done = False
    if 9998 in dltq:
        dltq = [x for x in dltq if x != 9998]
        reset_done = True
        seq_before = ledger.last_seq()
        # 归档前记录对话日志水位(行数),供将来重载快照时对齐上下文
        try:
            from anvil.history_db import get_history_rows
            watermark = len(get_history_rows(agent.project_dir))
        except Exception:
            watermark = None
        snapshot = ledger.archive(cad_dir=os.path.join(agent.project_dir, "cad"),
                                  history_watermark=watermark)
        ledger.clear()  # Q 置空(seq 保留递增);S 产物已随 archive 移走
        # 同步清 chat 链 model_state——否则下轮迁移会把 chat 对象重新入账，
        # 违背"重新设计/清空之前所有设计"的用户意图
        try:
            from anvil.model_state import ModelState
            ModelState(agent.project_dir).clear()
        except Exception:
            pass
        # 归档产物:MinIO 当前产物 cad/* → archive/<tag>/ 并清 cad/ 前缀,
        # 补传本地归档目录;保证 MinIO 与本地"旧模型归档、当前置空"一致。失败不阻断
        if snapshot and snapshot.get("cad_archive"):
            try:
                from anvil import minio_store
                tag = os.path.basename(snapshot["cad_archive"])
                minio_store.archive_cad_prefix(
                    ledger.pid, tag,
                    project_dir=agent.project_dir,
                    archive_rel=snapshot["cad_archive"])
            except Exception:
                pass
        # 设计日志追加重置事件;q_snapshot 携带重置前 Q 全需求矩阵快照 blob(可回撤/分支)
        agent.project.append_log({
            "action": "model_clear",
            "instruction": message,
            "llm_response": "重置：清空之前所有设计",
            "output_dir": "",
            "result_log": {"status": "cleared", "seq_before": seq_before,
                           "cad_archive": (snapshot or {}).get("cad_archive")},
            "q_snapshot": snapshot,
        })
        # 纯清零(过滤9998后矩阵空):不落空账、不执行——写对话回应即收尾
        if not dltq:
            agent.history.append("user", {"content": message})
            agent.history.append("assistant", {"content": "已清空之前所有设计（Q 快照与产物已归档，可回溯）。请下一条指令开始新设计。"})
            return {"seq": None, "dltq": [9998], "reset": True,
                    "echo": "已清空之前所有设计", "note": "", "files": [],
                    "exec_ok": True, "exec_error": None, "raw": "",
                    "source": message, "total_entries": 0}

    # 重做:9997=撤销上一步执行,用原矩阵重放(纯 9997 触发;混入其他码时忽略按增量译)
    redo_of = None
    if 9997 in dltq:
        if [x for x in dltq if x != 9997]:
            dltq = [x for x in dltq if x != 9997]
        else:
            last = ledger.pop_last()
            if not last:
                return {"error": "重新执行失败：账本没有可撤销的条目"}
            dltq = last["dltq"]
            redo_of = last["seq"]

    # 防复述：LLM 偶发把历史指令重译一遍（前缀重复），截掉历史部分只留增量
    for e in ledger.all_entries():
        h = e.get("dltq", [])
        if len(dltq) > len(h) and h and all(float(a) == float(b) for a, b in zip(dltq[:len(h)], h)):
            dltq = dltq[len(h):]
            break

    # 指称闸门(一期·存在性):990,N 引用的 N 必须是活条目——
    # 引用不存在/已撤销(9997 弹出/9998 清零)的对象 → 拒绝落账并报警
    _alive = {e["seq"] for e in ledger.all_entries()}
    _bad = sorted({int(dltq[i + 1]) for i in range(len(dltq) - 1)
                   if int(dltq[i]) == 990 and int(dltq[i + 1]) not in _alive})
    if _bad:
        return {"error": "译码报警：引用了不存在的对象 #%s（已撤销或未创建）。请从已有对象指称索引中按名称匹配选取"
                         % "、".join(str(x) for x in _bad),
                "raw": result.get("raw", "")}

    # 1b) 拓扑心象求解(2026-09-07 用户定:空间推理归 Primordium,LLM 不算坐标):
    # -1 未定参数位由心象快照+约束算子(759 贴边/752 对齐/z 贴地)推出实参;
    # 推不出 → 欠约束提问(不落账,设计者补充后重译)
    if any(float(x) == -1 for x in dltq):
        from anvil.encoder.solver import solve_dltq
        dltq, _unres = solve_dltq(dltq, ledger.topo_map())
        if _unres:
            _ask = "【欠约束】" + "；".join(_unres[:3])
            agent.history.append("user", {"content": message})
            agent.history.append("assistant", {"content": _ask})
            return {"echo": "", "note": _ask, "ask": True, "exec_ok": True,
                    "raw": result.get("raw", "")}

    # 2) 回显：数字矩阵 → 中文（供用户确认/纠正）
    seq_preview = ledger.last_seq() + 1
    echo = dltq_to_echo(dltq, seq_preview)
    if redo_of:
        echo = "(重做 Δ#%d) %s" % (redo_of, echo)

    # 3) 落账：分配自动递增序号（永不复用）
    seq = ledger.apply(dltq, source=message, echo=echo)[0]

    # 4) 执行：重放编译 → FreeCAD(CADService 8102) → 产物 STL 落 cad/ → 前端可看
    from anvil.encoder.freeexec import execute_design
    ex = execute_design(ledger, agent.project_dir)

    # 4a) 心象快照回写:执行成功即把该 Δ 真实几何摘要(bbox/center/volume)
    # 存 entry.topo——后续 759 求解/谓词验证/指称索引位置的单一事实来源
    if ex.get("ok") and ex.get("topo", {}).get(seq):
        try:
            ledger.set_topo(seq, ex["topo"][seq])
        except Exception:
            pass

    # 4b) 干涉反馈重译(2026-09-07 用户定)：独立放置的新体元与已有对象重叠
    # → 撤销本条,把执行层 bbox 反馈喂回 translate 重译一版（只试一次;
    # 反馈只进 LLM 对话,设计者不可见——信息分流）
    _ex_err = ex.get("error") or ""
    if (not ex.get("ok") and "INTERFERE" in _ex_err and not _interfere_retried
            and len(ledger.all_entries()) and ledger.all_entries()[-1]["seq"] == seq):
        _fb = next((l for l in _ex_err.splitlines() if "INTERFERE" in l), _ex_err[:300])
        try:
            ledger.pop_last()
        except Exception:
            pass
        enc2 = translate(message, user_id=user_id, history=history, feedback=_fb,
                         recent=_recent)
        if enc2.get("ok") and enc2.get("dltq"):
            print("[interfere] 干涉重译:", _fb[:160], flush=True)
            return run_round(agent, message, enc_result=enc2, _interfere_retried=True)
        # 重译未成:账本已撤,直接友好失败(不再走"已入账"措辞)
        _user_msg = ("这步放置与已有对象重叠了。请明确位置（如：贴边留10毫米间隙），"
                     "或说\"合并/组合\"把两者连成一体")
        agent.project.append_log({
            "action": "encode_fail",
            "instruction": message,
            "llm_response": _user_msg,
            "output_dir": "",
            "result_log": {
                "status": "interfere_retry_failed",
                "internal": _fb,
                "raw": (enc2.get("raw") or "")[:500],
            },
        })
        return {"error": _user_msg, "internal": _fb,
                "raw": enc2.get("raw", "")}

    steps = ex.get("code") and ex  # 简化：执行结果整体作为 steps 载荷

    # files 过滤:history 只显示当前步骤 step_N.stl + assembly.stl,不含历史 step 文件
    # 路径归一:CADService 回传 realpath(挂载点),project_dir 可能是软链形式
    # ——两侧统一 realpath 再求 rel,避免 ../../ 链污染
    _rp = os.path.realpath(agent.project_dir)
    all_files = [os.path.relpath(os.path.realpath(f), _rp) for f in ex.get("files", [])]
    rel_files = [f for f in all_files
                 if f.endswith((f"step_{seq}.stl", f"step_{seq}.step"))
                 or f.endswith(("assembly.stl", "assembly.step"))]

    # 产物持久化到 MinIO({tenant}/p/{pid}/cad/...);本地盘为工作区/缓存,MinIO 为持久库
    # 重置后:上传新产物并把 cad/ 对账为仅当前文件(清掉归档竞态残留的旧 step)
    try:
        from anvil import minio_store
        if ex.get("ok") and rel_files:
            keep = {os.path.basename(r) for r in rel_files} if reset_done else None
            minio_store.upload_async(ledger.pid, agent.project_dir, rel_files,
                                     prune_keep=keep)
        elif reset_done:
            minio_store.sync_cad_prefix(ledger.pid, set())
    except Exception:
        pass

    # 指称索引回写:执行成功后,从 LLM 备注提取「名称(#N)」括注 → 登记为
    # 该对象的指称锚(去重)。用户话术中的指称词随使用固化,上下文再长不丢
    if ex.get("ok") and note:
        import re as _re
        for m in _re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9×\-]{2,12})\s*[（(]#(\d{1,6})[)）]", note):
            _alias, _ref = m.group(1).strip("的在把个于"), int(m.group(2))
            if len(_alias) < 2:
                continue
            # 脏别名过滤:含已有别名的长串(如"基于底板")不登记
            _e = ledger.get(_ref)
            _old = (_e or {}).get("names") or []
            if any(_n and _n in _alias for _n in _old):
                continue
            ledger.add_alias(_ref, _alias)

    # 5) 写设计日志(结构化五要素,design_log_rows;DB 失败直接抛错,不静默)
    # dltq_seq=指令序号 Δ#N(显式列,递增唯一永不复用——每步设计日志必带)
    agent.project.append_log({
        "action": "model_build",
        "dltq_seq": seq,
        "instruction": message,
        "llm_response": echo,
        "output_dir": "cad",
        "result_log": {
            "status": "ok" if ex.get("ok") else "error",
            "files": rel_files,
            "dltq": dltq,
            "seq": seq,
            "redo_of": redo_of,
            "raw": result.get("raw", ""),
            "message": (ex.get("error") or "")[:400],
        },
    })

    # 6) 写对话流水(history_rows;字段名与 /api/chat 对齐:content + files)
    # seq 标注为 dltq_seq:译码账本序号,与 chat 设计日志 seq 是两套体系
    # 执行失败显式标记:sanity/几何错误在对话里可见原因,不再"像没完成"
    content = (echo + ("\n\n" + note if note else "")).strip()
    if not ex.get("ok"):
        _err = (ex.get("error") or "").strip()
        _line = next((l for l in _err.splitlines() if "SANITY" in l or "Error" in l), _err[:160])
        content = "❌ 执行失败（Δ#%d 已入账，可发\"重新执行\"撤销）：%s\n\n%s" % (seq, _line.strip()[:200], content)
    agent.history.append("user", {"content": message, "dltq_seq": seq})
    agent.history.append("assistant", {
        "content": content,
        "dltq": dltq, "dltq_seq": seq,
        "files": rel_files,
    })

    return {
        "seq": seq,
        "dltq": dltq,
        "echo": echo,
        "note": note,
        "steps": steps,
        "files": rel_files,
        "exec_ok": ex.get("ok", False),
        "exec_error": ex.get("error"),
        "raw": result["raw"],
        "source": message,
        "total_entries": len(ledger.all_entries()),
    }


@router.get("/api/translate/ledger/{project}")
async def get_ledger(project: str, user: User = Depends(get_current_user)):
    """查看 dltQ 账本（所有指令+序号+数字矩阵+回显）"""
    agent = get_agent(project, user.username)
    if not agent:
        return {"error": "project not found"}
    ledger = DltQLedger(agent.project_dir)
    return {
        "entries": ledger.all_entries(),
        "last_seq": ledger.last_seq(),
    }
