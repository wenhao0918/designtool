"""
Model state manager — persistent parts/joints storage.

Replaces the all-in-one build_model with incremental CRUD operations.
Model state is persisted as .model_state.json in the project directory.
"""

import os
import json
import copy
from datetime import datetime
from .tools import primitives
from .tools.freecad import FreeCADTool


class ModelState:
    """Manages persistent model state with incremental operations."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.path = os.path.join(project_dir, ".model_state.json")
        self.state = self._load()
        # 来源追踪:声明本次写入来源(合法=agent 的 model_* 工具链);
        # 未声明来源的写入(如外部直接改文件)会在审计中被标记为 EXTERNAL。
        self._write_source = None

    def set_write_source(self, source: str):
        """声明本次状态写入的来源(合法:agent 的 model_* 工具链)。"""
        self._write_source = source

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    state = json.load(f)
                state = self._migrate(state)
                return state
            except Exception:
                pass
        return {"parts": [], "joints": [], "created_at": None, "updated_at": None, "schema_version": "1.0", "build_counter": 0}

    def _migrate(self, state):
        """Migrate state from older schema versions."""
        ver = state.get("schema_version", "0.9")
        if ver == "0.9":
            state["schema_version"] = "1.0"
        # Ensure build_counter exists (added in schema 1.0)
        if "build_counter" not in state:
            state["build_counter"] = 0
        return state

    def _save(self):
        self.state["schema_version"] = "1.0"
        self.state["updated_at"] = datetime.now().isoformat()
        # 原子写:先写临时文件再 rename,防止多进程/异常中断导致文件截断损坏
        # (损坏的 .model_state.json 会被 _load 静默丢弃 → model_get_state 返回空 → LLM 误以为无模型)
        import tempfile
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        # 审计:记录每次状态写入的来源(区分 LLM 工具链 vs 外部直接改)
        self._audit_write()

    def _audit_write(self):
        """写审计记录到 data/state_writes.jsonl(集中审计,独立于项目目录)。"""
        try:
            data_dir = os.environ.get("ANVIL_DATA_DIR") or os.path.join(
                os.path.dirname(os.path.dirname(self.project_dir)), "data"
            )
            os.makedirs(data_dir, exist_ok=True)
            audit_path = os.path.join(data_dir, "state_writes.jsonl")
            rec = {
                "time": datetime.now().isoformat(),
                "project": os.path.basename(self.project_dir),
                "source": self._write_source or "EXTERNAL(未声明来源)",
                "parts": len(self.state.get("parts", [])),
            }
            with open(audit_path, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_state(self):
        """Return current model state (parts + joints)."""
        return copy.deepcopy(self.state)

    def get_tree(self):
        raw = copy.deepcopy(self.state.get("parts", []))
        root = []
        lookup = {}
        for p in raw:
            name = p.get("params", {}).get("name", "")
            if name:
                lookup[name] = p
            p["_children"] = []
        for p in raw:
            pn = p.get("parent")
            if pn and pn in lookup:
                lookup[pn]["_children"].append(p)
            else:
                root.append(p)
        def _build(nodes):
            result = []
            for n in nodes:
                item = {"name": n.get("params", {}).get("name", "?"), "type": n["type"]}
                if n["type"] != "group":
                    item["params"] = n.get("params", {})
                kids = n.pop("_children", [])
                if kids:
                    item["children"] = _build(kids)
                result.append(item)
            return result
        return _build(root)



    def set_dependency(self, part_name, depends_on):
        """Record that part_name depends on depends_on for build order."""
        for p in self.state["parts"]:
            if p.get("params", {}).get("name") == part_name:
                current = p.get("depends_on", [])
                if depends_on not in current:
                    current.append(depends_on)
                    p["depends_on"] = current
                self._save()
                return True
        return False
    def add_group(self, name, parent=None):
        parts = self.state["parts"]
        existing = {p.get("params", {}).get("name") for p in parts if p.get("params")}
        if name in existing:
            base = name
            i = 2
            while name in existing:
                name = "%s_%d" % (base, i)
                i += 1
        entry = {"type": "group", "params": {"name": name}}
        if parent:
            entry["parent"] = parent
        parts.append(entry)
        self._save()
        return name

    def add_part(self, part_type, params):
        """Add a new part.

        Args:
            part_type: primitive type (e.g. "shell_box")
            params: dict of parameters for the primitive

        Returns:
            part name
        """
        parent = params.pop("parent", None)
        parts = self.state["parts"]
        name = params.get("name", "part_%d" % (len(parts) + 1))
        # Auto-dedup name
        existing = {p.get("params", {}).get("name") for p in parts}
        if name in existing:
            base = name
            i = 2
            while name in existing:
                name = "%s_%d" % (base, i)
                i += 1
            params["name"] = name
        entry = {"type": part_type, "params": dict(params), "depends_on": []}
        if parent:
            entry["parent"] = parent
        parts.append(entry)
        self._save()
        return name

    def update_part(self, name, updates):
        """Update parameters of an existing part.

        Args:
            name: part name to update
            updates: dict of parameter updates (only specified keys change)

        Returns:
            True if found, False otherwise
        """
        for part in self.state["parts"]:
            if part.get("params", {}).get("name") == name:
                part["params"].update(updates)
                self._save()
                return True
        return False

    def remove_part(self, name):
        """Remove a part by name."""
        before = len(self.state["parts"])
        self.state["parts"] = [p for p in self.state["parts"]
                               if p.get("params", {}).get("name") != name]
        if len(self.state["parts"]) < before:
            self._save()
            return True
        return False

    def add_joint(self, joint_type, params):
        """Add a new joint."""
        parts = self.state["joints"]
        name = params.get("name", "joint_%d" % (len(parts) + 1))
        parts.append({"type": joint_type, "params": dict(params)})
        self._save()
        return name

    def update_joint(self, name, updates):
        """Update parameters of an existing joint."""
        for joint in self.state["joints"]:
            if joint.get("params", {}).get("name") == name:
                joint["params"].update(updates)
                self._save()
                return True
        return False

    def remove_joint(self, name):
        """Remove a joint by name."""
        before = len(self.state["joints"])
        self.state["joints"] = [j for j in self.state["joints"]
                                if j.get("params", {}).get("name") != name]
        if len(self.state["joints"]) < before:
            self._save()
            return True
        return False

    def _next_build_version(self):
        """Scan cad/ for build subdirectories, return next version number.

        File system is the source of truth for version numbering.
        Scans both old flat files (design_v*.step) and new subdirs.
        """
        import re
        cad_dir = os.path.join(self.project_dir, "cad")
        if not os.path.isdir(cad_dir):
            return 1
        max_v = 0
        # New format: cad/{step_uuid}/ subdirectories containing *.step
        for entry in os.listdir(cad_dir):
            entry_path = os.path.join(cad_dir, entry)
            if os.path.isdir(entry_path):
                has_step = any(f.endswith('.step') for f in os.listdir(entry_path))
                if has_step:
                    max_v += 1
            else:
                m = re.match(r'design_v(\d+)\.step', entry)
                if m:
                    v = int(m.group(1))
                    if v > max_v:
                        max_v = v
        return max_v + 1

    def _build_via_primitive_service(self, parts, joints, step_dir):
        """PrimitiveService(8103)路径:validate(硬律)→compose(代码+
        CADService 执行)。失败/不可用返回 None(降级本地链路)。

        硬律违规返回 error result(不降级——几何必然错误,交给 LLM 修正)。
        """
        import urllib.request
        url = os.environ.get("PRIMITIVESERVICE_URL",
                             "http://127.0.0.1:8103") + "/api/primitives/compose"
        body = json.dumps({"parts": parts, "joints": joints,
                           "work_dir": step_dir, "timeout": 180}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=210) as r:
                out = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode()).get("detail", {})
            except Exception:
                detail = {}
            if isinstance(detail, dict) and detail.get("violations"):
                # 硬约束违规:如实回给 LLM(附违规清单与修正提示)
                return {"status": "error",
                        "message": detail.get("message", "硬约束违规"),
                        "violations": detail["violations"]}
            return None  # 其他 4xx/5xx → 降级本地
        except Exception:
            import traceback
            print("[primitive-service] 降级原因:", traceback.format_exc()[-500:],
                  file=__import__("sys").stderr, flush=True)
            return None  # 服务不可用 → 降级本地
        files = out.get("files") or []
        if not files or not out.get("ok"):
            import sys as _sys
            print("[primitive-service] 响应异常: ok=%s files=%s"
                  % (out.get("ok"), files), file=_sys.stderr, flush=True)
            return None
        # 统一契约:status/files(绝对路径)
        return {"status": "ok",
                "files": [f for f in files if f.endswith((".step", ".stl"))],
                "stdout": out.get("stdout", ""),
                "engine": "primitive-service"}

    def build(self, step_path=None):
        """Generate STEP file from current model state.

        Output goes to cad/{step_uuid}/ — each build is a unique,
        self-contained subdirectory.  The step_uuid is a content hash
        of the parts+joints state, making it reproducible.
        """
        import uuid, hashlib

        parts = self.state["parts"]
        joints = self.state["joints"]

        # Generate step_id: content hash (reproducibility trace) + full timestamp with
        # milliseconds → unique per build, never overwrites previous result dir.
        state_bytes = json.dumps({"parts": parts, "joints": joints},
                                  sort_keys=True, ensure_ascii=False).encode()
        content_hash = hashlib.sha256(state_bytes).hexdigest()[:12]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 含毫秒,保证唯一
        step_id = f"{content_hash}_{ts}"

        if step_path is None:
            cad_dir = os.path.join(self.project_dir, "cad") if self.project_dir else "/tmp"
            step_dir = os.path.join(cad_dir, step_id)
            os.makedirs(step_dir, exist_ok=True)
            step_path = os.path.join(step_dir, "design.step")

        # 原语体系独立(PrimitiveService 8103):优先走服务(约束校验+代码生成
        # +经 CADService 执行);失败降级本地 registry,保证会话不中断。
        remote = self._build_via_primitive_service(parts, joints, step_dir)
        if remote is not None:
            result = remote
        else:
            # 降级不降规则:本地生成前仍做硬律校验(8103 validate 优先,
            # 服务整体不可用时用本地 constraints)。违规拒绝并回给 LLM 修正。
            from .primitives_client import hard_failures
            hard = hard_failures(parts, joints)
            if hard:
                return {"status": "error",
                        "message": "硬约束违规,拒绝建模(几何必然错误)",
                        "violations": hard}
            code = primitives.generate_model_export(
                parts, joints, "Design", step_path,
                export_dir=os.path.dirname(step_path)
            )
            freecad = FreeCADTool(self.project_dir)
            result = freecad.execute_python(code)

        if result.get("status") == "ok":
            # 设计产物持久化到 MinIO(新键契约 {tenant}/p/{bigint_id}/cad/...;失败本地兜底)
            try:
                from . import minio_store
                from .project.manager import ProjectManager
                pid = ProjectManager(self.project_dir).pid
                rels = []
                if os.path.isdir(step_dir):
                    for fn in os.listdir(step_dir):
                        if fn.endswith((".step", ".stl", ".stp", ".FCStd")):
                            rels.append("cad/%s/%s" % (step_id, fn))
                keys = minio_store.upload_relfiles(pid, self.project_dir, rels)
                if keys:
                    self._write_minio_manifest(step_id, keys)
            except Exception as e:
                print("[minio] upload skip:", e)
            v = self._next_build_version() - 1  # current version after increment
            self.state["build_counter"] = v
            self._save()

            # Write manifest into the step directory
            self._write_manifest(step_id, result.get("files", []))
            result["version"] = v
            result["step_id"] = step_id
            result["step_dir"] = step_id

        return result

    def _write_minio_manifest(self, step_id, keys):
        """minio 对象键写入 manifest-minio.json(与 manifest.json 同目录)。"""
        cad_dir = os.path.join(self.project_dir, "cad")
        mpath = os.path.join(cad_dir, step_id, "manifest-minio.json")
        with open(mpath, "w") as f:
            json.dump({"bucket": "design-tool", "keys": keys}, f, ensure_ascii=False, indent=2)

    def _write_manifest(self, step_id, files):
        """Write manifest.json into the build subdirectory."""
        cad_dir = os.path.join(self.project_dir, "cad")
        step_dir = os.path.join(cad_dir, step_id)
        os.makedirs(step_dir, exist_ok=True)
        manifest = {
            "step_id": step_id,
            "timestamp": datetime.now().isoformat(),
            "parts": self.state.get("parts", []),
            "joints": self.state.get("joints", []),
            "files": [os.path.basename(f) for f in files],
        }
        with open(os.path.join(step_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    def clear(self):
        """Reset model state."""
        self.state = {"parts": [], "joints": [], "created_at": None, "updated_at": None}
        self._save()

    def summary(self):
        parts = self.state["parts"]
        joints = self.state["joints"]
        lines = ["当前模型状态:", ""]
        if parts:
            lines.append("零件 (%d):" % len(parts))
            root = []
            lookup = {}
            for p in parts:
                name = p.get("params", {}).get("name", "")
                if name:
                    lookup[name] = p
                p["_children"] = []
            for p in parts:
                pn = p.get("parent")
                if pn and pn in lookup:
                    lookup[pn]["_children"].append(p)
                else:
                    root.append(p)
            def _print(nodes, indent=0):
                pre = "  " * indent
                for n in nodes:
                    pp = n.get("params", {})
                    name = pp.get("name", "?")
                    kids = n.get("_children", [])
                    t = n["type"]
                    if t == "group":
                        lines.append(pre + "- " + name + " (组)")
                    elif t == "shell_box":
                        lines.append(pre + "- " + name + ": " + str(pp.get("L","?")) + "x" + str(pp.get("W","?")) + "x" + str(pp.get("H","?")) + " t=" + str(pp.get("t","?")) + " @" + str(pp.get("pos","?")))
                    else:
                        lines.append(pre + "- " + name + " (" + t + ")")
                    if kids:
                        _print(kids, indent + 1)
            _print(root)
            for p in parts:
                p.pop("_children", None)
        else:
            lines.append("零件: (空)")
        if joints:
            lines.append("")
            lines.append("关节 (%d):" % len(joints))
            for j in joints:
                jp = j.get("params", {})
                lines.append("  - " + jp.get("name", "?") + ": " + j.get("type", "?") + " @" + str(jp.get("pos","?")))
        else:
            lines.append("关节: (空)")
        return "\n".join(lines)
def tool_get_model_state():
    return {
        "type": "function",
        "function": {
            "name": "model_get_state",
            "description": "查询当前模型的所有零件和关节参数。在需要修改已有模型时，先调这个看当前参数。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


def tool_add_part():
    return {
        "type": "function",
        "function": {
            "name": "model_add_part",
            "description": "新增一个零件到模型中。用 list_design_primitives 查看可用的类型和参数。"
                         "布尔开孔(subtract):刀具(圆柱)必须【穿过】基体——刀具位置要伸入基体内部,"
                         "如球体开孔时圆柱中心应在球内(如 z=0),高度足够贯穿球壁;"
                         "刀具完全在基体外(只贴表面)会切不到任何材料,布尔结果不变。"
                         "空心球=外球减内球(两球同心)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Primitive type. For u_channel: ends='start'(wall at x=0), ends='end'(wall at x=L), ends='both'(both ends), ends='open'(no ends). Open trough pattern: left=start, middle=open, right=end"},
                    "params": {"type": "object", "description": "Parameters for this primitive"}
                },
                "required": ["type", "params"]
            }
        }
    }


def tool_update_part():
    return {
        "type": "function",
        "function": {
            "name": "model_update_part",
            "description": "修改已有零件的参数或名称。只传需要改的字段。改名：{'name': '新名字'}。改尺寸：{'L': 300, 'W': 400}",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "要修改的零件名称"},
                    "updates": {"type": "object", "description": "要修改的字段，例如 {\"L\": 300, \"W\": 400}"}
                },
                "required": ["name", "updates"]
            }
        }
    }


def tool_remove_part():
    return {
        "type": "function",
        "function": {
            "name": "model_remove_part",
            "description": "删除一个零件.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "零件名称"}
                },
                "required": ["name"]
            }
        }
    }


def tool_add_joint():
    return {
        "type": "function",
        "function": {
            "name": "model_add_joint",
            "description": "新增一个关节/连接到模型中。",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Primitive type, e.g. shell_box"},
                    "params": {"type": "object", "description": "Parameters"}
                },
                "required": ["type", "params"]
            }
        }
    }


def tool_update_joint():
    return {
        "type": "function",
        "function": {
            "name": "model_update_joint",
            "description": "修改已有关节的参数。只传需要改的字段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "关节名称"},
                    "updates": {"type": "object", "description": "要修改的字段"}
                },
                "required": ["name", "updates"]
            }
        }
    }


def tool_remove_joint():
    return {
        "type": "function",
        "function": {
            "name": "model_remove_joint",
            "description": "删除一个关节.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "关节名称"}
                },
                "required": ["name"]
            }
        }
    }


def tool_add_group():
    return {
        "type": "function",
        "function": {
            "name": "model_add_group",
            "description": "Create a group/assembly node for tree organization.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Group name"},
                    "parent": {"type": "string", "description": "Parent group name (optional)"}
                },
                "required": ["name"]
            }
        }
    }


def tool_model_build():
    return {
        "type": "function",
        "function": {
            "name": "model_build",
            "description": "根据当前模型状态重新生成 STEP 文件。每次修改完零件或关节后调用此工具生成最新模型。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


def tool_model_clear():
    return {
        "type": "function",
        "function": {
            "name": "model_clear",
            "description": "清空所有零件和关节，重置模型状态。用户说'重新设计''重来''从头开始'时必须先调用此工具。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


ALL_MODEL_TOOLS = [
    tool_get_model_state(),
    tool_add_part(),
    tool_update_part(),
    tool_remove_part(),
    tool_add_joint(),
    tool_update_joint(),
    tool_remove_joint(),
    tool_model_build(),
    tool_add_group(),
    tool_model_clear(),
]
