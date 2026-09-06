"""
Anvil integration: dtwin_client — calls Digital Twin microservice.

Adds kinematics and simulation tools to Anvil's agent tool list.
"""

import json
import urllib.request
import urllib.error

DTWIN_URL = "http://localhost:8092"


def _call(endpoint, data=None):
    """Call Dtwin API."""
    url = DTWIN_URL + endpoint
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"},
                                  method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": e.read().decode()[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def kinematics_solve(parts, joints, parameters):
    """Solve kinematic chain for given configuration."""
    return _call("/kinematics/solve", {
        "parts": parts, "joints": joints, "parameters": parameters
    })


def kinematics_animate(parts, joints, angle_start=0, angle_end=45, steps=10):
    """Generate animation frames."""
    return _call("/kinematics/animate", {
        "parts": parts, "joints": joints,
        "angle_start": angle_start, "angle_end": angle_end, "steps": steps
    })


def simulate_bellows(hinge_pos, attach_a, attach_b, initial_length,
                     angle_deg, axis_dir="y"):
    """Simulate bellows compression."""
    return _call("/simulate/bellows?" + urllib.parse.urlencode({
        "hinge_pos": json.dumps(hinge_pos),
        "attach_a": json.dumps(attach_a),
        "attach_b": json.dumps(attach_b),
        "initial_length": initial_length,
        "angle_deg": angle_deg,
        "axis_dir": axis_dir,
    }))


def mesh_bounds(path):
    """Get bounding box of an STL."""
    return _call("/mesh/bounds", {"path": path})


# ===== Tool definitions for Anvil agent =====

def tool_kinematics_solve():
    return {
        "type": "function",
        "function": {
            "name": "dtwin_solve",
            "description": "数字孪生：求解运动学链。给定零件、关节和参数，计算每个零件在世界空间中的位置和旋转。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parts": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "零件列表 [{\"name\":\"rear\",\"initial_transform\":[[4x4]]}]"
                    },
                    "joints": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "关节列表 [{\"type\":\"hinge\",\"parent\":\"rear\",\"child\":\"front\",\"position\":[x,y,z],\"axis\":\"y\"}]"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "参数如 {\"angle\": 30}"
                    }
                },
                "required": ["parts", "joints", "parameters"]
            }
        }
    }


def tool_kinematics_animate():
    return {
        "type": "function",
        "function": {
            "name": "dtwin_animate",
            "description": "数字孪生：生成动画关键帧序列。用于前端滑块驱动模型运动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parts": {"type": "array", "items": {"type": "object"}},
                    "joints": {"type": "array", "items": {"type": "object"}},
                    "angle_start": {"type": "number", "description": "起始角度"},
                    "angle_end": {"type": "number", "description": "终止角度"},
                    "steps": {"type": "integer", "description": "帧数"}
                },
                "required": ["parts", "joints"]
            }
        }
    }


def tool_simulate_bellows():
    return {
        "type": "function",
        "function": {
            "name": "dtwin_bellows",
            "description": "数字孪生：波纹管压缩仿真。计算铰链旋转时波纹管的伸缩量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hinge_pos": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] 铰链中心"},
                    "attach_a": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] 波纹管固定端"},
                    "attach_b": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] 波纹管活动端"},
                    "initial_length": {"type": "number", "description": "波纹管原始长度"},
                    "angle_deg": {"type": "number", "description": "旋转角度"},
                    "axis_dir": {"type": "string", "enum": ["x", "y"]}
                },
                "required": ["hinge_pos", "attach_a", "attach_b", "initial_length", "angle_deg"]
            }
        }
    }



def validate_configuration(parts, joints, parameters, bounds):
    """Validate a configuration for part interference."""
    return _call("/validate", {
        "parts": parts, "joints": joints,
        "parameters": parameters, "bounds": bounds
    })


def validate_range(parts, joints, bounds, angle_start=0, angle_end=90, step=5):
    """Scan angle range to find collision angle."""
    return _call("/validate/range", {
        "parts": parts, "joints": joints, "bounds": bounds,
        "angle_start": angle_start, "angle_end": angle_end, "step": step
    })


def calc_drive_torque(load_N, lever_mm, angle_deg=0):
    return _call("/drive/torque", {"load_N": load_N, "lever_mm": lever_mm, "angle_deg": angle_deg})


def calc_actuator_force(torque_Nm, mount_offset_mm, mount_angle_deg=90):
    return _call("/drive/actuator_force", {"torque_Nm": torque_Nm, "mount_offset_mm": mount_offset_mm, "mount_angle_deg": mount_angle_deg})


def suggest_actuator(force_N, stroke_mm, speed_mm_s=10):
    return _call("/drive/actuator_sizing", {"force_N": force_N, "stroke_mm": stroke_mm, "speed_mm_s": speed_mm_s})


def suggest_mounts(hinge_pos, part_length, part_height):
    return _call("/drive/mount_suggest", {"hinge_pos": hinge_pos, "part_length": part_length, "part_height": part_height})


# ===== Tool definitions =====
def tool_validate():
    return {
        "type": "function",
        "function": {
            "name": "dtwin_validate",
            "description": "数字孪生验证：检测当前构型下零件之间是否有干涉（碰撞）。需传入 bounds（各零件STL包围盒）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parts": {"type": "array", "items": {"type": "object"}},
                    "joints": {"type": "array", "items": {"type": "object"}},
                    "parameters": {"type": "object"},
                    "bounds": {
                        "type": "object",
                        "description": "540496f64ef676845c4090e8530556f476d2Ff0c683c5f0f5982 {rear: {min: [0,0,0], max: [300,360,200]}}"
                    }
                },
                "required": ["parts", "joints", "bounds"]
            }
        }
    }


def tool_validate_range():
    return {
        "type": "function",
        "function": {
            "name": "dtwin_validate_range",
            "description": "数字孪生验证：扫描角度范围，找出零件开始碰撞的临界角度。用于确定铰链的安全行程。",
            "parameters": {
                "type": "object",
                "properties": {
                    "parts": {"type": "array", "items": {"type": "object"}},
                    "joints": {"type": "array", "items": {"type": "object"}},
                    "bounds": {"type": "object"},
                    "angle_start": {"type": "number", "description": "起始角度"},
                    "angle_end": {"type": "number", "description": "终止角度"},
                    "step": {"type": "number", "description": "扫描步长(度)"}
                },
                "required": ["parts", "joints", "bounds"]
            }
        }
    }


def tool_drive_torque():
    return {
        "type": "function",
        "function": {
            "name": "calc_drive_torque",
            "description": "计算铰链处所需扭矩：负载 × 力臂 × cos(角度)。用于确定驱动系统需求。",
            "parameters": {
                "type": "object",
                "properties": {
                    "load_N": {"type": "number", "description": "负载力 (N)"},
                    "lever_mm": {"type": "number", "description": "负载重心到铰链距离 (mm)"},
                    "angle_deg": {"type": "number", "description": "当前角度 (度), 默认0"}
                },
                "required": ["load_N", "lever_mm"]
            }
        }
    }


def tool_actuator_force():
    return {
        "type": "function",
        "function": {
            "name": "calc_actuator_force",
            "description": "将铰链扭矩换算为直线执行器所需的推力。根据安装点和角度计算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "torque_Nm": {"type": "number", "description": "铰链扭矩 (Nm)"},
                    "mount_offset_mm": {"type": "number", "description": "执行器安装点到铰链距离 (mm)"},
                    "mount_angle_deg": {"type": "number", "description": "执行器与力臂夹角 (度), 默认90"}
                },
                "required": ["torque_Nm", "mount_offset_mm"]
            }
        }
    }


def tool_suggest_actuator():
    return {
        "type": "function",
        "function": {
            "name": "suggest_actuator",
            "description": "推荐合适的电动推杆型号。根据推力和行程匹配标准型号(LA12/LA23/LA36/LA44)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "force_N": {"type": "number", "description": "所需推力 (N)"},
                    "stroke_mm": {"type": "number", "description": "所需行程 (mm)"},
                    "speed_mm_s": {"type": "number", "description": "期望速度 mm/s, 默认10"}
                },
                "required": ["force_N", "stroke_mm"]
            }
        }
    }


ALL_DTWIN_TOOLS = [
    tool_kinematics_solve(),
    tool_kinematics_animate(),
    tool_simulate_bellows(),
    tool_validate(),
    tool_validate_range(),
    tool_drive_torque(),
    tool_actuator_force(),
    tool_suggest_actuator(),
]
