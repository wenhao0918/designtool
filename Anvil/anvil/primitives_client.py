"""PrimitiveService(8103)统一客户端 — 原语体系独立后的 Anvil 侧接入口。

职责(2026-08-27,修复 Anvil 同步缺口):
1. list_primitives 优先走 8103(动态注册表:进化出的新原语 LLM 即时可见),
   服务不可用时降级本地 registry,保证会话不中断;
2. validate 封装:降级本地生成前的硬律校验(规则跟着原语走,降级不降规则);
3. 带短 TTL 缓存,避免 agent 每轮对话都打 8103。

失败语义:一切网络异常 → None(调用方自行降级本地),绝不抛出。
"""

import os
import json
import time
import urllib.request
import urllib.error

PRIMITIVESERVICE_URL = os.environ.get(
    "PRIMITIVESERVICE_URL", "http://127.0.0.1:8103")

_LIST_CACHE_TTL = 30  # 秒;8103 reload 版本变化最长 30s 后被感知
_list_cache = {"ts": 0, "data": None}


def _request(path, body=None, timeout=5):
    """POST JSON → dict;任何异常返回 None(调用方降级)。"""
    url = PRIMITIVESERVICE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _request_json(path, body=None, timeout=5):
    """POST JSON → (status_code, dict|None);HTTPError 读 body(422 携带打回详情)。"""
    url = PRIMITIVESERVICE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception:
        return None, None


def get_grammar():
    """设计语言文法词汇表(prompt 动态注入唯一来源);不可用返回 None。"""
    return _request("/api/grammar")


def resolve_intent(sentence):
    """设计语言句子 → 8103 演算器(MCP 同构端点 /api/intent/resolve)。

    返回 {status: ok|violation|invalid, parts/checks/trace|errors};
    服务不可用返回 None。
    """
    code, out = _request_json("/api/intent/resolve", {"sentence": sentence, "compose": False})
    if code is None:
        return None
    if code == 200:
        return out
    detail = (out or {}).get("detail") or {}
    if isinstance(detail, dict) and detail.get("errors"):
        return {"status": "invalid", "errors": detail["errors"],
                "message": detail.get("message", "句子不合法")}
    return {"status": "invalid",
            "errors": [str(detail) or ("HTTP %s" % code)],
            "message": "演算请求被拒绝"}


def list_primitives(use_cache=True):
    """原语清单:8103 优先(含动态原语),失败降级本地 registry。

    返回与本地 list_primitives 同构:{type: {description, params}}。
    """
    now = time.time()
    if use_cache and _list_cache["data"] is not None \
            and now - _list_cache["ts"] < _LIST_CACHE_TTL:
        return _list_cache["data"]
    out = _request("/api/primitives/list")
    if out and out.get("primitives"):
        _list_cache["ts"] = now
        _list_cache["data"] = out["primitives"]
        return _list_cache["data"]
    from .tools.primitives import list_primitives as _local
    return _local()


def validate(parts, joints=None):
    """约束校验(8103)。返回违规列表;服务不可用返回 None(调用方降级本地校验)。"""
    out = _request("/api/primitives/validate",
                   {"parts": parts, "joints": joints or []})
    if out and "violations" in out:
        return out["violations"]
    return None


def hard_failures(parts, joints=None):
    """仅 hard 违规(降级路径拒绝建模用)。服务不可用 → 本地 constraints 校验。"""
    v = validate(parts, joints)
    if v is None:
        try:
            from .tools import constraints as _c
            v = _c.validate(parts, joints or [])
        except Exception:
            return []  # 本地校验也缺(旧部署) → 放行,保持降级链路可用
    return [x for x in v if x.get("level") == "hard"]


def invalidate_cache():
    """8103 reload/新原语发布后可调用,立即可见。"""
    _list_cache["ts"] = 0
