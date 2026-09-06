"""知音(Zhiyin)服务——同时支持 HTTP API 和 MCP。

架构:
- FastAPI 定义业务端点:POST /zhiyin/interpret(语义解析)、GET /health
- fastapi-mcp(FastApiMCP)把 FastAPI 端点自动转成 MCP 工具,挂载在 /mcp
- 一个服务两种消费方式:HTTP 给前端/其他服务,MCP 给 LLM/Agent

运行(dev 环境,fastapi-mcp 装在 dev):
  /usr/local/Caskroom/miniconda/base/envs/dev/bin/python mcp_server.py
或:
  PYTHONPATH=/usr/local/Caskroom/miniconda/base/envs/dev/lib/python3.12/site-packages python3 mcp_server.py

环境变量:
  ZHIYIN_PORT      HTTP 端口(默认 5001)
  RAGFLOW_BASE_URL RAGFlow 地址(默认 http://localhost:1800)
  RAGFLOW_API_KEY  RAGFlow key(可选)
"""

import os
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from rag.ragflow_client import RAGFlowClient

app = FastAPI(title="Zhiyin", description="知音——设计意图术语映射(API + MCP)")

rag_client = RAGFlowClient(
    base_url=os.getenv("RAGFLOW_BASE_URL", "http://localhost:1800"),
    api_key=os.getenv("RAGFLOW_API_KEY", ""),
    collection_id=os.getenv("RAGFLOW_COLLECTION_ID", "default"),
)


class InterpretRequest(BaseModel):
    text: str
    session_id: Optional[str] = None
    scene: Optional[str] = None


def ner_stub(text: str) -> Dict[str, Any]:
    """轻量 NER/slot 提取(桩实现,后续可换模型)。"""
    spec_match = re.search(r"M\d+", text, flags=re.IGNORECASE)
    nums = re.findall(r"\b\d+\b", text)
    return {"fastener_spec": spec_match.group(0) if spec_match else None, "numbers": nums}


@app.get("/health")
def health():
    return {"name": "zhiyin", "status": "ok"}


@app.post("/zhiyin/interpret")
def interpret(req: InterpretRequest):
    """自然语言 → 标准术语上下文。

    优先 RAG 混合检索;RAG 不可用时降级返回低置信度 + 澄清问题。
    """
    text = req.text
    session_id = req.session_id
    scene = req.scene
    ner = ner_stub(text)

    try:
        results = rag_client.hybrid_search(text, top_k=5)
        identified: List[str] = []
        scores: List[float] = []
        for r in results:
            if isinstance(r, dict):
                meta = r.get("meta", {})
                term = meta.get("standard_term") or r.get("text") or meta.get("title")
                if term:
                    identified.append(term)
                score = r.get("score")
                if isinstance(score, (int, float)):
                    scores.append(score)
        confidence = float(sum(scores) / len(scores)) if scores else 0.5
        return {
            "terms": {"identified": identified, "resolved": {}},
            "clarifying_questions": [],
            "confidence": confidence,
            "context": {"fastener_spec": ner.get("fastener_spec"), "scene": scene, "session_id": session_id},
        }
    except Exception:
        # RAG 不可用——降级
        return {
            "terms": {"identified": [], "resolved": {}},
            "clarifying_questions": ["无法访问语义检索服务,请提供更多上下文或使用标准术语。"],
            "confidence": 0.25,
            "context": {"fastener_spec": ner.get("fastener_spec"), "scene": scene, "session_id": session_id},
        }


# ===== MCP:把 FastAPI 端点自动转成 MCP 工具,挂载 /mcp =====
try:
    from fastapi_mcp import FastApiMCP

    mcp = FastApiMCP(app, name="Zhiyin", description="知音——设计意图术语映射")
    mcp.mount(mount_path="/mcp")
    MCP_ENABLED = True
except Exception as e:  # pragma: no cover
    MCP_ENABLED = False
    print("fastapi-mcp 不可用,MCP 未挂载(HTTP API 仍可用): {}".format(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("ZHIYIN_PORT", 5001)), log_level="info")
