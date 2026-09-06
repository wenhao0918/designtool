"""KnowledgeBase 独立知识查询服务(端口 8101)——纯联邦 API。

数字资产本体在 RAGFlow(知识库+知识图谱);本服务统一入口:
    GET /api/kb/status       域+后端健康
    GET /api/kb/domains      域清单
    GET /api/kb/search?q=&top_k=&domain=&kinds=ragflow,proxy...
    GET /api/kb/ask?q=&domain=

知识内容管理(上传/替换/图谱)直接在 RAGFlow GUI 操作;
docs/ 目录仅是资料整理工作区,与本服务无关。

启动: python -m kbservice.api --port 8101
"""

import os
import sys

from fastapi import FastAPI, HTTPException

from .core import KBService

app = FastAPI(title="KnowledgeBase", version="0.2.0")
_svc = KBService()


@app.get("/api/kb/status")
def status():
    return {"ok": True, "domains": _svc.status()}


@app.get("/api/kb/domains")
def domains():
    return {"domains": {k: {"label": v["label"]} for k, v in _svc.domains.items()}}


@app.get("/api/kb/search")
def search(q: str, top_k: int = 5, domain: str = "", kinds: str = ""):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q 不能为空")
    kind_list = [k for k in kinds.split(",") if k] or None
    hits = _svc.search(q, top_k=min(top_k, 20),
                       domain=domain or None, kinds=kind_list)
    return {"query": q, "count": len(hits), "hits": [h.to_dict() for h in hits]}


@app.get("/api/kb/ask")
def ask(q: str, domain: str = ""):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q 不能为空")
    return _svc.ask(q, domain=domain or None)


def main():
    import uvicorn
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    else:
        port = int(os.environ.get("KB_PORT", "8101"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
