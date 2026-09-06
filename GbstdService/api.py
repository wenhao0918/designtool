"""GbstdService — 国标服务统一外壳(端口 8104,HTTP+MCP)。

定位(2026-08-27):各类国标经统一分类目录对外服务:
  分类目录(catalog) → RAGFlow 分类知识库(一分类一库) → 查询路由。
建库:POST /api/gbstd/categories auto_create → 自动在 RAGFlow 建库并登记。

消费方:
  Anvil query_standard(category 参数指定分类)
  DraftEngine gbstd.collect(--category 按分类入库)
与 KnowledgeBase(8101) 关系:8101 仍是联邦入口(术语/物料代理等),
国标域由本服务承载(分类路由+建库)——8101 的 gbstd 域后续可指向本服务。

启动: python3 api.py --port 8104
"""

import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import catalog
import ragflow_client as ragflow
import router

app = FastAPI(
    title="GbstdService", version="0.2.0",
    description="国标服务统一外壳:分类目录(=dataset指针+服务方法) + 查询路由")

# 服务方法绑定:统一签名 fn(query, dataset_ids, top_k) → hits
catalog.SERVICES["ragflow"] = ragflow.retrieve


class CategoryReq(BaseModel):
    name: str
    label: str = ""
    keywords: list = []
    dataset_id: str = ""
    service: str = "ragflow"    # 服务方法类型(统一签名 query(q,top_k)→hits)
    auto_create: bool = False   # 无 dataset_id 时自动在 RAGFlow 建库


class QueryReq(BaseModel):
    q: str
    category: str = ""          # 空=自动路由;"all"=全分类联检
    top_k: int = 5


@app.get("/api/gbstd/status", operation_id="gbstd_status",
         summary="服务状态:分类统计 + RAGFlow 连通")
def status():
    c = catalog.load_catalog()
    return {"ok": True,
            "categories": {"total": len(c), "active": len(catalog.routable(c))},
            "ragflow": ragflow.ping()}


@app.get("/api/gbstd/categories", operation_id="gbstd_categories",
         summary="国标分类目录(含各分类关键词与库绑定)")
def categories():
    return catalog.load_catalog()


@app.post("/api/gbstd/categories", operation_id="gbstd_register",
          summary="新增/更新国标分类;auto_create 可自动建 RAGFlow 库")
def register(req: CategoryReq):
    name = req.name.strip()
    if not name or not name.replace("_", "").isascii():
        raise HTTPException(422, "分类名仅限 ASCII/下划线(如 fasteners)")
    if req.service not in catalog.SERVICES:
        raise HTTPException(422, "未知服务方法 '%s'(可用: %s)"
                            % (req.service, ",".join(sorted(catalog.SERVICES))))
    c = catalog.load_catalog()
    ds = req.dataset_id
    created = False
    if not ds and req.auto_create:
        if req.service != "ragflow":
            raise HTTPException(422, "auto_create 仅支持 ragflow 服务方法")
        label = req.label or name
        try:
            ds = ragflow.create_dataset(
                "国标-" + label, "GbstdService 分类:%s" % name)
            created = True
        except Exception as e:
            raise HTTPException(502, str(e))
    entry = catalog.upsert(c, name, req.label, req.keywords, ds,
                           service=req.service)
    catalog.save_catalog(c)
    return {"name": name, "entry": entry, "dataset_created": created}


@app.post("/api/gbstd/query", operation_id="gbstd_query",
          summary="国标检索:显式分类优先,否则关键词路由;category=all 全分类联检")
def query(req: QueryReq):
    q = req.q.strip()
    if not q:
        raise HTTPException(400, "q 不能为空")
    c = catalog.load_catalog()
    active = catalog.routable(c)
    routing = {"method": "", "category": "", "score": 0, "matched": []}

    if req.category and req.category != "all":
        entry = active.get(req.category)
        if not entry:
            raise HTTPException(404, "分类 '%s' 不存在或未绑定知识库"
                                % req.category)
        routing.update({"method": "explicit", "category": req.category})
        entries = [entry]
    elif req.category == "all":
        routing.update({"method": "fanout",
                        "category": ",".join(sorted(active))})
        entries = list(active.values())
    else:
        cat, score, matched = router.classify(q, c)
        routing.update({"method": "classified" if score else "default",
                        "category": cat, "score": score, "matched": matched})
        entries = [active[cat]]

    # 统一服务方法:按分类声明的 service 类型分发(签名一致)。
    # ragflow 类可共库联检;异型 service 逐条独立调用后合并。
    hits = []
    by_service = {}
    for e in entries:
        by_service.setdefault(e.get("service", "ragflow"), []).append(e)
    for svc, group in sorted(by_service.items()):
        fn = catalog.SERVICES.get(svc)
        if fn is None:
            continue  # 未注册的服务类型跳过(分类登记时已挡,双保险)
        if svc == "ragflow":
            hits += fn(q, [g["dataset_id"] for g in group], top_k=req.top_k)
        else:
            for g in group:
                hits += fn(q, [g["dataset_id"]], top_k=req.top_k)
    hits.sort(key=lambda h: -h.get("score", 0))
    return {"query": q, "routing": routing, "count": len(hits),
            "hits": hits[:req.top_k]}


def main():
    import uvicorn
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    else:
        port = int(os.environ.get("GBSTD_PORT", "8104"))
    try:
        root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        from mcp_helper import mount_mcp
        mount_mcp(app, name="GbstdService",
                  description="国标统一服务:分类目录/分类路由检索/建库登记")
    except Exception as e:
        print("[mcp] GbstdService MCP 挂载跳过:", e)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
