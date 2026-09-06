"""RAGFlow backend — knowledge retrieval via RAGFlow API.

协同 MySQL 术语表：
- MySQL: 精确匹配、别名查询、结构化定义
- RAGFlow: 语义搜索、详细文档、模糊查询
- 查询流程: 先 MySQL 精确匹配 → 未命中则 RAGFlow 语义搜索
"""

import os
import json
import httpx
from pathlib import Path
from .base import RAGBackend


# 机械设计术语知识库 ID
MECH_TERMS_DATASET_ID = "38661c8b9a0e11f1bc457eb885516d10"


class RAGFlowBackend(RAGBackend):
    def __init__(self):
        self.base_url = os.environ.get("ANVIL_RAGFLOW_URL", "").rstrip("/")
        self.api_key = os.environ.get("ANVIL_RAGFLOW_API_KEY", "")
        self._headers = {}
        if self.api_key:
            self._headers["Authorization"] = "Bearer " + self.api_key

    def _available(self):
        return bool(self.base_url and self.api_key)

    def search(self, question, dataset_ids=None, top_k=5):
        """语义搜索 RAGFlow 知识库。"""
        if not self._available():
            return {"error": "RAGFlow not configured. Set ANVIL_RAGFLOW_URL and ANVIL_RAGFLOW_API_KEY."}
        if dataset_ids is None:
            datasets = self.list_datasets()
            if isinstance(datasets, dict) and "error" in datasets:
                return datasets
            dataset_ids = [d["id"] for d in datasets]
        try:
            resp = httpx.post(
                self.base_url + "/api/v1/retrieval",
                headers=self._headers,
                json={"question": question, "dataset_ids": dataset_ids, "top_k": top_k},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return [
                        {
                            "content": c.get("content", ""),
                            "dataset_id": c.get("dataset_id", ""),
                            "dataset_name": c.get("dataset_name", ""),
                            "document_name": c.get("document_name", ""),
                            "similarity": c.get("similarity", 0),
                        }
                        for c in data.get("data", {}).get("chunks", [])
                    ]
            return {"error": "Search failed"}
        except Exception as e:
            return {"error": str(e)}

    def search_mech_term(self, term):
        """搜索机械设计术语知识库。

        协同 MySQL 查询：
        1. 先查 MySQL 表（通过调用者实现）
        2. MySQL 未命中时调用此方法进行语义搜索
        """
        if not self._available():
            return {"error": "RAGFlow not configured."}
        try:
            resp = httpx.post(
                self.base_url + "/api/v1/retrieval",
                headers=self._headers,
                json={
                    "question": term,
                    "dataset_ids": [MECH_TERMS_DATASET_ID],
                    "top_k": 3
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    chunks = data.get("data", {}).get("chunks", [])
                    if chunks:
                        return {
                            "source": "ragflow",
                            "term": term,
                            "results": [
                                {
                                    "content": c.get("content", ""),
                                    "similarity": c.get("similarity", 0),
                                    "document": c.get("document_name", ""),
                                }
                                for c in chunks
                            ]
                        }
                    return {"source": "ragflow", "term": term, "results": [], "message": "未找到相关术语"}
            return {"error": "RAGFlow search failed"}
        except Exception as e:
            return {"error": str(e)}

    def lookup_term_hybrid(self, term):
        """混合查询：MySQL 精确匹配 + RAGFlow 语义搜索。

        协同逻辑：
        1. 先查 MySQL 表（精确/别名匹配）
        2. MySQL 未命中 → 调用 RAGFlow 语义搜索
        3. 合并结果
        """
        # 1. 先查 MySQL
        from ..prompts.mech_terms import lookup_term
        mysql_result = lookup_term(term)

        # 如果 MySQL 找到了（不包含"未找到"），直接返回
        if "未找到" not in mysql_result:
            return {
                "source": "mysql",
                "term": term,
                "content": mysql_result
            }

        # 2. MySQL 未命中，查 RAGFlow
        ragflow_result = self.search_mech_term(term)

        if isinstance(ragflow_result, dict) and ragflow_result.get("results"):
            # RAGFlow 找到了
            content = "【RAGFlow 知识库】\n"
            for r in ragflow_result["results"][:2]:
                content += r["content"][:500] + "\n---\n"
            return {
                "source": "ragflow",
                "term": term,
                "content": content
            }

        # 3. 都没找到
        return {
            "source": "none",
            "term": term,
            "content": "术语表和知识库中均未找到'%s'。请按字面理解，或向用户确认其含义。" % term
        }

    def list_datasets(self):
        if not self._available():
            return {"error": "RAGFlow not configured."}
        try:
            resp = httpx.get(self.base_url + "/api/v1/datasets", headers=self._headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return [
                        {"id": d["id"], "name": d["name"],
                         "chunk_count": d.get("chunk_count", 0),
                         "description": d.get("description", "")}
                        for d in data.get("data", [])
                    ]
            return {"error": "API error"}
        except Exception as e:
            return {"error": str(e)}

    def create_dataset(self, name, description=""):
        if not self._available():
            return {"error": "RAGFlow not configured."}
        try:
            resp = httpx.post(
                self.base_url + "/api/v1/datasets",
                headers=self._headers,
                json={"name": name, "description": description},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    d = data.get("data", {})
                    return {"id": d.get("id", ""), "name": d.get("name", name)}
            return {"error": "Create failed"}
        except Exception as e:
            return {"error": str(e)}

    def upload_document(self, dataset_id, file_path):
        if not self._available():
            return {"error": "RAGFlow not configured."}
        try:
            with open(file_path, "rb") as f:
                files = {"file": (Path(file_path).name, f, "application/octet-stream")}
                resp = httpx.post(
                    self.base_url + "/api/v1/datasets/" + dataset_id + "/documents",
                    headers=self._headers,
                    files=files,
                    timeout=60,
                )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return {"document_ids": [d.get("id", "") for d in data.get("data", [])]}
            return {"error": "Upload failed"}
        except Exception as e:
            return {"error": str(e)}
