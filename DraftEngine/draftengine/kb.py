"""知识库统一接口:面向 DraftEngine/AI Agent 的 RAG 服务。

抽象层(策略模式):
- RAGFlowBackend  远程 RAGFlow 检索(语义,自然语言问答)
- LocalBackend    本地 gbstd 规则库(键路径精确查询,零依赖兜底)
- KBService       门面:先本地(确定性规则),再 RAGFlow(语义扩展),
                  结果带 source 标注可追溯。

接口约定(任何新后端实现这三个方法即可接入):
    search(query, top_k) -> [KBHit]
    ask(query)          -> {answer, hits}   (仅 RAG 后端支持生成)
    ping()              -> bool
"""

import json
import os
import re
import urllib.request

from . import gbstd

RAGFLOW_URL = os.environ.get("RAGFLOW_URL", "http://localhost:1800")
RAGFLOW_API_KEY = os.environ.get("RAGFLOW_API_KEY",
                                 "ragflow-9IGG6y08i6itpjXiF4ae_QA82eOzkLbt5swQWGVB0EM")
RAGFLOW_DATASET = os.environ.get("RAGFLOW_DATASET",
                                 "64cc97e4a0ef11f19e5b7eb885516d10")  # 工程图纸国标


class KBHit:
    """一条检索命中。"""

    def __init__(self, content, source, score=1.0, meta=None):
        self.content = content      # 命中正文
        self.source = source        # 出处(标准号/数据节)
        self.score = score          # 相关度 0~1
        self.meta = meta or {}

    def to_dict(self):
        return {"content": self.content, "source": self.source,
                "score": round(self.score, 3), "meta": self.meta}


class LocalBackend:
    """本地 gbstd 规则库检索。

    两种命中:
    - 节名/摘要/正文关键词匹配 → 整节 JSON
    - 文本里出现 mm 数值/标准号 → 对应参数条目
    确定性、离线可用——RAGFlow 不可用时的兜底。
    """

    def __init__(self):
        self._sections = None

    def ping(self):
        return True

    def _all(self):
        if self._sections is None:
            self._sections = {s: gbstd.load(s) for s in gbstd.sections()}
        return self._sections

    def search(self, query, top_k=5):
        q = query.strip().lower()
        hits = []
        for name, data in self._all().items():
            std = data.get("standard", "")
            blob = json.dumps(data, ensure_ascii=False).lower()
            # 评分:节名命中 3 分 / 标准号命中 5 分 / 关键词频次
            score = 0.0
            if re.search(r"gb/t\s*%s" % re.escape(name), q):
                score += 5
            for kw in re.split(r"[\s,，。;；/]+", query):
                if len(kw) >= 2 and kw.lower() in blob:
                    score += blob.count(kw.lower()) * 0.8
            if name in q or std.lower() in q:
                score += 3
            if score > 0:
                summary = data.get("summary", "")[:120]
                hits.append(KBHit(
                    content="%s(%s): %s" % (name, std, summary),
                    source=std or ("gbstd/" + name),
                    score=min(score / 10.0, 1.0),
                    meta={"section": name, "type": "local_rule",
                          "data": data if score >= 3 else None}))
        hits.sort(key=lambda h: -h.score)
        return hits[:top_k]

    def ask(self, query):
        hits = self.search(query, top_k=3)
        if not hits:
            return {"answer": "本地规则库无匹配,请换关键词或走 RAGFlow 通道",
                    "hits": []}
        answer = ";\n".join(h.content for h in hits)
        return {"answer": answer, "hits": [h.to_dict() for h in hits]}


class RAGFlowBackend:
    """RAGFlow 检索 + 生成(语义,支持自然语言)。"""

    def __init__(self, url=None, api_key=None, dataset=None):
        self.url = url or RAGFLOW_URL
        self.api_key = api_key or RAGFLOW_API_KEY
        self.dataset = dataset or RAGFLOW_DATASET

    def _req(self, method, path, body=None, timeout=20):
        url = self.url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.api_key)
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def ping(self):
        try:
            r = self._req("GET", "/api/v1/datasets?page=1&page_size=1", timeout=6)
            return r.get("code") == 0
        except Exception:
            return False

    def search(self, query, top_k=5):
        r = self._req("POST", "/api/v1/retrieval", body={
            "question": query,
            "dataset_ids": [self.dataset],
            "document_ids": [],
            "page_size": top_k,
            "similarity_threshold": 0.2,
        })
        if r.get("code") != 0:
            return []
        out = []
        for c in (r.get("data") or {}).get("chunks", []):
            out.append(KBHit(
                content=re.sub(r"<[^>]+>", "", c.get("content", ""))[:400],
                source=c.get("document_keyword", "RAGFlow"),
                score=c.get("similarity", 0.0),
                meta={"type": "ragflow",
                      "doc_id": c.get("document_id"),
                      "positions": c.get("positions")}))
        return out[:top_k]

    def ask(self, query):
        """检索增强回答:命中片段拼接为上下文,由调用方接 LLM 生成;
        此处先返回片段组装的回答(RAGFlow chat 需单独建会话,留接口)。"""
        hits = self.search(query, top_k=4)
        if not hits:
            return {"answer": "RAGFlow 无命中", "hits": []}
        answer = ";\n\n".join("[%s] %s" % (h.source, h.content) for h in hits)
        return {"answer": answer, "hits": [h.to_dict() for h in hits]}


class KBService:
    """门面:本地规则(确定性) + RAGFlow(语义)双通道,自动降级。"""

    def __init__(self, ragflow=None, local=None):
        self.ragflow = ragflow or RAGFlowBackend()
        self.local = local or LocalBackend()

    def search(self, query, top_k=5, backend="auto"):
        """
        backend: auto(local+ragflow 合并) / local / ragflow
        返回 [KBHit];auto 模式两路都查,local 结果排前(确定性优先)。
        """
        if backend == "local":
            return self.local.search(query, top_k)
        if backend == "ragflow":
            return self.ragflow.search(query, top_k)
        hits = self.local.search(query, top_k)
        try:
            hits += self.ragflow.search(query, top_k)
        except Exception:
            pass
        return hits[:top_k * 2]

    def ask(self, query, backend="auto"):
        if backend == "local":
            return self.local.ask(query)
        if backend == "ragflow":
            try:
                return self.ragflow.ask(query)
            except Exception as e:
                return {"answer": "RAGFlow 不可用(%s),已降级本地" % e,
                        "hits": []}
        # auto:本地答案 + RAGFlow 片段合并
        base = self.local.ask(query)
        try:
            rag = self.ragflow.search(query, top_k=3)
            if rag:
                base["hits"] += [h.to_dict() for h in rag]
                base["answer"] += "\n\n[RAGFlow 语义补充]\n" + \
                    ";\n".join("[%s] %s" % (h.source, h.content[:100]) for h in rag)
        except Exception:
            base["ragflow"] = "unavailable"
        return base

    def status(self):
        return {"ragflow": {"ok": self.ragflow.ping(), "dataset": self.ragflow.dataset,
                            "url": self.ragflow.url},
                "local": {"ok": True, "sections": gbstd.sections()}}


_service = None


def service():
    global _service
    if _service is None:
        _service = KBService()
    return _service
