"""PrimitiveService — 设计原语体系服务(端口 8103,HTTP+MCP)。

Primordium 理论的可执行载体(2026-08-26):
  原语注册表 + 约束规则 + 术语语义 = 理论当前快照
任何 LLM/Agent 经此服务获得统一的机械设计建模能力与合规校验;
几何执行委托 CADService(8102),本服务不直接跑 FreeCAD。

API:
  GET  /api/primitives/list                 原语清单+schema+语义
  POST /api/primitives/validate             parts/joints → 违规清单(不建模)
  POST /api/primitives/compose              parts+joints → 代码 → CADService
                                           → STEP/STL 落盘
启动: python3 api.py --port 8103
"""

import json
import os
import sys
import urllib.request

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import registry
import constraints
import grammar
import resolver

app = FastAPI(title="PrimitiveService", version="0.1.0",
              description="设计原语体系(Primordium 可执行载体):"
                          "原语注册表+约束校验+组合建模")

CADSERVICE_URL = os.environ.get("CADSERVICE_URL", "http://127.0.0.1:8102")


class DesignReq(BaseModel):
    parts: list
    joints: list = []
    work_dir: str = ""          # compose 时产物目录(空→/tmp)
    timeout: int = 180


@app.get("/api/primitives/list", operation_id="list_primitives",
         summary="设计原语清单(参数schema+语义描述)")
def list_primitives():
    return {"primitives": registry.list_primitives(),
            "count": len(registry.PRIMITIVE_REGISTRY)}


# ============ 设计语言演算(结果是算出来的:LLM 只译句子,计算归本服务) ============

class IntentReq(BaseModel):
    sentence: dict          # 设计语言句子(dsl.v0,见 grammar.py)
    compose: bool = False   # true → 演算后直接建模出 STEP(走现有 compose 链路)
    work_dir: str = ""


@app.get("/api/grammar", operation_id="get_design_grammar",
         summary="设计语言文法 V0(体元/算子/关系词汇表——prompt 动态注入唯一来源)")
def get_grammar():
    return grammar.describe()


@app.post("/api/intent/resolve", operation_id="resolve_design_intent",
          summary="设计语言演算器:句子→语法校验→体元求值→算子代数→关系方程→坐标解算→parts(零决策)")
def resolve_design_intent(req: IntentReq):
    ok, errors, normalized = grammar.validate(req.sentence)
    if not ok:
        raise HTTPException(status_code=422, detail={
            "message": "句子不合法,打回重译(翻译问题,不是建模问题)",
            "errors": errors})
    try:
        result = resolver.evaluate(normalized)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={
            "message": "演算失败: %s" % e, "errors": [str(e)]})
    result["grammar_errors"] = []
    if req.compose and result["status"] == "ok":
        sub = DesignReq(parts=result["parts"], joints=[],
                        work_dir=req.work_dir, timeout=180)
        result["build"] = compose_design(sub)
    return result


@app.post("/api/primitives/validate", operation_id="validate_design",
          summary="约束校验(不建模):返回 hard/feas/value 违规清单")
def validate_design(req: DesignReq):
    v = constraints.validate(req.parts, req.joints)
    return {"ok": not any(x["level"] == constraints.HARD for x in v),
            "violations": v,
            "summary": {"hard": sum(1 for x in v if x["level"] == "hard"),
                        "feas": sum(1 for x in v if x["level"] == "feas"),
                        "value": sum(1 for x in v if x["level"] == "value")}}


@app.post("/api/primitives/compose", operation_id="compose_design",
          summary="组合原语建模:校验→生成 FreeCAD 代码→CADService 执行")
def compose_design(req: DesignReq):
    hard = constraints.hard_failures(req.parts, req.joints)
    if hard:
        raise HTTPException(
            status_code=422, detail={
                "message": "硬约束违规,拒绝建模(几何必然错误)",
                "violations": hard})
    step_path = os.path.join(req.work_dir or "/tmp", "design.step")
    code = registry.generate_model_export(
        req.parts, req.joints, "Design", step_path,
        export_dir=req.work_dir or None)
    body = json.dumps({"code": code,
                       "work_dir": req.work_dir or "/tmp",
                       "timeout": req.timeout}).encode()
    r = urllib.request.Request(CADSERVICE_URL + "/api/cad/execute",
                               data=body, method="POST")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=req.timeout + 30) as resp:
            out = json.loads(resp.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail="CADService 不可用: %s" % e)
    out["files"] = [os.path.join(req.work_dir or "/tmp", f)
                    for f in out.get("files", [])]
    return out


def main():
    import uvicorn
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    else:
        port = int(os.environ.get("PRIM_PORT", "8103"))
    try:
        root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        from mcp_helper import mount_mcp
        mount_mcp(app, name="PrimitiveService",
                  description="设计原语体系(Primordium 载体):"
                              "原语清单/约束校验/组合建模")
    except Exception as e:
        print("[mcp] PrimitiveService MCP 挂载跳过:", e)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
