"""Demo API — 迭代式设计演示(动画/配音)的数据与 TTS 服务。

GET /api/demo/{name}          → 演示脚本(steps: 指令/解说/STL文件)
GET /api/demo/{name}/audio/{i} → 第 i 步解说配音(mp3,Edge-TTS 生成并缓存)

演示数据:从真实项目历史生成(轴承座V2 = 五步迭代设计的教学化重述)。
TTS 缓存:anvil/data/demo_audio/{name}_{i}.mp3,文本 sha1 前缀防过期错配。
"""

import asyncio
import hashlib
import os

from fastapi import APIRouter, HTTPException, Response

from .deps import DATA_DIR

router = APIRouter(prefix="/api/demo", tags=["demo"])

AUDIO_DIR = os.path.join(DATA_DIR, "demo_audio")
VOICE = "zh-CN-XiaoxiaoNeural"

# 演示脚本(与真实项目 cbbe67dc0c41 的五步对应;解说词面向观众,教学化)
DEMOS = {}


import glob as _glob
import json as _json

DEMOS_DIR = os.path.join(DATA_DIR, "demos")


def _demo(name):
    """演示脚本:文件优先(data/demos/{name}.json,改文件即生效),内置兜底。"""
    fp = os.path.join(DEMOS_DIR, name + ".json")
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            return _json.load(f)
    d = DEMOS.get(name)
    if not d:
        avail = [os.path.basename(x)[:-5]
                 for x in _glob.glob(os.path.join(DEMOS_DIR, "*.json"))]
        avail += list(DEMOS)
        raise HTTPException(404, "demo '%s' 不存在(可用: %s)" % (name, ",".join(sorted(set(avail)))))
    return d


@router.get("")
def list_demos():
    """可用演示清单(文件+内置,给前端选单)。"""
    out = {}
    for fp in _glob.glob(os.path.join(DEMOS_DIR, "*.json")):
        try:
            with open(fp, encoding="utf-8") as f:
                d = _json.load(f)
            out[os.path.basename(fp)[:-5]] = d.get("title", os.path.basename(fp))
        except Exception:
            continue
    for k, v in DEMOS.items():
        out.setdefault(k, v["title"])
    return {"demos": out}


def _resolve_stl(project_ref, prefix):
    """演示步骤 → 实际 STL 文件。

    兼容两链产物结构(2026-09-06 同步):
    - chat 链: cad/{step_id}/design.stl(子目录)
    - 译码链: cad/step_{N}.stl(平铺,prefix=step_N 不含扩展名)
    """
    from .project.manager import resolve_project_dir
    base = os.path.join(DATA_DIR, "projects", "admin")
    pdir, _pid = resolve_project_dir(base, project_ref)
    if not pdir:
        return None
    cad = os.path.join(pdir, "cad")
    if not os.path.isdir(cad):
        return None
    for entry in os.listdir(cad):
        if entry.startswith(prefix) and os.path.isfile(os.path.join(cad, entry, "design.stl")):
            return "%s/design.stl" % entry
    # 译码链平铺产物: cad/{prefix}.stl
    flat = prefix + ".stl"
    if os.path.isfile(os.path.join(cad, flat)):
        return flat
    return None


@router.get("/{name}")
def get_demo(name: str):
    d = _demo(name)
    steps = []
    for s in d["steps"]:
        stl_rel = _resolve_stl(d["project_ref"], s["stl"])
        steps.append({k: v for k, v in s.items()} | {"stl_file": stl_rel})
    return {"title": d["title"], "subtitle": d["subtitle"],
            "project_ref": d["project_ref"], "steps": steps}


def _tts_sync(text, out_path):
    async def _gen():
        import edge_tts
        await edge_tts.Communicate(text, VOICE).save(out_path)
    asyncio.run(_gen())


@router.get("/{name}/audio/{idx}")
def get_demo_audio(name: str, idx: int):
    d = _demo(name)
    if idx < 0 or idx >= len(d["steps"]):
        raise HTTPException(404, "step out of range")
    s = d["steps"][idx]
    os.makedirs(AUDIO_DIR, exist_ok=True)
    sig = hashlib.sha1((s["narration"] + VOICE).encode()).hexdigest()[:10]
    path = os.path.join(AUDIO_DIR, "%s_%d_%s.mp3" % (name, idx, sig))
    # 空文件视为未生成(生成竞态可能留下 0 字节,不能进缓存)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        if os.path.exists(path):
            os.unlink(path)
        import threading
        t = threading.Thread(target=_tts_sync, args=(s["narration"], path))
        t.start(); t.join(timeout=60)  # 同步等待生成(首次较慢,之后走缓存)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise HTTPException(500, "tts failed")
    return Response(content=open(path, "rb").read(),
                    media_type="audio/mpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
