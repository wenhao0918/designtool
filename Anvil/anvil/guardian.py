"""Guardian(监护者)——看着 Anvil 做事,记录对错,针对性修正。

原则(用户 2026-08-15 定):
- Anvil 在后台做的事必须有跟踪:做对了什么、做错了什么、碰到了什么问题;
- 必须有'监护者'看着,并针对性响应;
- 响应不是替它完成,而是修正它,让它能完成 —— 自我进化。

职责:
1. 分析设计日志,识别错误模式(几何自校验报错 / build 失败 / 悬空刀具 / 缺原语)
2. 对每个错误生成'修正建议'(改进点:提示词/工具描述/校验/新原语)
3. 记录闭环:错误 → 建议 → 落实状态 → 同类错误是否复发

数据:
- 输入:项目的 .design/log(JSONL 全链路)
- 输出:data/guardian.jsonl(监护记录,集中存放,admin 可查)
"""

import os
import json
import re
from datetime import datetime

GUARDIAN_FILE = "guardian.jsonl"

# 错误模式识别规则:日志文本 → (模式名, 严重度, 修正方向)
ERROR_PATTERNS = [
    {
        "name": "悬空刀具",
        "match": ["不相交", "交集体积", "布尔减法无效"],
        "severity": "high",
        "fix": "刀具必须穿过基体材料。已在 model_add_part 描述中强调;若复发,"
               "需在提示词中再加示例(球体开孔刀具中心应在球内),或增强几何自校验提示。",
    },
    {
        "name": "方向错误",
        "match": ["cylinder", "方向", "axis"],
        "severity": "medium",
        "fix": "cylinder 只能沿 Z 轴;非 Z 方向孔必须用 side_hole。已在工具描述中明确;若复发,"
               "考虑给 model_add_part 加'开孔方向'参数校验。",
    },
    {
        "name": "原语缺失",
        "match": ["暂无", "无法表达", "不支持", "无直接"],
        "severity": "medium",
        "fix": "能力缺口:应走 request_tool 提交 capability_gaps,由开发侧实现新原语。",
    },
    {
        "name": "build失败",
        "match": ["status.*error", "失败", "traceback"],
        "severity": "high",
        "fix": "build 失败需定位根因(FreeCAD 错误/几何非法/超时),检查 execute_python 的 stderr。",
    },
    {
        "name": "硬凑",
        "match": ["假装", "硬凑", "近似代替", "先这样"],
        "severity": "high",
        "fix": "违反'禁止硬凑'原则:必须暴露能力缺口,不许用错误原语假装完成。",
    },
]


def _session():
    try:
        from anvil.db import SessionLocal
        return SessionLocal()
    except Exception:
        return None


def analyze_project_log(project_dir: str, project_ref: str = "") -> dict:
    """分析一个项目的设计日志,识别错误模式,返回监护记录。"""
    log_path = os.path.join(project_dir, ".design", "log")
    if not os.path.exists(log_path):
        return {"ok": False, "reason": "no log"}
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    # 收集最后 200 条,搜索错误模式
    issues = []
    for e in entries[-200:]:
        text = json.dumps(e, ensure_ascii=False)
        for pat in ERROR_PATTERNS:
            if any(m in text for m in pat["match"]):
                # 避免重复:同一模式只记一次(取最近)
                if not any(i["pattern"] == pat["name"] for i in issues):
                    issues.append({
                        "pattern": pat["name"],
                        "severity": pat["severity"],
                        "fix": pat["fix"],
                        "evidence": (e.get("instruction") or e.get("llm_response") or text)[:120],
                        "time": e.get("time", ""),
                    })
    return {"ok": True, "project": project_ref or os.path.basename(project_dir), "issues": issues}


def _default_data_dir(project_dir: str) -> str:
    """数据目录:ANVIL_DATA_DIR 优先;否则从项目路径向上推导。
    项目路径形如 <data>/projects/<user>/<proj>,向上 3 级是 <data>。
    """
    env = os.environ.get("ANVIL_DATA_DIR")
    if env:
        return env
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(project_dir))))


def record_guardian(project_dir: str, project_ref: str = "") -> dict:
    """分析并写监护记录(带状态跟踪:open → resolved)。

    每次会话都写一条评估记录:有问题记问题(open),没问题记'正常'。
    这样'做对了什么/做错了什么'都有跟踪。
    """
    result = analyze_project_log(project_dir, project_ref)
    if not result.get("ok"):
        return result
    data_dir = _default_data_dir(project_dir)
    os.makedirs(data_dir, exist_ok=True)
    guard_path = os.path.join(data_dir, GUARDIAN_FILE)
    recorded = 0
    if not result["issues"]:
        # 正常会话:记录健康状态(供'做对了什么'的跟踪)
        rec = {
            "time": datetime.now().isoformat(),
            "project": result["project"],
            "pattern": "normal",
            "severity": "info",
            "fix": "",
            "evidence": "本轮会话未检测到已知错误模式",
            "status": "ok",
            "occurrences": 0,
        }
        with open(guard_path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {"ok": True, "project": result["project"], "issues": [], "recorded": 0, "status": "ok"}
    for iss in result["issues"]:
        rec = {
            "time": datetime.now().isoformat(),
            "project": result["project"],
            "pattern": iss["pattern"],
            "severity": iss["severity"],
            "fix": iss["fix"],
            "evidence": iss["evidence"],
            "status": "open",  # open → resolved(开发侧修正后标记)
            "occurrences": 1,
        }
        with open(guard_path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        recorded += 1
    return {"ok": True, "project": result["project"], "issues": result["issues"], "recorded": recorded}


def list_guardian(data_dir: str = None) -> list:
    """列出监护记录(按时间倒序)。"""
    data_dir = data_dir or os.environ.get("ANVIL_DATA_DIR", "")
    guard_path = os.path.join(data_dir, GUARDIAN_FILE) if data_dir else GUARDIAN_FILE
    if not os.path.exists(guard_path):
        return []
    recs = []
    for line in open(guard_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(recs))
