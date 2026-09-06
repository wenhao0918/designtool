"""TraceHook — 把 Anvil 的设计决策接入 TraceTool 溯源链。

分层职责：
- 用户消息（低频、语义）→ trace source add（S-NNN）
- 模型落地产物（model_build / freecad_execute 成功）→ trace refinery add（R-NNN）
- 高频工具调用审计留在 .design/log，不进溯源链

设计约束：
- 溯源是附加保障层，TraceTool 调用失败只告警，绝不阻断设计流程；
- 通过 subprocess 调用 trace.py CLI（解耦，不 import TraceTool 模块）；
- 强制 --no-git：Anvil 项目目录在上级 git repo 内，禁止自动 commit 污染主仓库。
"""

import os
import subprocess
import sys
from pathlib import Path

# TraceTool CLI 路径：优先环境变量，默认 DesignTool 标准布局（../.. 相对本文件）
TRACE_PY = os.environ.get(
    "TRACE_TOOL_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "TraceTool", "trace.py"),
)


class TraceClient:
    """程序化调用 TraceTool CLI 的薄封装。"""

    def __init__(self, project_dir):
        self.project_dir = str(project_dir)
        self._initialized = False

    # ── internal ────────────────────────────────────────────────

    def _run(self, *args, timeout=30):
        return subprocess.run(
            [sys.executable, TRACE_PY, *args],
            capture_output=True, text=True, timeout=timeout,
        )

    def ensure_init(self):
        """首次使用时在项目目录初始化溯源项目（.PROJECT.md + .sources/ + .refineries/）。"""
        if (Path(self.project_dir) / ".sources").is_dir():
            self._initialized = True
            return
        try:
            r = self._run("init", self.project_dir)
            if r.returncode == 0:
                self._initialized = True
            else:
                print("[TraceTool] init failed: " + (r.stderr or "").strip()[:200])
        except Exception as e:
            print("[TraceTool] init failed: %s" % e)

    # ── public ──────────────────────────────────────────────────

    def add_source(self, title, content):
        """归档一条用户消息为 Source。返回 S-NNN 编号，失败返回 None。"""
        if not self._initialized:
            return None
        try:
            r = self._run(
                "-d", self.project_dir, "--no-git", "-q",
                "source", "add", "-t", title, "-c", content,
                "--participants", "用户 + Anvil",
                "--type", "anvil-session",
            )
            if r.returncode == 0 and r.stdout.strip():
                return Path(r.stdout.strip()).stem
        except Exception as e:
            print("[TraceTool] source add failed: %s" % e)
        return None

    def add_refinery(self, title, sources, output, content):
        """提炼一条设计产出。返回 R-NNN 编号，失败返回 None。"""
        if not self._initialized:
            return None
        if not sources:
            print("[TraceTool] refinery skipped: no source id")
            return None
        try:
            cmd = ["-d", self.project_dir, "--no-git", "-q",
                   "refinery", "add", "-t", title, "-s", sources, "-c", content]
            if output:
                cmd += ["-o", output]
            r = self._run(*cmd)
            if r.returncode == 0 and r.stdout.strip():
                return Path(r.stdout.strip()).stem
        except Exception as e:
            print("[TraceTool] refinery add failed: %s" % e)
        return None
