"""推导脚本执行器"""
import os, importlib

SCRIPTS_DIR = os.path.dirname(os.path.dirname(__file__))
CATS = {"anatomy": "anatomy/scripts", "mechanics": "mechanics/scripts",
         "kinematics": "kinematics/scripts", "components": "components/scripts"}

def list_scripts(cat=None):
    res = []
    for c, sd in CATS.items():
        if cat and c != cat:
            continue
        d = os.path.join(SCRIPTS_DIR, sd)
        if not os.path.exists(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            meta = _read_meta(os.path.join(d, fn))
            res.append({"name": fn[:-3], "category": c, "path": os.path.join(sd, fn), **meta})
    return res

def _read_meta(path):
    with open(path) as f:
        content = f.read()
    meta = {}
    for line in content.split("\n")[:20]:
        for k in ["param", "input", "output", "method", "confidence"]:
            if line.strip().startswith("@" + k + ":"):
                meta[k] = line.split(":", 1)[1].strip()
    return meta

def run_script(script_path, **kwargs):
    full = os.path.join(SCRIPTS_DIR, script_path)
    if not os.path.exists(full):
        return {"error": "script not found: " + script_path}
    spec = importlib.util.spec_from_file_location("calc_mod", full)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "calc"):
        return {"error": "no calc() function"}
    try:
        res = mod.calc(**kwargs)
        return {"status": "ok", "result": res, "script": script_path}
    except Exception as e:
        return {"status": "error", "error": str(e), "script": script_path}
