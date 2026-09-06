"""参数注册中心"""
import yaml, os
from datetime import datetime

REG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "registry")
REG_PATH = os.path.join(REG_DIR, "registry.yaml")
AUDIT_PATH = os.path.join(REG_DIR, "audit_log.md")

def load():
    if not os.path.exists(REG_PATH):
        return {"params": {}}
    with open(REG_PATH) as f:
        return yaml.safe_load(f) or {"params": {}}

def save(data):
    os.makedirs(REG_DIR, exist_ok=True)
    with open(REG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def list_params(cat=None, min_conf=None):
    data = load()
    res = []
    for n, p in data.get("params", {}).items():
        if cat and p.get("category") != cat:
            continue
        c = p.get("confidence", "")
        if min_conf and len(c) < min_conf:
            continue
        res.append({"name": n, **p})
    return res

def get_param(name):
    return load().get("params", {}).get(name)

def update_param(name, value, unit, confidence, changed_by="AI", reason=""):
    data = load()
    data.setdefault("params", {})
    if name not in data["params"]:
        data["params"][name] = {"created": datetime.now().isoformat()}
    p = data["params"][name]
    p.update({"value": value, "unit": unit, "confidence": confidence,
              "updated": datetime.now().isoformat(), "updated_by": changed_by})
    save(data)
    _audit(name, value, unit, changed_by, reason)
    return p

def _audit(name, value, unit, who, reason):
    os.makedirs(REG_DIR, exist_ok=True)
    h = "| 时间 | 参数 | 值 | 变更人 | 原因 |\n|------|------|-----|--------|------|\n"
    l = f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {name} | {value} {unit} | {who} | {reason} |\n"
    if not os.path.exists(AUDIT_PATH):
        with open(AUDIT_PATH, "w") as f:
            f.write("# 参数变更审计日志\n\n" + h + l)
    else:
        with open(AUDIT_PATH, "a") as f:
            f.write(l)

def validate_ranges():
    data = load()
    issues = []
    for n, p in data.get("params", {}).items():
        v = p.get("value")
        r = p.get("range")
        if v and r:
            lo, hi = r.get("min"), r.get("max")
            if lo is not None and hi is not None and (v < lo or v > hi):
                issues.append({"param": n, "value": v, "range": r})
    return issues
