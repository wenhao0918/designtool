"""KBService 后端策略集。

统一接口(实现即可接入):
    search(query, top_k) -> [KBHit]
    ping()              -> bool

后端类型:
- LocalJSONBackend   本地 JSON 规则库(gbstd data 等,确定性,离线兜底)
- RAGFlowBackend     RAGFlow 数据集(语义检索,自然语言)
- AnvilTermsProxy    Anvil /api/terms 代理(机械术语精确查询,自动登录缓存 token)
- MaterialProxy      Anvil /api/material 代理(标准件库,自动登录)
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

KB_ROOT = os.path.dirname(os.path.abspath(__file__))


class KBHit:
    """一条检索命中。"""

    def __init__(self, content, source, score=1.0, meta=None):
        self.content = content
        self.source = source
        self.score = score
        self.meta = meta or {}

    def to_dict(self):
        return {"content": self.content, "source": self.source,
                "score": round(self.score, 3), "meta": self.meta}


def _http_json(method, url, body=None, headers=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------- 本地 JSON 规则库 ----------

class LocalJSONBackend:
    """目录下所有 *.json 为可检索单元(键路径/摘要/全文关键词评分)。"""

    def __init__(self, name, data_dir=None, doc_dir=None):
        self.name = name
        self.data_dir = data_dir
        self.doc_dir = doc_dir
        self._cache = None

    def ping(self):
        return True

    def _load(self):
        if self._cache is None:
            items = []
            if self.data_dir and os.path.isdir(self.data_dir):
                for fn in sorted(os.listdir(self.data_dir)):
                    if fn.endswith(".json"):
                        with open(os.path.join(self.data_dir, fn),
                                  encoding="utf-8") as f:
                            items.append((os.path.splitext(fn)[0],
                                          json.load(f)))
            self._cache = items
        return self._cache

    def search(self, query, top_k=5):
        q = query.strip()
        hits = []
        for sect, data in self._load():
            std = data.get("standard", "")
            blob = json.dumps(data, ensure_ascii=False).lower()
            score = 0.0
            for kw in re.split(r"[\s,，。;；/]+", q):
                if len(kw) >= 2 and kw.lower() in blob:
                    score += blob.count(kw.lower()) * 0.8
            if sect in q or std.lower() in q.lower():
                score += 5
            if score > 0:
                hits.append(KBHit(
                    content="%s(%s): %s" % (sect, std,
                                            data.get("summary", "")[:120]),
                    source=std or ("local/" + self.name + "/" + sect),
                    score=min(score / 10.0, 1.0),
                    meta={"type": "local", "domain": self.name,
                          "section": sect,
                          "data": data if score >= 4 else None}))
        hits.sort(key=lambda h: -h.score)
        return hits[:top_k]


# ---------- RAGFlow ----------

class RAGFlowBackend:
    def __init__(self, name, dataset_id, url=None, api_key=None):
        self.name = name
        self.dataset = dataset_id
        self.url = url or os.environ.get(
            "RAGFLOW_URL", "http://localhost:1800")
        self.api_key = api_key or os.environ.get(
            "RAGFLOW_API_KEY",
            "ragflow-9IGG6y08i6itpjXiF4ae_QA82eOzkLbt5swQWGVB0EM")

    def ping(self):
        try:
            r = _http_json("GET", self.url + "/api/v1/datasets?page=1&page_size=1",
                           headers={"Authorization": "Bearer " + self.api_key},
                           timeout=6)
            return r.get("code") == 0
        except Exception:
            return False

    def search(self, query, top_k=5):
        r = _http_json("POST", self.url + "/api/v1/retrieval", body={
            "question": query,
            "dataset_ids": [self.dataset],
            "document_ids": [],
            "page_size": top_k,
            "similarity_threshold": 0.2,
        }, headers={"Authorization": "Bearer " + self.api_key}, timeout=25)
        if r.get("code") != 0:
            return []
        out = []
        for c in (r.get("data") or {}).get("chunks", []):
            out.append(KBHit(
                content=re.sub(r"<[^>]+>", "", c.get("content", ""))[:400],
                source=c.get("document_keyword", "RAGFlow"),
                score=c.get("similarity", 0.0),
                meta={"type": "ragflow", "domain": self.name,
                      "doc_id": c.get("document_id")}))
        return out[:top_k]


# ---------- RAGFlow 图谱(GraphRAG) ----------

class RAGFlowGraphBackend(RAGFlowBackend):
    """RAGFlow Graph dataset(chunk_method=graph,解析时自动实体抽取)。

    检索走同一 /api/v1/retrieval:命中片段带实体上下文;
    图遍历(实体邻居)用 RAGFlow 图查询,此处检索为主。
    """

    def search(self, query, top_k=5):
        hits = super().search(query, top_k)
        for h in hits:
            h.meta["type"] = "ragflow_graph"
        return hits


# ---------- Anvil 业务库代理 ----------

class AnvilAuth:
    """AdminService 登录 → Anvil JWT,缓存至过期前 60s。"""

    def __init__(self):
        self.auth_url = os.environ.get(
            "ADMIN_AUTH_URL", "http://127.0.0.1:8097/api/auth/login")
        self.user = os.environ.get("KB_SVC_USER", "")
        self.password = os.environ.get("KB_SVC_PASS", "")
        self._token = None
        self._exp = 0

    @property
    def configured(self):
        return bool(self.user and self.password)

    def token(self):
        if not self.configured:
            return None
        if self._token and time.time() < self._exp:
            return self._token
        r = _http_json("POST", self.auth_url,
                       body={"username": self.user, "password": self.password})
        self._token = r.get("token")
        # JWT exp(无库解析,保守 2h)
        self._exp = time.time() + 2 * 3600 - 60
        return self._token


_AUTH = AnvilAuth()


class AnvilTermsProxy:
    """机械术语(Anvil mech_terms 表)。q 过滤 term/definition/aliases。"""

    def __init__(self, name="mechterms"):
        self.name = name
        self.base = os.environ.get("ANVIL_API", "http://127.0.0.1:8095")

    def ping(self):
        return _AUTH.configured

    def search(self, query, top_k=5):
        tok = _AUTH.token()
        if not tok:
            return []
        try:
            terms = _http_json("GET", self.base + "/api/terms",
                               headers={"Authorization": "Bearer " + tok},
                               timeout=15)
        except Exception:
            return []
        ql = query.strip().lower()
        hits = []
        for t in terms:
            blob = " ".join(str(t.get(k, "")) for k in
                            ("term", "definition", "geometry", "modeling")).lower()
            if ql and ql not in blob:
                continue
            score = 1.0 if ql == str(t.get("term", "")).lower() else 0.6
            hits.append(KBHit(
                content="%s: %s | 建模: %s" % (
                    t.get("term"), t.get("definition"),
                    str(t.get("modeling"))[:80]),
                source="mech_terms(term#%s)" % t.get("id"),
                score=score, meta={"type": "anvil", "domain": self.name}))
        return hits[:top_k]


class MaterialProxy:
    """标准件库(经 Anvil 代理 mn-material)。searchCache 关键词全库搜。"""

    COLLECTIONS = ("standardPart", "nonstandardPart", "industryPart",
                   "enterprisePart", "supplierInfo")

    def __init__(self, name="materials"):
        self.name = name
        self.base = os.environ.get("ANVIL_API", "http://127.0.0.1:8095")

    def ping(self):
        return _AUTH.configured

    def search(self, query, top_k=5):
        tok = _AUTH.token()
        if not tok:
            return []
        q = urllib.parse.quote(query.strip())
        try:
            r = _http_json(
                "GET",
                self.base + "/api/material/searchCache/list?keyword=" + q
                + "&pageNum=1&pageSize=%d" % top_k,
                headers={"Authorization": "Bearer " + tok}, timeout=20)
        except Exception:
            return []
        rows = (r or {}).get("rows") or []
        hits = []
        for row in rows[:top_k]:
            name = row.get("name") or row.get("partName") or str(row)[:80]
            spec = row.get("specification") or row.get("spec") or ""
            brand = row.get("brand") or ""
            hits.append(KBHit(
                content="%s %s %s" % (name, spec, brand),
                source="mn-material/" + str(row.get("collection", "part")),
                score=0.7, meta={"type": "material", "domain": self.name,
                                 "row": row}))
        return hits
