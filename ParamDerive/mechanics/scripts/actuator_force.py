"""
@param: 推杆推力_F
@input: 使用者质量(kg)=120, 力臂(mm)=250, 倾角=65
@output: 需求推力(N), 安全系数, 选型推力(N)
@method: 力矩平衡
@confidence: ****
"""
import math

def calc(mass=120, lever_arm=250, tilt_angle=65, safety=1.5):
    g = 9.81
    weight = mass * g
    torque = weight * (lever_arm / 1000) * math.sin(math.radians(tilt_angle))
    required = torque / (lever_arm / 1000)
    selected = max(required * safety, 5000)
    return {
        "torque_Nm": round(torque, 1),
        "required_force_N": round(required, 0),
        "selected_force_N": round(selected, 0),
        "safety_factor": safety,
        "formula": "F = m*g*L*sin(theta) / L  (力矩平衡)",
    }

if __name__ == "__main__":
    import json
    print(json.dumps(calc(), indent=2, ensure_ascii=False))
