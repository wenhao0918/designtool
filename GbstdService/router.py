"""查询路由:q → 国标分类。

规则:
  ① 显式 category 参数优先(调用方指定,不分类);
  ② 否则关键词计分:命中分类关键词数最多者胜;
  ③ 全零 → 默认分类(当前唯一有内容的 draw),响应中标记 default 兜底。
"""

DEFAULT_CATEGORY = "draw"


def classify(q, catalog):
    """返回 (category, score, matched_keywords)。仅路由绑定了库的分类。"""
    best, best_score, best_kw = DEFAULT_CATEGORY, 0, []
    for name in sorted(catalog):
        entry = catalog[name]
        if not entry.get("dataset_id"):
            continue
        hits = [k for k in entry.get("keywords", []) if k and k in q]
        if len(hits) > best_score:
            best, best_score, best_kw = name, len(hits), hits
    return best, best_score, best_kw
