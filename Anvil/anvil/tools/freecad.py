"""FreeCAD tool — execute Python scripts in FreeCAD context via direct lib call."""

import os
import sys
import json
import subprocess
import platform
from datetime import datetime
from pathlib import Path


# Auto-detect FreeCAD library path
def _detect_freecad_lib():
    if platform.system() == "Darwin":
        # macOS: FreeCAD.app
        candidates = [
            "/Applications/FreeCAD.app/Contents/Resources/lib",
        ]
    else:
        candidates = [
            "/usr/lib/freecad-python3/lib",
            "/usr/lib/freecad/lib",
        ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]

FREECAD_LIB = _detect_freecad_lib()
PROJECTS_DIR = os.environ.get("ANVIL_DATA_DIR") and os.path.join(
    os.environ["ANVIL_DATA_DIR"], "projects"
) or os.path.expanduser("~/develop/work/dao_code/DesignTool/Anvil/projects")


class FreeCADTool:
    """Generate 3D models via FreeCAD Python API (no GUI needed)."""

    def __init__(self, project_dir=None):
        self.project_dir = project_dir

    def execute_python(self, code, timeout=120):
        """Execute Python code in FreeCAD context.

        优先走 CADService(8102,常驻免冷启动);不可用/失败时降级本地 subprocess。
        返回契约与本地路径一致:{status, stdout, stderr, files, ...}。

        On macOS: invokes FreeCAD.app's freecadcmd -c directly.
        On Linux: runs via subprocess Python with sys.path tweak.

        Returns dict with status, stdout, stderr, files (list of generated filenames).
        """
        remote = self._execute_via_cadservice(code, timeout=timeout)
        if remote is not None:
            return remote
        return self._execute_local(code, timeout=timeout)

    def _execute_via_cadservice(self, code, timeout=120):
        """CADService HTTP 路径。失败返回 None(降级本地)。"""
        import json as _json
        import urllib.request
        url = os.environ.get("CADSERVICE_URL", "http://127.0.0.1:8102")
        cad_dir = os.path.join(self.project_dir, "cad") if self.project_dir else ""
        body = _json.dumps({"code": code, "work_dir": cad_dir,
                            "timeout": timeout}).encode()
        req = urllib.request.Request(url + "/api/cad/execute", data=body,
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout + 30) as r:
                d = _json.loads(r.read().decode())
        except Exception:
            return None  # 服务不可用 → 降级
        if not d.get("ok"):
            return {"status": "error",
                    "stdout": d.get("stdout", ""),
                    "stderr": d.get("stderr", d.get("error", "CADService error")),
                    "files": [], "returncode": 1}
        # 复用本地结果归集逻辑:扫 stdout/cad_dir 产物
        return self._collect_result(code, d.get("stdout", ""),
                                    d.get("stderr", ""),
                                    0, d.get("files", []))

    def _execute_local(self, code, timeout=120):
        cad_dir = None
        if self.project_dir:
            cad_dir = os.path.join(self.project_dir, "cad")
            os.makedirs(cad_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _temp_file = None

        if platform.system() == "Darwin" and os.path.exists("/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"):
            freecad_bin = "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd"
            # macOS FreeCAD 1.1.1: Part.export([shape], path) broken for STEP
            # Patch: replace Part.export with working per-shape export
            # 多 shape 用 makeCompound 合一一次写出——逐 shape 循环写同一路径
            # 会后者覆盖前者(只剩最后一个 shape),与 freeexec 导出语义对齐
            export_dir = cad_dir if cad_dir else "/tmp"
            export_patch = (
                "import os, Part\n"
                f"_cad_dir = '{export_dir}'\n"
                "os.makedirs(_cad_dir, exist_ok=True)\n"
                "_orig_export = Part.export\n"
                "def _patched_export(shapes, path):\n"
                "    path = str(path)\n"
                "    _ok = [s for s in (shapes if isinstance(shapes, list) else [shapes])\n"
                "           if hasattr(s, 'Volume') and s.Volume > 0]\n"
                "    if not _ok:\n"
                "        return\n"
                "    _one = _ok[0] if len(_ok) == 1 else Part.makeCompound(_ok)\n"
                "    if path.endswith('.step') or path.endswith('.stp'):\n"
                "        _one.exportStep(path)\n"
                "        print('EXPORTED:' + path)\n"
                "    elif path.endswith('.stl'):\n"
                "        _one.exportStl(path)\n"
                "        print('STL_EXPORTED:' + path)\n"
                "    else:\n"
                "        _orig_export(_ok, path)\n"
                "Part.export = _patched_export\n"
                "# ---- user code follows ----\n"
            )
            wrapper = export_patch + code + "\n"
            import tempfile
            tf = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir='/tmp')
            tf.write(wrapper)
            tf.close()
            _temp_file = tf.name
            cmd = [freecad_bin, _temp_file]
        else:
            # Linux: use sys.executable + sys.path tweak
            wrapper = (
                "import sys\n"
                'sys.path.insert(0, "' + FREECAD_LIB + '")\n'
                "import FreeCAD\n"
                "import Part\n"
                "\n"
                + code + "\n"
            )
            cmd = [sys.executable, "-c", wrapper]

        # Snapshot files in cad_dir before execution
        before = set()
        if cad_dir and os.path.isdir(cad_dir):
            for fn in os.listdir(cad_dir):
                if fn.endswith(('.step', '.stl')):
                    before.add(fn)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=timeout,
                env={**os.environ},
            )
            # Clean up temp file for macOS
            if _temp_file:
                try: os.unlink(_temp_file)
                except: pass
            return self._collect_result(code, result.stdout, result.stderr,
                                        result.returncode, before=before,
                                        cad_dir=cad_dir)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "FreeCAD execution timed out (>" + str(timeout) + "s)"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _collect_result(self, code, stdout, stderr, returncode,
                        new_files=None, before=None, cad_dir=None):
        """结果归集(CADService 与本地执行路径共用)。

        1. stdout EXPORTED:/STL_EXPORTED: 标记
        2. code+stdout+stderr 中 .step/.stl 路径扫描(LLM 任意路径写)
        3. cad_dir 快照差集兜底
        产物统一拷入 cad_dir,返回契约:{status, stdout, stderr, files}。
        """
        before = before if before is not None else set()
        cad_dir = cad_dir or (os.path.join(self.project_dir, "cad")
                              if self.project_dir else None)

        found = {}  # basename -> full path

        # 1. stdout 导出标记
        for line in stdout.split("\n"):
            line = line.strip()
            for prefix in ("EXPORTED:", "STL_EXPORTED:"):
                if line.startswith(prefix):
                    p = line[len(prefix):].strip()
                    if os.path.exists(p):
                        found[os.path.basename(p)] = p

        # 2. 任意路径扫描
        import re
        combined = code + "\n" + stdout + "\n" + stderr
        path_re = re.compile(r'["\'\s]?(/[^\s,\'\")\]]+\.(?:step|stl))', re.IGNORECASE)
        for m in path_re.finditer(combined):
            p = m.group(1)
            if os.path.exists(p):
                found[os.path.basename(p)] = p

        # 3. cad_dir 快照差集
        if cad_dir and os.path.isdir(cad_dir):
            for fn in os.listdir(cad_dir):
                if fn.endswith(('.step', '.stl')) and fn not in before:
                    fp = os.path.join(cad_dir, fn)
                    if fn not in found:
                        found[fn] = fp

        files = []
        if cad_dir:
            import shutil
            os.makedirs(cad_dir, exist_ok=True)
            cad_dir_real = os.path.realpath(cad_dir)
            for basename, src in found.items():
                src_real = os.path.realpath(src)
                if src_real.startswith(cad_dir_real + os.sep):
                    files.append(src_real)
                else:
                    dst = os.path.join(cad_dir, basename)
                    if src_real != os.path.realpath(dst):
                        shutil.copy2(src, dst)
                    files.append(dst)
        else:
            files = list(found.values())

        # 静默失败检测
        status = "ok" if returncode == 0 else "error"
        if status == "ok" and not files:
            status = "error"
        if status == "ok" and "Exception" in stderr:
            status = "error"

        return {
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "files": files,
            "returncode": returncode,
        }


    def check_connection(self):
        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, '" + FREECAD_LIB + "'); "
                 "import FreeCAD; print(FreeCAD.Version()[0])"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return {"status": "ok", "version": result.stdout.strip()}
            return {"status": "error", "message": result.stderr}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_tool_definition(self):
        return {
            "type": "function",
            "function": {
                "name": "freecad_execute",
                "description": "在 FreeCAD 中执行 Python 代码生成 3D 模型。STEP/STL 自动导出到项目 cad/ 目录。\n\n"
                              "CRITICAL RULES:\n"
                              "1. 用 Part.makeXxx() API，禁止 doc.addObject('Part::Box'...)\n"
                              "2. 多组件设计用 App::Part 容器组装：\n"
                              "   assy = doc.addObject('App::Part','Assembly')\n"
                              "   assy.Label = '装配体名称'\n"
                              "   o1 = doc.addObject('Part::Feature','Part1'); o1.Shape = shape1; assy.addObject(o1)\n"
                              "   o2 = doc.addObject('Part::Feature','Part2'); o2.Shape = shape2; assy.addObject(o2)\n"
                              "   最后用 Import.export(doc.Objects, step_path) 导出装配体\n"
                              "3. 底座挖凹球面：base = box.cut(Part.makeSphere(r))\n"
                              "4. 导出时系统自动为每个组件生成独立 STEP+STL，也生成合并 STL 供 3D 预览",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "FreeCAD Python 代码。示例（空心球+底座装配体）：\n"
                                          "outer=Part.makeSphere(50); inner=Part.makeSphere(40); sphere=outer.cut(inner).cut(Part.makeCylinder(10,100,FreeCAD.Vector(0,0,-50)))\n"
                                          "box=Part.makeBox(60,60,30,FreeCAD.Vector(-30,-30,-70)); base=box.cut(Part.makeSphere(50))\n"
                                          "assy=doc.addObject('App::Part','Assembly'); assy.Label='空心球体装配'\n"
                                          "o1=doc.addObject('Part::Feature','Sphere'); o1.Shape=sphere; o1.Label='空心球体_通孔20'; assy.addObject(o1)\n"
                                          "o2=doc.addObject('Part::Feature','Base'); o2.Shape=base; o2.Label='底座_凹球面'; assy.addObject(o2)\n"
                                          "doc.recompute(); Import.export(doc.Objects,'/path/cad/assembly.step')"
                        }
                    },
                    "required": ["code"]
                }
            }
        }
