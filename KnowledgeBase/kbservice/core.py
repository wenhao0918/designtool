"""KBService 核心:知识域注册 + 联邦检索。

定位(2026-08-26 定稿):纯查询联邦——数字资产本体在 RAGFlow,
本服务不存内容、不碰 docs/;职责是统一入口:
    RAGFlow(国标向量/图谱) + Anvil(术语/标准件) → 一个 API。

域(domain) = {label, backends: [(名, 后端, 权重)]},新增域注册一行。
"""

import os

from .backends import (AnvilTermsProxy, MaterialProxy, RAGFlowBackend,
                       RAGFlowGraphBackend)

# RAGFlow datasets(数字资产本体;graph 型需先在 RAGFlow 建 Graph dataset)
RAGFLOW_GBSTD = os.environ.get("RAGFLOW_DATASET",
                               "64cc97e4a0ef11f19e5b7eb885516d10")
RAGFLOW_GBSTD_GRAPH = os.environ.get("RAGFLOW_DATASET_GRAPH", "")


def default_domains():
    domains = {
        "gbstd": {
            "label": "工程图纸国标",
            "backends": [
                ("ragflow", RAGFlowBackend("gbstd", RAGFLOW_GBSTD), 1.0),
            ],
        },
        "mechterms": {
            "label": "机械设计术语",
            "backends": [("proxy", AnvilTermsProxy("mechterms"), 1.0)],
        },
        "materials": {
            "label": "标准件库",
            "backends": [("proxy", MaterialProxy("materials"), 1.0)],
        },
    }
    if RAGFLOW_GBSTD_GRAPH:
        domains["gbstd"]["backends"].append(
            ("ragflow_graph", RAGFlowGraphBackend("gbstd",
                                                  RAGFLOW_GBSTD_GRAPH), 1.05))
    return domains


class KBService:
    def __init__(self, domains=None):
        self.domains = domains or default_domains()

    def search(self, query, top_k=5, domain=None, kinds=None):
        """跨域检索。kinds 过滤后端类型(ragflow/ragflow_graph/proxy)。"""
        results = []
        for dname, d in self.domains.items():
            if domain and dname != domain:
                continue
            for bname, backend, weight in d["backends"]:
                if kinds and bname not in kinds:
                    continue
                try:
                    hits = backend.search(query, top_k)
                except Exception:
                    continue
                for h in hits:
                    h.score = min(h.score * weight, 1.0)
                    h.meta.setdefault("domain", dname)
                    h.meta["backend"] = bname
                results += hits
        results.sort(key=lambda h: -h.score)
        return results[:top_k * (2 if not domain else 1)]

    def ask(self, query, top_k=4, domain=None):
        hits = self.search(query, top_k, domain=domain)
        answer = ";\n\n".join("[%s|%s] %s" % (h.meta.get("backend"), h.source,
                                              h.content[:160]) for h in hits)
        return {"answer": answer or "无命中",
                "hits": [h.to_dict() for h in hits]}

    def status(self):
        out = {}
        for dname, d in self.domains.items():
            backends = {}
            for bname, backend, _ in d["backends"]:
                try:
                    ok = backend.ping()
                except Exception:
                    ok = False
                backends[bname] = ok
            out[dname] = {"label": d["label"], "backends": backends}
        return out
