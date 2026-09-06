"""Design Loop 后端/审阅侧 — 状态表驱动,给原语方案、审阅结果。

角色(用户 2026-08-15 定,注意反复):
- 后端(backend): 处理 Anvil 提交的 gap,以【设计原语】方式给出解决方案,
  调 mark_solution。只动原语层(能力),绝不直接改模型数据。
- 审阅(reviewer): 检查 Anvil 提交的 result;通过 → review_pass;
  发现问题 → review_issue(原语调整建议)给后端,
  后端调原语 → Anvil 重做 → 再审阅,反复直至正确。

本模块是这两个角色的【开发侧工具】(由开发者/我调用),不是 LLM 工具。
"""

from anvil.comm import (
    submit_gap, check_loop, submit_result,
    mark_solution, review_pass, review_issue, run_review_cycle, list_jobs,
)


# === 后端(原语供给) ===

def backend_list_gaps(status=None):
    """列出设计任务(可按状态过滤),开发侧查看待处理的缺口。

    用法:
        for j in backend_list_gaps("pending_gap"):
            # ... 实现/调整设计原语 ...
            mark_solution(j["job_id"], "generate_chamfer", "孔口倒角原语", {...})
    """
    jobs = list_jobs()
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return jobs


def backend_mark_solution(job_id, primitive_name, description, params=None, code_hint=None):
    """后端给出原语方案(调 comm.mark_solution)。"""
    return mark_solution(job_id, primitive_name, description, params, code_hint)


# === 审阅(质量门) ===

def reviewer_list_results(status=None):
    """列出待审阅的设计结果(await_review)。"""
    jobs = list_jobs()
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return jobs


def reviewer_check(job_id, state_summary="", files=None):
    """审阅一轮:规则检查 → pass 或 issue(调 comm.run_review_cycle)。"""
    return run_review_cycle(job_id, state_summary, files)


def reviewer_pass(job_id, note=""):
    return review_pass(job_id, note)


def reviewer_issue(job_id, problems, primitive_adjustment=""):
    return review_issue(job_id, problems, primitive_adjustment)


# 队列/状态查看(开发侧)

def show_loop():
    """打印设计循环全貌(各状态任务数 + 最新若干)。"""
    jobs = list_jobs()
    statuses = {}
    for j in jobs:
        st = j.get("status", "?")
        statuses[st] = statuses.get(st, 0) + 1
    return {"count_by_status": statuses, "total": len(jobs), "recent": jobs[:10]}
