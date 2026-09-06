import os
from typing import List, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .interface import RAGClientInterface


class RAGFlowClient(RAGClientInterface):
    """Minimal HTTP client for RAGFlow-like services.

    This implementation is intentionally lightweight: it wraps POST calls
    to configurable endpoints and returns the JSON payloads as-is.
    Adjust parsing to match the actual RAGFlow deployment responses.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, collection_id: Optional[str] = None, timeout: int = 5):
        # Default RAGFlow HTTP service address (change via RAGFLOW_BASE_URL env)
        self.base_url = base_url or os.getenv("RAGFLOW_BASE_URL", "http://localhost:1800")
        self.api_key = api_key or os.getenv("RAGFLOW_API_KEY", "")
        self.collection_id = collection_id or os.getenv("RAGFLOW_COLLECTION_ID", "default")
        self.timeout = timeout

        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.3, status_forcelist=(500, 502, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def _post(self, path: str, payload: Dict) -> Dict:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        resp = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        payload = {"collection_id": self.collection_id, "query": query, "top_k": top_k}
        try:
            data = self._post("/api/v1/retrieval", payload)
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception:
            raise

    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        payload = {"entity": entity, "relation": relation}
        try:
            data = self._post("/api/v1/graph/query", payload)
            return data.get("items", []) if isinstance(data, dict) else data
        except Exception:
            raise

    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        payload = {"collection_id": self.collection_id, "query": query, "top_k": top_k}
        try:
            data = self._post("/api/v1/hybrid_search", payload)
            # fallback to retrieval shape
            if isinstance(data, dict):
                return data.get("results", data.get("items", []))
            return data
        except Exception:
            # last-resort fallback: call semantic_search
            return self.semantic_search(query, top_k=top_k)
