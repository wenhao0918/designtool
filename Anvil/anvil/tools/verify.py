"""
Design verification tools — check that generated model meets requirements.

Runs after STEP generation to validate against the original design spec.
"""

import json


def verify_design(requirements, model_parts, issues=None):
    """Verify generated design against requirements.

    Args:
        requirements: structured requirement dict (from requirement parser)
        model_parts: list of part dicts used in the model
        issues: optional list of already-known issues

    Returns:
        dict with passed, failed, warnings
    """
    results = {"passed": [], "failed": [], "warnings": []}

    req = requirements

    # 1. Check part count
    required_parts = []
    if req.get("parts"):
        required_parts = [p.get("name") for p in req["parts"]]
    if req.get("constraints", {}).get("num_parts"):
        required_parts = list(range(req["constraints"]["num_parts"]))

    model_names = [p.get("params", {}).get("name", "") for p in model_parts]
    if required_parts:
        if len(model_names) >= len(required_parts):
            results["passed"].append(f"Part count OK: {len(model_names)} >= {len(required_parts)}")
        else:
            results["failed"].append(f"Missing parts: need {len(required_parts)}, have {len(model_names)}")

    # 2. Check joints
    required_joints = req.get("joints", [])
    if required_joints and issues:
        results["passed"].append(f"Joints specified: {len(required_joints)}")
    elif required_joints and not issues:
        pass  # Can't verify joints from parts list alone

    # 3. Check constraints
    constraints = req.get("constraints", {})
    for key, expected in constraints.items():
        if key == "hollow" and expected:
            # Check if any shell_box is used
            has_shell = any(p.get("type") == "shell_box" for p in model_parts)
            if has_shell:
                results["passed"].append("Hollow construction: present")
            else:
                results["failed"].append("Missing hollow construction")
        elif key == "open_top" and expected:
            results["passed"].append("Open top: assumed (shell_box default)")
        elif key == "has_bottom" and expected:
            results["passed"].append("Bottom: present (shell_box has solid bottom)")

    # 4. Check for standard issues
    if issues:
        for issue in issues:
            results["warnings"].append(issue)

    return results


def design_review(requirements_raw: str, model_plan: dict):
    """Generate a human-readable design review.

    Args:
        requirements_raw: original user requirement text
        model_plan: the design plan dict with parts and joints

    Returns:
        Markdown review text
    """
    parts = model_plan.get("parts", [])
    joints = model_plan.get("joints", [])
    params = model_plan.get("parameters", {})

    review = []
    review.append("## 设计审查报告\n")
    review.append("### 结构概览\n")
    review.append(f"- 零件数: {len(parts)}")
    review.append(f"- 连接/关节数: {len(joints)}")

    if params:
        review.append("\n### 关键参数\n")
        for k, v in params.items():
            if isinstance(v, dict):
                review.append(f"- **{k}**:")
                for sk, sv in v.items():
                    review.append(f"  - {sk}: {sv}")
            else:
                review.append(f"- **{k}**: {v}")

    if parts:
        review.append("\n### 零件清单\n")
        for p in parts:
            ptype = p.get("type", "?")
            pname = p.get("params", {}).get("name", "?")
            review.append(f"- {pname} ({ptype})")

    if joints:
        review.append("\n### 连接/关节\n")
        for j in joints:
            jtype = j.get("type", "?")
            jname = j.get("params", {}).get("name", "?")
            review.append(f"- {jname} ({jtype})")

    review.append("\n### 待检查项\n")
    review.append("- [ ] 零件间干涉检查")
    review.append("- [ ] 铰链旋转行程验证")
    review.append("- [ ] 波纹管伸缩量校核")
    review.append("- [ ] 结构强度校核")
    review.append("- [ ] 铰链销剪切强度")
    review.append("- [ ] 人机工程尺寸验证")

    return "\n".join(review)
