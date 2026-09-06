"""
Design pipeline — orchestrates multi-stage design process.

Each stage produces structured output consumed by the next stage.
Keeps the LLM focused on one thing at a time instead of doing everything at once.
"""

import os
import json
import logging
from datetime import datetime

from .requirement_parser import parse_requirement
from .tools.primitives import generate_model_export, list_primitives
from .primitives_client import list_primitives as list_primitives_remote
from . import spatial as spatial_tools

logger = logging.getLogger(__name__)


# Stage definitions for LLM guidance
STAGE_DEFINITIONS = {
    "parse": {
        "name": "需求解析",
        "description": "将用户自然语言描述解析为结构化规格（零件、连接、密封、约束）",
        "next": "concept",
    },
    "concept": {
        "name": "概念设计",
        "description": "基于结构化规格确定机构方案、布局、材料选择。调用空间计算工具验证可行性。",
        "next": "detail",
    },
    "detail": {
        "name": "详细设计",
        "description": "确定所有尺寸参数，校核强度，生成FreeCAD模型并导出STEP。使用设计原语生成代码，不手写坐标。",
        "next": "verify",
    },
    "verify": {
        "name": "验证校核",
        "description": "检查模型是否满足需求，检查干涉，检查关键特征。",
        "next": None,
    },
}


def get_pipeline_status(stage):
    """Get current pipeline stage description."""
    s = STAGE_DEFINITIONS.get(stage, {})
    return {
        "current_stage": stage,
        "stage_name": s.get("name", stage),
        "stage_description": s.get("description", ""),
        "next_stage": s.get("next"),
        "available_primitive_types": list(list_primitives_remote().keys()),
    }


def run_stage_parse(requirement_text):
    """Stage 1: Parse requirements."""
    return parse_requirement(requirement_text)


def run_stage_concept(spec):
    """Stage 2: Conceptual design — determine layout and parameters.

    This is primarily LLM-driven with spatial tool support.
    Runs spatial analysis to validate the concept.

    Args:
        spec: structured spec from parse stage

    Returns:
        dict with layout, parts_plan, joints_plan, parameters, issues
    """
    issues = []
    parameters = {}

    parts = spec.get("parts", [])
    joints = spec.get("joints", [])

    # Suggest ergonomic dimensions if not specified
    if any(p.get("approx_size", {}).get("l") is None for p in parts):
        ergo = spatial_tools.resolve_ergonomic_dimensions()
        parameters["ergonomic_reference"] = ergo

    # Estimate loads
    loads = spatial_tools.estimate_seated_loads()
    parameters["estimated_loads"] = loads
    parameters["estimated_load_N"] = loads["total_load_N"]

    # Check interference between parts
    model_parts = []
    for p in parts:
        pname = p.get("name", "part")
        ps = p.get("approx_size", {})
        L = ps.get("l") or parameters.get("ergonomic_reference", {}).get("rear_length") or 300
        W = ps.get("w") or parameters.get("ergonomic_reference", {}).get("rear_width") or 360
        H = ps.get("h") or 200
        model_parts.append({
            "type": "shell_box",
            "params": {"name": pname, "L": L, "W": W, "H": H, "t": 8, "pos": (0, 0, 0)},
        })

    interference = spatial_tools.check_interference(model_parts)
    if interference:
        issues.extend(interference)

    return {
        "layout": "front_rear_split",
        "parts_plan": parts,
        "joints_plan": joints,
        "parameters": parameters,
        "issues": issues,
        "suggested_primitives": ["shell_box", "u_channel", "plate"],
    }


def run_stage_detail(concept_output):
    """Stage 3: Detailed design — generate FreeCAD model."""
    parts = concept_output.get("parts_plan", [])
    joints_plan = concept_output.get("joints_plan", [])
    params = concept_output.get("parameters", {})
    ergo = params.get("ergonomic_reference", {})
    loads = params.get("estimated_loads", {})

    # Convert concept to model parts
    model_parts = []
    x_offset = 0
    for p in parts:
        pname = p.get("name", "part")
        ps = p.get("approx_size", {})
        L = ps.get("l") or 300
        W = ps.get("w") or 360
        H = ps.get("h") or 200

        # Use ergonomic reference if available
        if ergo:
            if "后" in pname:
                L = ergo.get("rear_length", L)
                W = ergo.get("rear_width", W)
                H = ergo.get("rear_height", H)

        model_parts.append({
            "type": "shell_box",
            "params": {
                "name": pname,
                "L": L,
                "W": W,
                "H": H,
                "t": 8,
                "pos": (x_offset, 0, 0),
            },
        })
        x_offset += L

    # Convert joints to model joints
    model_joints = []
    seals = []
    # Convert seals
    for seal in j.get("seals", []):
        pass  # TODO: handle seal primitives in future

    # Strength check
    strength_report = None
    if loads:
        pin_load = loads.get("total_load_N", 750) * 0.6  # ~60% on front part
        strength_report = spatial_tools.cantilever_bending(pin_load, 200, 300, 8, 70000)

    return {
        "model_parts": model_parts,
        "model_joints": model_joints,
        "strength_report": strength_report,
        "notes": [],
    }


def design_review_markdown(spec, concept, detail, verify_result=None):
    """Generate a comprehensive design review in markdown."""
    lines = []
    lines.append("# 设计方案\n")

    lines.append("## 需求\n")
    for p in spec.get("parts", []):
        lines.append(f"- {p.get('name', '?')}: {p.get('function', '')}")
    for j in spec.get("joints", []):
        lines.append(f"- 连接: {j.get('type', '')} 在 {j.get('position', '')}")
    for s in spec.get("seals", []):
        lines.append(f"- 密封: {s.get('type', '')} ({s.get('material', '')})")

    lines.append("\n## 参数\n")
    params = concept.get("parameters", {})
    for k, v in params.items():
        if isinstance(v, dict):
            lines.append(f"- {k}:")
            for sk, sv in v.items():
                lines.append(f"  - {sk}: {sv}")
        else:
            lines.append(f"- {k}: {v}")

    issues = concept.get("issues", [])
    if issues:
        lines.append(f"\n## 问题 ({len(issues)})\n")
        for issue in issues:
            desc = issue.get("description", str(issue))
            lines.append(f"- ⚠ {desc}")

    sr = detail.get("strength_report")
    if sr:
        lines.append(f"\n## 强度校核\n")
        lines.append(f"- 弯曲应力: {sr.get('bending_stress_MPa', '?')} MPa")
        lines.append(f"- 挠度: {sr.get('deflection_mm', '?')} mm")
        lines.append(f"- 安全系数: {sr.get('safety_factor', '?')}")
        if sr.get('safety_factor', 0) < 1.5:
            lines.append(f"- ⚠ 安全系数不足，需增加壁厚或加强结构")

    lines.append(f"\n## 模型\n")
    model_parts = detail.get("model_parts", [])
    for mp in model_parts:
        pp = mp.get("params", {})
        lines.append(f"- {pp.get('name', '?')}: {pp.get('L', '?')}×{pp.get('W', '?')}×{pp.get('H', '?')} t={pp.get('t', '?')}")
    model_joints = detail.get("model_joints", [])
    for mj in model_joints:
        mp = mj.get("params", {})
        lines.append(f"- 连接: {mp.get('name', '?')} @ {mp.get('pos', '?')} axis={mp.get('axis_dir', '?')}")

    if verify_result:
        lines.append(f"\n## 验证\n")
        for item in verify_result.get("passed", []):
            lines.append(f"- ✅ {item}")
        for item in verify_result.get("failed", []):
            lines.append(f"- ❌ {item}")
        for item in verify_result.get("warnings", []):
            lines.append(f"- ⚠ {item}")

    return "\n".join(lines)
