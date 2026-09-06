"""RAGFlow 客户端 — 国标分类知识库的检索与建库操作面。"""

import json
import os
import re
import urllib.request

RAGFLOW_URL = os.environ.get("RAGFLOW_URL", "http://localhost:1800")
RAGFLOW_KEY = os.environ.get(
    "RAGFLOW_API_KEY",
    "ragflow-9IGG6y08i6itpjXiF4ae_QA82eOzkLbt5swQWGVB0EM")


def _req(method, path, body=None, timeout=25):
    req = urllib.request.Request(
        RAGFLOW_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Authorization", "Bearer " + RAGFLOW_KEY)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ping():
    try:
        return _req("GET", "/api/v1/datasets?page=1&page_size=1",
                    timeout=6).get("code") == 0
    except Exception:
        return False


def retrieve(query, dataset_ids, top_k=5):
    """向量检索:多库联检(dataset_ids 列表)。返回清洗后的命中列表。"""
    r = _req("POST", "/api/v1/retrieval", {
        "question": query,
        "dataset_ids": dataset_ids,
        "document_ids": [],
        "page_size": top_k,
        "similarity_threshold": 0.2,
    })
    if r.get("code") != 0:
        return []
    out = []
    for c in (r.get("data") or {}).get("chunks", []):
        out.append({
            "content": re.sub(r"<[^>]+>", "", c.get("content", ""))[:400],
            "source": c.get("document_keyword", ""),
            "score": round(c.get("similarity", 0.0), 3),
            "doc_id": c.get("document_id", ""),
        })
    return out[:top_k]


def create_dataset(name, description=""):
    """建库(RAGFlow dataset)。返回 dataset_id;失败抛异常。"""
    r = _req("POST", "/api/v1/datasets", {
        "name": name,
        "description": description,
        "permission": "team",
    })
    if r.get("code") != 0:
        raise RuntimeError("RAGFlow 建库失败: %s" % r.get("message"))
    return r["data"]["id"]
