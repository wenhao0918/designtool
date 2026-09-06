"""CAD 执行层:FreeCAD 脚本执行 + STEP/STL 导出(收编 Anvil FreeCADTool 成熟逻辑)。

FreeCAD 路线统一执行层(2026-08-26 定稿,build123d 路线终止):
- Linux: python + sys.path 补 freecad-python3/lib(remote-server)
- macOS: FreeCAD.app freecadcmd(含 Part.export patch)
- 服务常驻 → Anvil 经 HTTP 调用,免去每次冷启动
"""

import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime

_CANDIDATES = ("/usr/lib/freecad-python3/lib", "/usr/lib/freecad/lib")


def _detect_freecad_lib():
    for c in _CANDIDATES:
        if os.path.isdir(c):
            return c
    return ""


FREECAD_LIB = _detect_freecad_lib()
MAC_FREECADCMD = "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"


def has_freecad():
    if platform.system() == "Darwin":
        return os.path.exists(MAC_FREECADCMD)
    return bool(FREECAD_LIB) or bool(
        os.environ.get("PYTHONPATH", "")) is not None and _try_import()


def _try_import():
    try:
        # 本进程已可 import(服务以 PYTHONPATH 启动时)
        import FreeCAD  # noqa: F401
        return True
    except Exception:
        return False


def execute(code, work_dir=None, timeout=120):
    """执行 FreeCAD Python 代码。

    work_dir: 输出目录(STEP/STL 落盘处);None → /tmp。
    返回 {ok, stdout, stderr, files(执行后 work_dir 新增文件), elapsed}。
    """
    if work_dir:
        os.makedirs(work_dir, exist_ok=True)
    else:
        work_dir = "/tmp"

    before = set(os.listdir(work_dir)) if os.path.isdir(work_dir) else set()
    t0 = datetime.now()

    if platform.system() == "Darwin" and os.path.exists(MAC_FREECADCMD):
        # macOS FreeCAD 1.1.1: Part.export STEP 坏,patch 之(与 Anvil 同款)
        export_patch = (
            "import os, Part\n"
            "_d = %r\n" % work_dir +
            "os.makedirs(_d, exist_ok=True)\n"
            "_orig = Part.export\n"
            "def _p(shapes, path):\n"
            "    path = str(path)\n"
            "    for s in (shapes if isinstance(shapes, list) else [shapes]):\n"
            "        if not hasattr(s, 'Volume') or s.Volume <= 0:\n"
            "            continue\n"
            "        if path.endswith(('.step', '.stp')):\n"
            "            s.exportStep(path); print('EXPORTED:' + path)\n"
            "        elif path.endswith('.stl'):\n"
            "            s.exportStl(path); print('STL_EXPORTED:' + path)\n"
            "        else:\n"
            "            _orig([s], path)\n"
            "Part.export = _p\n"
            "# ---- user code ----\n"
        )
        wrapper = export_patch + code + "\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                         delete=False, dir="/tmp") as tf:
            tf.write(wrapper)
            temp = tf.name
        cmd = [MAC_FREECADCMD, temp]
    else:
        wrapper = (
            "import sys\n"
            'sys.path.insert(0, "%s")\n' % (FREECAD_LIB or "/usr/lib/freecad-python3/lib") +
            "import FreeCAD\nimport Part\n\n" + code + "\n"
        )
        cmd = [sys.executable, "-c", wrapper]
        temp = None

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout,
                           env={**os.environ,
                                "QT_QPA_PLATFORM": "offscreen"})
        stdout, stderr, rc = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout(%ds)" % timeout,
                "files": [], "elapsed": (datetime.now() - t0).total_seconds()}
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)

    files = sorted(set(os.listdir(work_dir)) - before) if os.path.isdir(work_dir) else []
    return {
        "ok": rc == 0,
        "stdout": stdout[-4000:],
        "stderr": stderr[-2000:],
        "files": files,
        "elapsed": round((datetime.now() - t0).total_seconds(), 2),
    }
