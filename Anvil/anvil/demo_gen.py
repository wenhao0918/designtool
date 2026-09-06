"""演示脚本生成器 — 从任意设计项目自动编排演示(2026-08-27)。

流程:用户选定项目 → 扫 design_log(DB) 按"成功 model_build"切分呈现步
→ 每步取:用户指令原文 + 当轮 STL + 该步 tool 流水(幕后动作素材)
→ LLM 写解说词(讲结果 + 推介 AI 幕后:参数完善/原语选型/国标查询/硬校验)
→ 落 data/demos/{name}.json → 现有放映页直接播放。

POST /api/demo/generate {project_ref, demo_name?}
GET  /api/demo (清单) 已并列出新脚本。
"""

import json
import os

from fastapi import HTTPException
from pydantic import BaseModel

from .deps import DATA_DIR
from . import history_db
from .project.manager import resolve_project_dir
from .demo_api import DEMOS_DIR, _resolve_stl

from fastapi import APIRouter, Depends
from .auth import get_current_user
from .db import User

router = APIRouter(prefix="/api/demo", tags=["demo"])

# 幕后动作提取规则:tool_call 流水 → 推介素材行
def _behind_scenes(rows):
    acts = []
    for r in rows:
        rl = r.get("result_log") or {}
        if r.get("action") == "tool_call":
            ins = r.get("instruction") or ""
            tool = (rl.get("tool") or ins.split()[0] if ins else "?")
            if tool == "query_standard":
                acts.append("自动查询国标条款作为设计依据")
            elif tool == "list_design_primitives":
                acts.append("盘点可用设计原语,选型最匹配的几何构造")
            elif tool == "model_add_part":
                acts.append("增量建模:新零件入列,参数即时校验")
            elif tool == "model_update_part":
                acts.append("按指令修订既有零件参数")
            elif tool == "check_design_compliance":
                acts.append("对照标准做合规检查")
            elif tool == "model_build":
                acts.append("执行布尔运算生成可制造模型")
        elif r.get("action") == "model_build" and r.get("result_log", {}).get("violations"):
            acts.append("硬约束校验拦截了非法几何,驱动自动修正")
    seen, out = set(), []
    for a in acts:
        if a not in seen:
            seen.add(a); out.append(a)
    return out[:5]


class GenReq(BaseModel):
    project_ref: str
    demo_name: str = ""
    title: str = ""


@router.post("/generate")
@router.post("/generate")
def generate_demo(req: GenReq, user: User = Depends(get_current_user)):
    base = os.path.join(DATA_DIR, "projects", user.username)
    pdir, _ = resolve_project_dir(base, req.project_ref)
    if not pdir:
        raise HTTPException(404, "项目不存在: " + req.project_ref)
    pid = req.project_ref

    rows = history_db.get_design_log(pdir)
    # 切步:每个成功 model_build = 一个呈现步;归并其间 user_message/tool 流水
    steps, cur = [], None
    for r in rows:
        a = r.get("action")
        if a == "user_message":
            cur = {"cmd": (r.get("instruction") or "")[:120], "rows": [r]}
        elif a == "model_build" and (r.get("result_log") or {}).get("status") == "ok":
            if cur is None:
                # 译码链轮不写 user_message 行——直接取 model_build 行自带的用户指令原文
                cur = {"cmd": (r.get("instruction") or "(继续设计)")[:120], "rows": []}
            cur["rows"].append(r)
            cur["output_dir"] = r.get("output_dir") or ""
            cur["dltq_seq"] = r.get("dltq_seq")  # 译码轮:step_N 定位(产物平铺在 cad/)
            steps.append(cur); cur = None
        elif cur is not None:
            cur["rows"].append(r)
    if not steps:
        raise HTTPException(422, "该项目没有成功的建模结果,无法编排演示")

    # STL 定位 + 幕后素材
    # 译码链轮(dltq_seq 有值):产物=cad/step_{N}.stl 平铺;chat 链:cad/{step_id}/ 子目录
    for s in steps:
        if s.get("dltq_seq"):
            s["stl"] = _resolve_stl(pid, "step_%d" % s["dltq_seq"])
        else:
            prefix = (s.get("output_dir") or "").split("/")[-1] if s.get("output_dir") else ""
            s["stl"] = _resolve_stl(pid, prefix) if prefix else None
        s["behind"] = _behind_scenes(s["rows"])

    # LLM 写解说词(每步;失败降级模板文案)
    from .llm import chat
    script_steps = []
    for i, s in enumerate(steps):
        narration = _narrate(chat, i + 1, len(steps), s["cmd"], s["behind"], s.get("stl") is not None)
        script_steps.append({
            "cmd": s["cmd"],
            "narration": narration,
            # 存前缀(不带扩展名/子路径):chat链={step_id},译码链=step_N——回放时 _resolve_stl 再定位
            "stl": (s.get("stl") or "").split("/")[0].rsplit(".stl", 1)[0] if s.get("stl") else "",
            "caption": "第 %d 步 · %s" % (i + 1, s["cmd"][:18]),
            "facts": s["behind"][:3] or ["阶段结果独立存档"],
        })
    # 丢没有 STL 的步(放映必须可视)
    script_steps = [x for x in script_steps if x["stl"]]
    if not script_steps:
        raise HTTPException(422, "该项目无可展示的 STL 产物")

    demo = {
        "title": req.title or ("项目演示 · %s" % pid[:8]),
        "subtitle": "Anvil 自动生成 · 迭代式设计过程回放",
        "project_ref": pid,
        "steps": script_steps,
    }
    os.makedirs(DEMOS_DIR, exist_ok=True)
    name = req.demo_name or pid[:12]
    out = os.path.join(DEMOS_DIR, name + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(demo, f, ensure_ascii=False, indent=2)
    return {"ok": True, "demo": name, "steps": len(script_steps), "file": out}


_SYS = ("你是产品演示解说撰稿人。根据设计指令与 AI 幕后动作,写一段 60-90 字的中文解说词,"
        "面向观众推介 AI 设计工具:先讲这一步做出了什么(结果),再自然带出 AI 幕后自动完成的事"
        "(如查国标、选原语、参数校验)。口语化、有感染力、不啰嗦,不要标题不要列表。")


def _narrate(chat, idx, total, cmd, behind, has_stl):
    hint = "；".join(behind) if behind else "常规建模与校验"
    user = "第%d步(共%d步)。设计指令:%s。AI幕后动作:%s。%s" % (
        idx, total, cmd, hint, "本步有新模型产出。" if has_stl else "")
    try:
        r = chat([{"role": "system", "content": _SYS},
                  {"role": "user", "content": user}], temperature=0.6)
        txt = (r.choices[0].message.content or "").strip()
        if 20 <= len(txt) <= 200:
            return txt
    except Exception:
        pass
    # 降级模板
    return "第%d步:%s。AI 在后台%s。每一步结果都独立存档,随时可回溯。" % (
        idx, cmd[:40], "自动" + "、".join(behind[:2]) if behind else "完成了建模与校验")
