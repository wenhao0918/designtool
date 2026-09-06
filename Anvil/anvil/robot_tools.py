"""Robot design tools for Anvil agent."""
import sys
import os

try:
    sys.path.insert(0, "/mnt/data/develop/work/digital-twin")
    from dtwin import robotics
except (ImportError, ModuleNotFoundError):
    robotics = None

# ===== Agent tool definitions =====

def tool_robot_forward():
    return {
        "type": "function",
        "function": {
            "name": "robot_dh_forward",
            "description": "机器人运动学正解：给定 DH 参数和关节角度，计算末端位姿和各关节位置。支持预设模型（6dof_articulated/scara）或自定义 DH。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dh_params": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                        "description": "[[a, alpha_deg, d, theta_offset], ...] 每行一个关节"
                    },
                    "joint_angles_deg": {
                        "type": "array", "items": {"type": "number"},
                        "description": "各关节角度（度）"
                    },
                    "model": {
                        "type": "string",
                        "description": "预设模型名: 6dof_articulated / scara，填此则忽略 dh_params"
                    },
                },
                "required": ["joint_angles_deg"]
            }
        }
    }


def tool_robot_models():
    return {
        "type": "function",
        "function": {
            "name": "robot_list_models",
            "description": "列出可用的预设机器人模型（DH参数、关节范围、工作半径）。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


def tool_robot_workspace():
    return {
        "type": "function",
        "function": {
            "name": "robot_workspace",
            "description": "计算机器人工作空间（可达范围）。返回包围盒和体积。",
            "parameters": {
                "type": "object",
                "properties": {
                    "dh_params": {"type": "array", "items": {"type": "array"}},
                    "joint_ranges_deg": {
                        "type": "array", "items": {"type": "array"},
                        "description": "[[min, max], ...] 每个关节的角度范围"
                    },
                    "model": {"type": "string", "description": "预设模型名"}
                },
                "required": ["joint_ranges_deg"]
            }
        }
    }


# ===== Tool implementations =====

def _get_dh(model_name, dh_params):
    if robotics and model_name and model_name in robotics.ROBOT_MODELS:
        return robotics.ROBOT_MODELS[model_name]["dh_params"]
    return dh_params

def _get_ranges(model_name, joint_ranges):
    if robotics and model_name and model_name in robotics.ROBOT_MODELS:
        return robotics.ROBOT_MODELS[model_name]["joint_ranges"]
    return joint_ranges


ALL_ROBOT_TOOLS = [
    tool_robot_forward(),
    tool_robot_models(),
    tool_robot_workspace(),
] if robotics else []
