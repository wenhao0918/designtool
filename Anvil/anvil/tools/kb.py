"""国标知识库工具(Agent 用):检索 + 清洗 + 合规检查。

数据流:query_standard → kbservice(8101) → RAGFlow → 三层清洗 → 干净片段
清洗层(C):
  ① 相关度过滤  score < MIN_SCORE 丢弃
  ② 溯源降权    "替代内容"标记 → 标注警示(LLM 输出时带"待核对")
  ③ 结构化整形  紧凑格式、限长、按 score 取 top2

check_design_compliance(B2):对模型要素(孔径/壁厚/公差标注等)构造
查询,回命中条款做合规对照——diff-aware 由调用方(LLM)只传本轮改动的
要素实现,工具本身无状态。
"""

import json
import os
import re
import urllib.parse
import urllib.request

KB_URL = os.environ.get("KBSERVICE_URL", "http://127.0.0.1:8101")
GBSTD_URL = os.environ.get("GBSTD_SERVICE_URL", "http://127.0.0.1:8104")

# 清洗参数(可调)
MIN_SCORE = 0.35          # ① 相关度阈值
MAX_HITS = 2              # ③ 注入条数上限
HIT_MAX_CHARS = 300       # ③ 单条限长


def _kb_get(path, params, timeout=20):
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(KB_URL + path + "?" + qs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _clean_hits(raw_hits):
    """三层清洗:过滤 → 溯源标记 → 整形。"""
    out = []
    for h in raw_hits:
        score = h.get("score", 0)
        if score < MIN_SCORE:
            continue
        content = re.sub(r"\s+", " ", h.get("content", "")).strip()
        source = h.get("source", "")
        is_replacement = "替代" in content[:60]
        # 截断到条款头+首句(头 300 字内信息密度最高)
        if len(content) > HIT_MAX_CHARS:
            content = content[:HIT_MAX_CHARS] + "…"
        conf = "替代内容(待原文核对)" if is_replacement else "标准内容"
        out.append({
            "source": source,
            "confidence": conf,
            "score": round(score, 2),
            "content": content,
        })
        if len(out) >= MAX_HITS:
            break
    return out


def _gbstd_query_hits(query, category, top_k=5):
    """GbstdService(8104) 分类路由检索。失败返回 None(降级 kbservice)。"""
    req = urllib.request.Request(
        GBSTD_URL + "/api/gbstd/query",
        data=json.dumps({"q": query, "category": category,
                         "top_k": top_k}).encode(),
        method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=25) as r:
        out = json.loads(r.read().decode())
    # 统一为 _clean_hits 输入形态(score/source/content)
    return [{"score": h.get("score", 0), "source": h.get("source", ""),
             "content": h.get("content", "")} for h in out.get("hits", [])]


def query_standard(query: str, domain: str = "gbstd", category: str = "") -> str:
    """检索国标条款,返回清洗后的紧凑片段(供 LLM 直接引用)。

    category 显式给出 → 走 GbstdService(8104) 分类路由
    (一分类一 RAGFlow 库:draw/fasteners/materials/...);
    失败降级 kbservice(8101) 默认域。
    """
    raw_hits = None
    if category:
        try:
            raw_hits = _gbstd_query_hits(query, category)
        except Exception:
            raw_hits = None  # 降级 kbservice 路径
    if raw_hits is None:
        try:
            r = _kb_get("/api/kb/search", {"q": query, "top_k": 5, "domain": domain})
            raw_hits = r.get("hits", [])
        except Exception as e:
            return json.dumps({"ok": False, "error": "知识库服务不可用: %s" % e},
                              ensure_ascii=False)
    hits = _clean_hits(raw_hits)
    if not hits:
        return json.dumps({
            "ok": True, "hits": [],
            "note": "无相关命中(score≥%.2f)。可换关键词重试;确实无标准"
                    "覆盖时按工程惯例处理并在回复中说明'无标准依据'。" % MIN_SCORE,
        }, ensure_ascii=False)
    return json.dumps({"ok": True, "hits": hits}, ensure_ascii=False)


def check_design_compliance(features: list) -> str:
    """设计要素合规对照。

    features: [{kind, query, value}] 如
      {"kind": "孔径", "query": "孔径 优先数系列 标准", "value": "Φ11"}
    对每个要素检索条款,返回 命中/无依据 结论列表(不判定对错——
    数值合规判断由 LLM 结合条款做,工具只提供依据)。
    """
    results = []
    for f in features[:8]:  # 上限防爆
        q = f.get("query") or f.get("kind", "")
        try:
            r = _kb_get("/api/kb/search", {"q": q, "top_k": 3, "domain": "gbstd"})
            hits = _clean_hits(r.get("hits", []))
        except Exception as e:
            hits = [{"source": "-", "confidence": "检索失败",
                     "score": 0, "content": str(e)[:120]}]
        results.append({
            "kind": f.get("kind", "?"),
            "value": f.get("value", ""),
            "references": hits or "无标准命中",
        })
    return json.dumps({"ok": True, "results": results}, ensure_ascii=False)


# ---------- 工具定义(LLM function calling schema) ----------

def tool_def_query_standard():
    return {
        "type": "function",
        "function": {
            "name": "query_standard",
            "description": (
                "检索国标知识库(按分类路由:draw=制图与标注——幅面/比例/图线/"
                "字体/尺寸注法/公差配合/粗糙度/螺纹/焊缝等 GB/T;"
                "fasteners=紧固件;materials=材料;safety=安全)。\n"
                "【何时调用】①用户没给的参数需要补全(孔径系列/壁厚/公差等级/材料)——"
                "先查再定,禁止凭记忆拍数字;②涉及标注/画法规则时查依据。\n"
                "【输出要求】引用命中内容时,回复中标注 [依据 GB/T xxx];"
                "命中标注'替代内容'时追加'(待原文核对)'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询,如'未注尺寸公差等级'、"
                                       "'均布孔标注方法'、'孔径优先数系列'",
                    },
                    "domain": {
                        "type": "string",
                        "description": "知识域,默认 gbstd(国标)",
                        "enum": ["gbstd", "mechterms", "materials"],
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "国标分类(经 GbstdService 分类路由,一分类一知识库)。"
                            "不确定时留空自动路由;all=全分类联检。"
                        ),
                        "enum": ["draw", "fasteners", "materials", "safety", "all"],
                    },
                },
                "required": ["query"],
            },
        },
    }


def tool_def_check_compliance():
    return {
        "type": "function",
        "function": {
            "name": "check_design_compliance",
            "description": (
                "设计要素合规对照:对(本轮修改涉及的)设计要素检索国标依据。\n"
                "【何时调用】每轮建模后,只对本轮新增/修改的要素调用"
                "(diff-aware,不重复查未改动的);用户要求出图前做全量检查。\n"
                "【输出要求】对照条款判断是否合规;合规在回复中标[依据 GB/T xxx],"
                "不合规给出⚠️提醒+建议值;无命中的要素说明'无标准依据,按工程惯例'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "features": {
                        "type": "array",
                        "description": "要检查的设计要素列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string",
                                         "description": "要素类型,如 孔径/壁厚/公差/孔距"},
                                "query": {"type": "string",
                                          "description": "检索词,如'孔径优先数系列'"},
                                "value": {"type": "string",
                                          "description": "当前值,如 Φ11"},
                            },
                            "required": ["kind", "value"],
                        },
                    },
                },
                "required": ["features"],
            },
        },
    }


ALL_KB_TOOLS = [tool_def_query_standard(), tool_def_check_compliance()]
