"""
Design Loop 状态表 — Anvil ↔ 后端(原语供给) ↔ 审阅(质量门) 的设计循环。

流程(用户 2026-08-15 定):
1. 用户问题 → Anvil 尝试解决
2. 解决不了 → Anvil submit_gap: 创建设计任务(状态=pending_gap)
3. 后端以设计原语给出方案 → mark_solution: 状态=primitive_ready
4. Anvil check_loop 看到方案 → 用新原语重做 → submit_result: 状态=await_review
5. 审阅检查 → pass: 状态=passed(交付)
            → 发现问题: review_issue: 状态=adjusting(附原语调整建议)
6. 后端调整原语 → mark_solution: 状态=primitive_ready → Anvil 重做 → 审阅(反复直至 passed)

设计取舍(优于消息队列):
- 一个设计任务 = 一条记录 + 状态机流转;不是多消息排队
  (无需 publish/consume/ack,避免异步复杂度——消费者/生产者是同一开发流程)
- 状态流转落盘(JSONL),可审计、可回放,天然支持"反复直至正确"

数据文件: <ANVIL_DATA_DIR>/design_loop/jobs.jsonl
"""

import os
import json
import uuid
from datetime import datetime

LOOP_DIR_NAME = "design_loop"
JOBS_FILE = "jobs.jsonl"

# 状态机
ST_PENDING_GAP = "pending_gap"
ST_PRIMITIVE_READY = "primitive_ready"
ST_AWAIT_REVIEW = "await_review"
ST_ADJUSTING = "adjusting"
ST_PASSED = "passed"
ST_FAILED = "failed"


def _ensure_dir():
    data_dir = os.environ.get("ANVIL_DATA_DIR", "")
    d = os.path.join(data_dir, LOOP_DIR_NAME) if data_dir else LOOP_DIR_NAME
    os.makedirs(d, exist_ok=True)
    return d


def _jobs_path():
    return os.path.join(_ensure_dir(), JOBS_FILE)


def _read_all():
    if not os.path.exists(_jobs_path()):
        return []
    jobs = []
    with open(_jobs_path(), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                jobs.append(json.loads(line))
            except Exception:
                continue
    return jobs


def _write_all(jobs):
    with open(_jobs_path(), "w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")


def _find(job_id):
    jobs = _read_all()
    for j in jobs:
        if j.get("job_id") == job_id:
            return j, jobs
    return None, jobs


def _append_history(job, event, detail=""):
    job.setdefault("history", []).append({"time": datetime.now().isoformat(), "event": event, "detail": detail})


# === Anvil 侧(生产者/消费者) ===

def submit_gap(name, description, priority="P2", params_hint="", usage_scenario="", current_state=""):
    """Anvil 解决不了 → 创建设计任务(缺口)。

    Returns:
        {job_id, status, message}
    """
    job_id = "job_" + uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "status": ST_PENDING_GAP,
        "gap": {
            "name": name,
            "description": description,
            "priority": priority,
            "params_hint": params_hint or "",
            "usage_scenario": usage_scenario or "",
            "current_state": current_state or "",
        },
        "solution": None,
        "result": None,
        "review": None,
        "history": [],
        "created_at": datetime.now().isoformat(),
    }
    _append_history(job, "gap_submitted", name)
    with open(_jobs_path(), "a") as f:
        f.write(json.dumps(job, ensure_ascii=False) + "\n")
    return {
        "job_id": job_id,
        "status": ST_PENDING_GAP,
        "message": "能力缺口已提交(job=%s)。后端将以设计原语给出方案,稍后 check_loop 查看。" % job_id,
    }


def check_loop(job_id=None):
    """Anvil 查看任务状态。"""
    if job_id:
        job, _ = _find(job_id)
        if not job:
            return {"status": "not_found", "message": "任务不存在: " + str(job_id)}
        jobs = [job]
    else:
        jobs = _read_all()
        if not jobs:
            return {"status": "empty", "message": "暂无设计任务"}
        jobs = jobs[-1:]
    job = jobs[0]
    st = job.get("status")
    out = {"job_id": job.get("job_id"), "status": st}
    if st == ST_PENDING_GAP:
        out["message"] = "缺口已提交,等待后端给出原语方案。"
    elif st == ST_PRIMITIVE_READY:
        out["message"] = "后端已给出原语方案,可开始重做。"
        out["solution"] = job.get("solution")
    elif st == ST_AWAIT_REVIEW:
        out["message"] = "结果已提交,等待审阅。"
    elif st == ST_ADJUSTING:
        out["message"] = "审阅发现问题,后端调整原语中。"
        out["review"] = job.get("review")
    elif st == ST_PASSED:
        out["message"] = "审阅通过,设计完成可交付。"
        out["review"] = job.get("review")
        out["solution"] = job.get("solution")
    elif st == ST_FAILED:
        out["message"] = "任务失败。"
    return out


def submit_result(job_id, summary, files=None, state_summary=""):
    """Anvil 用新原语重做完成 → 提交结果,进入待审阅。"""
    job, jobs = _find(job_id)
    if not job:
        return {"status": "error", "message": "任务不存在"}
    job["result"] = {"summary": summary, "files": files or [], "state_summary": state_summary or ""}
    job["status"] = ST_AWAIT_REVIEW
    _append_history(job, "result_submitted", summary[:100])
    _write_all(jobs)
    return {"job_id": job_id, "status": ST_AWAIT_REVIEW, "message": "结果已提交审阅,审阅通过即交付;发现问题会调整原语让你重做。"}


# === 后端侧(原语供给,开发侧调用) ===

def mark_solution(job_id, primitive_name, description, params=None, code_hint=None):
    """后端给出原语方案 → 状态=primitive_ready。"""
    job, jobs = _find(job_id)
    if not job:
        return {"status": "error", "message": "任务不存在"}
    job["solution"] = {
        "primitive_name": primitive_name,
        "description": description,
        "params": params or {},
        "code_hint": code_hint or "",
        "time": datetime.now().isoformat(),
    }
    job["status"] = ST_PRIMITIVE_READY
    _append_history(job, "solution_ready", primitive_name)
    _write_all(jobs)
    return {"job_id": job_id, "status": ST_PRIMITIVE_READY}


# === 审阅侧(质量门,开发侧调用) ===

def review_pass(job_id, note=""):
    """审阅通过 → passed(交付)。"""
    job, jobs = _find(job_id)
    if not job:
        return {"status": "error", "message": "任务不存在"}
    job["review"] = {"verdict": "pass", "note": note or "审阅通过,设计正确,可交付。", "time": datetime.now().isoformat()}
    job["status"] = ST_PASSED
    _append_history(job, "review_pass")
    _write_all(jobs)
    return {"job_id": job_id, "status": ST_PASSED}


def review_issue(job_id, problems, primitive_adjustment=""):
    """审阅发现问题 → 状态=adjusting(后端调整原语 → Anvil 重做,反复)。"""
    job, jobs = _find(job_id)
    if not job:
        return {"status": "error", "message": "任务不存在"}
    job["review"] = {
        "verdict": "issue",
        "problems": problems,
        "primitive_adjustment": primitive_adjustment,
        "time": datetime.now().isoformat(),
    }
    job["status"] = ST_ADJUSTING
    _append_history(job, "review_issue", primitive_adjustment[:100])
    _write_all(jobs)
    return {"job_id": job_id, "status": ST_ADJUSTING, "message": "审阅发现问题,后端调整原语中,调整后 Anvil 重做(反复直至正确)。"}


# === 审阅规则(几何/参数检查,可扩展) ===

def review_result(job_id, state_summary="", files=None):
    """对 Anvil 提交的结果做规则检查(骨架,可扩展更深几何校验)。"""
    problems = []
    if not files:
        problems.append({"desc": "没有产物文件(缺 STEP/STL)"})
    if not state_summary:
        problems.append({"desc": "缺少模型状态摘要,无法确认设计内容"})
    if problems:
        return False, problems, "检查 model_build 是否成功产出文件;检查状态摘要"
    return True, [], ""


def run_review_cycle(job_id, state_summary="", files=None):
    """完整审阅一轮:规则检查 → pass 或 issue。"""
    ok, problems, adj = review_result(job_id, state_summary, files)
    if ok:
        review_pass(job_id)
        return {"status": "pass"}
    review_issue(job_id, problems, adj)
    return {"status": "issue", "problems": problems, "adjustment": adj}


# === 查询 ===

def list_jobs(limit=200):
    jobs = _read_all()
    return list(reversed(jobs[-limit:]))


# 工具定义(挂到 agent.tools)

def tool_submit_gap():
    return {
        "type": "function",
        "function": {
            "name": "submit_gap",
            "description": (
                "遇到现有原语/工具【解决不了】的需求时调用:创建设计任务,把能力缺口抛给后端,"
                "后端会以设计原语方式给出解决方案。绝不硬凑——做不了就提交缺口。"
                "提交后稍后用 check_loop 查看后端方案,拿到新原语后重做。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "缺口名,如 chamfer"},
                    "description": {"type": "string", "description": "为什么解决不了 / 需要什么能力"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2"], "description": "优先级"},
                    "params_hint": {"type": "string", "description": "期望参数"},
                    "usage_scenario": {"type": "string", "description": "使用场景"},
                    "current_state": {"type": "string", "description": "当前模型状态摘要(帮助后端设计原语)"}
                },
                "required": ["name", "description"]
            }
        }
    }


def tool_check_loop():
    return {
        "type": "function",
        "function": {
            "name": "check_loop",
            "description": (
                "查看设计任务进展:后端是否已给原语方案(primitive_ready)、"
                "审阅是否通过(passed)、审阅是否要求调整(adjusting)。"
                "提交缺口/结果后调用它看下一步。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "设计任务ID(不传看最近)"}
                }
            }
        }
    }


def tool_submit_result():
    return {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": (
                "重做完成、模型已生成后,把结果提交给审阅。审阅通过即交付;"
                "审阅发现问题会调整原语,你需要 check_loop 查看并再次重做(反复直至正确)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "设计任务ID(来自 submit_gap 返回值)"},
                    "summary": {"type": "string", "description": "本次设计结果摘要"},
                    "state_summary": {"type": "string", "description": "模型状态摘要"}
                },
                "required": ["job_id", "summary"]
            }
        }
    }


ALL_LOOP_TOOLS = [tool_submit_gap(), tool_check_loop(), tool_submit_result()]

# === 旧 Communication tools(request_tool/check_tool_status,兼容保留) ===

def request_tool(name, description, priority="P2", params_hint="", usage_scenario=""):
    """(旧API)请求新工具——兼容保留,新流程用 submit_gap。"""
    r = submit_gap(name, description, priority, params_hint, usage_scenario)
    return r["job_id"]


def check_tool_status(tool_name=None):
    """(旧API)查看工具实现状态——兼容保留,新流程用 check_loop。"""
    r = check_loop()
    return r


def tool_request_tool():
    return {
        "type": "function",
        "function": {
            "name": "request_tool",
            "description": "向 OpenCode 工程师请求一个新工具。当我需要但还没有的功能时调用这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "工具名，如 update_part"},
                    "description": {"type": "string", "description": "工具应该做什么"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2"], "description": "优先级"},
                    "params_hint": {"type": "string", "description": "期望的参数列表"},
                    "usage_scenario": {"type": "string", "description": "什么场景下使用"}
                },
                "required": ["name", "description"]
            }
        }
    }


def tool_check_tool_status():
    return {
        "type": "function",
        "function": {
            "name": "check_tool_status",
            "description": "查看之前请求的工具是否已实现。OpenCode 实现后会写状态到这里。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "要查询的工具名，不传则看全部"}
                }
            }
        }
    }


ALL_COMM_TOOLS = [tool_request_tool(), tool_check_tool_status()]
