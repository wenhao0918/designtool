# -*- coding: utf-8 -*-
"""DesignTool 确定性求解演示 — 单进程 FastAPI。"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import solver

app = FastAPI(title="DesignTool Demo — 确定性设计求解")
STATIC = Path(__file__).parent / "static"


class SolveIn(BaseModel):
    preset: str = "ball_base"
    params: dict = {}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/solve")
def solve_api(payload: SolveIn):
    return JSONResponse(solver.solve(payload.model_dump()))
