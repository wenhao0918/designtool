"""
Spatial computation tools — geometry, kinematics, force calculations.

These run in Python (no FreeCAD needed) to compute positions,
dimensions, and mechanical relationships.
"""

import math






def hinge_rotation(hinge_pos, axis_dir, angle_deg, point):
    """Rotate a point around a pivot (hinge) axis — general rotation kinematics.

    Args:
        hinge_pos: (x, y, z) hinge pin center
        axis_dir: 'x' or 'y'
        angle_deg: rotation angle in degrees
        point: (x, y, z) point to rotate

    Returns:
        (x, y, z) rotated point
    """
    angle = math.radians(angle_deg)
    # Translate to origin
    ox, oy, oz = hinge_pos
    px, py, pz = point
    tx, ty, tz = px - ox, py - oy, pz - oz

    if axis_dir == 'x':
        y2 = ty * math.cos(angle) - tz * math.sin(angle)
        z2 = ty * math.sin(angle) + tz * math.cos(angle)
        return (ox + tx, oy + y2, oz + z2)
    else:  # 'y'
        x2 = tx * math.cos(angle) + tz * math.sin(angle)
        z2 = -tx * math.sin(angle) + tz * math.cos(angle)
        return (ox + x2, oy + ty, oz + z2)

def bellows_compression(initial_length, angle_deg, hinge_pos, attach_point_a, attach_point_b, axis_dir='y'):
    """Calculate bellows length change given hinge rotation.

    The flexible section connects two parts across a hinge. When the hinge rotates,
    the distance between attachment points changes, compressing/extending the bellows.

    Args:
        initial_length: bellows free length (mm)
        angle_deg: hinge rotation angle (degrees)
        hinge_pos: hinge pin center (x,y,z)
        attach_point_a: bellows attachment on part A (x,y,z) — before rotation
        attach_point_b: bellows attachment on part B (x,y,z) — before rotation
        axis_dir: hinge axis direction

    Returns:
        dict with new_length, delta, compression_ratio, status
    """
    # Part B rotates, part A stays
    rotated_b = hinge_rotation(hinge_pos, axis_dir, angle_deg, attach_point_b)

    # Distance between attachment points
    dx = rotated_b[0] - attach_point_a[0]
    dy = rotated_b[1] - attach_point_a[1]
    dz = rotated_b[2] - attach_point_a[2]
    new_length = math.sqrt(dx * dx + dy * dy + dz * dz)

    delta = new_length - initial_length
    ratio = new_length / initial_length if initial_length > 0 else 1.0

    status = "normal"
    if abs(ratio - 1.0) > 0.5:
        status = "warning: excessive deformation"
    elif ratio < 0.3:
        status = "warning: bellows over-compressed"

    return {
        "new_length": round(new_length, 1),
        "delta": round(delta, 1),
        "compression_ratio": round(ratio, 3),
        "rotated_B_attach": tuple(round(v, 1) for v in rotated_b),
        "status": status,
    }

def box_volume(L, W, H, t, open_top=True):
    """Calculate volume of a shell box."""
    outer_vol = L * W * H
    if open_top:
        inner_vol = (L - 2 * t) * (W - 2 * t) * (H - t)
    else:
        inner_vol = (L - 2 * t) * (W - 2 * t) * (H - 2 * t)
    return outer_vol - inner_vol


def estimate_weight(volume_mm3, density_g_cm3=7.85):
    """Estimate weight from volume and density.

    Args:
        volume_mm3: volume in cubic mm
        density_g_cm3: density in g/cm³ (default 7.85 for steel)

    Returns:
        weight in kg
    """
    volume_cm3 = volume_mm3 / 1000
    return volume_cm3 * density_g_cm3 / 1000


def cantilever_bending(force_N, length_mm, width_mm, height_mm, E_MPa=70000):
    """Simple cantilever beam bending calculation.

    Args:
        force_N: force at free end (N)
        length_mm: beam length (mm)
        width_mm: beam width (mm)
        height_mm: beam height (mm)
        E_MPa: Young's modulus (MPa, default 70000 for aluminum)

    Returns:
        dict with stress, deflection, safety_factor
    """
    I = width_mm * (height_mm ** 3) / 12  # moment of inertia (mm⁴)
    M = force_N * length_mm  # bending moment (N·mm)
    c = height_mm / 2  # distance to extreme fiber (mm)
    stress = M * c / I  # bending stress (MPa)

    deflection = force_N * (length_mm ** 3) / (3 * E_MPa * I)  # mm

    # Typical yield strengths (MPa)
    yield_strengths = {
        "steel_304": 215,
        "steel_316": 290,
        "aluminum_6061": 276,
        "aluminum_7075": 503,
        "plastic_abs": 40,
        "ceramic": 100,
    }
    safe_stress = yield_strengths.get("aluminum_6061", 200)
    safety_factor = safe_stress / stress if stress > 0 else 999

    return {
        "bending_stress_MPa": round(stress, 2),
        "deflection_mm": round(deflection, 2),
        "safety_factor": round(safety_factor, 2),
        "status": "ok" if safety_factor >= 1.5 else "warning: safety factor too low",
    }


def hinge_pin_shear(load_N, pin_r, pin_count=2, material="steel_304"):
    """Calculate hinge pin shear stress.

    Args:
        load_N: total load on hinge (N)
        pin_r: pin radius (mm)
        pin_count: number of pins
        material: pin material key

    Returns:
        dict with shear_stress, allowable_stress, safety_factor
    """
    area_per_pin = math.pi * pin_r ** 2
    shear_area = area_per_pin * pin_count
    if hasattr(load_N, '__iter__'):
        load_N = max(load_N) if load_N else 0
    shear_stress = load_N / shear_area if shear_area > 0 else 0

    shear_strengths = {
        "steel_304": 172,
        "steel_316": 232,
        "steel_45": 200,
        "aluminum_6061": 207,
    }
    allowable = shear_strengths.get(material, 172)
    sf = allowable / shear_stress if shear_stress > 0 else 999

    return {
        "shear_stress_MPa": round(shear_stress, 2),
        "allowable_MPa": allowable,
        "safety_factor": round(sf, 2),
        "status": "ok" if sf >= 2.0 else "warning: safety factor too low",
    }


def estimate_seated_loads(body_weight_kg=75, thigh_ratio=0.3):
    """Estimate loads for seated design (chairs, seats, recliners, care equipment).

    Args:
        body_weight_kg: user body weight (kg)
        thigh_ratio: fraction of weight on thighs (vs buttocks)

    Returns:
        dict with buttock_load, thigh_load, total_load (all in N)
    """
    total_N = body_weight_kg * 9.81
    thigh_N = total_N * thigh_ratio
    buttock_N = total_N - thigh_N
    return {
        "buttock_load_N": round(buttock_N, 1),
        "thigh_load_N": round(thigh_N, 1),
        "total_load_N": round(total_N, 1),
    }


def resolve_ergonomic_dimensions(body_height_mm=1700, body_weight_kg=75):
    """Suggest ergonomic dimensions for seated products when user gives no sizes.

    Uses ergonomic references to suggest reasonable dimensions
    when user doesn't specify exact numbers.

    Args:
        body_height_mm: user height (mm, default 1700)
        body_weight_kg: user weight (kg, default 75)

    Returns:
        dict with recommended dimensions
    """
    # Ergonomic reference: hip width ~360mm, thigh length ~450mm
    # (proportions of body height)
    hip_w = max(320, min(420, body_height_mm * 0.22))
    thigh_l = max(400, min(550, body_height_mm * 0.27))
    foot_l = max(200, min(280, body_height_mm * 0.15))

    return {
        "rear_width": round(hip_w),
        "rear_length": round(thigh_l * 0.6),
        "rear_height": round(max(180, min(250, body_height_mm * 0.12))),
        "front_width": round(hip_w * 0.85),
        "front_length": round(thigh_l * 0.4 + foot_l * 0.3),
        "front_height": round(max(180, min(250, body_height_mm * 0.12))),
        "wall_thickness": 8,
        "recommended_material": "stainless_steel_304_or_equivalent",
        "notes": "Dimensions based on standard ergonomic references. Adjust as needed.",
    }


def extract_part_bounds(part_def):
    """Extract bounding box from a part definition.

    Args:
        part_def: dict with type and params

    Returns:
        (min_x, min_y, min_z, max_x, max_y, max_z) or None
    """
    ptype = part_def.get("type")
    params = part_def.get("params", {})
    pos = params.get("pos", (0, 0, 0))

    if ptype == "shell_box":
        L = params.get("L", 0)
        W = params.get("W", 0)
        H = params.get("H", 0)
        return (pos[0], pos[1], pos[2],
                pos[0] + L, pos[1] + W, pos[2] + H)
    return None


def check_interference(part_defs):
    """Check if any two parts overlap (simple AABB check).

    Args:
        part_defs: list of part definition dicts

    Returns:
        list of (part_a, part_b, overlap_description)
    """
    bounds = []
    for p in part_defs:
        b = extract_part_bounds(p)
        if b:
            bounds.append((p.get("params", {}).get("name", "?"), b))

    issues = []
    for i in range(len(bounds)):
        for j in range(i + 1, len(bounds)):
            name_a, ba = bounds[i]
            name_b, bb = bounds[j]
            # Check AABB overlap
            if (ba[0] < bb[3] and ba[3] > bb[0] and
                ba[1] < bb[4] and ba[4] > bb[1] and
                ba[2] < bb[5] and ba[5] > bb[2]):
                overlap = (
                    round(min(ba[3], bb[3]) - max(ba[0], bb[0]), 1),
                    round(min(ba[4], bb[4]) - max(ba[1], bb[1]), 1),
                    round(min(ba[5], bb[5]) - max(ba[2], bb[2]), 1),
                )
                issues.append({
                    "part_A": name_a,
                    "part_B": name_b,
                    "overlap_mm": overlap,
                    "description": f"{name_a} overlaps {name_b} by {overlap}",
                })
    return issues
