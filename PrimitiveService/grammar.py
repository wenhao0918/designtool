"""设计语言文法 V0 —— 词汇表 + 句子校验。

单一事实源:四张表(体元/特征算子/关系谓词/句子结构)只定义在本文件,
prompt 词汇说明经 GET /api/grammar 动态注入,杜绝手写清单与实现脱节
(2026-09-01"模型能力测试"事故教训)。

设计立场(《设计语言演算架构_V0.md》):
- LLM 只把用户话翻译成本文法定义下的句子,语法校验是可判定问题,无概率;
- 演算归 resolver,判定归 constraints,LLM 永不参与"怎么建模"。
"""

# ============ 词汇表(冻结;新词条只在此处与 resolver 同步新增) ============

# 体元:数学定义 + 锚点语义。anchor: sphere=球心 / box,cylinder=底面中心
BODY_KINDS = {
    "sphere":   {"params": {"r":  float}, "anchor": "center",       "desc": "球体:{x: |x−O| ≤ r}"},
    "cylinder": {"params": {"r":  float, "h": float}, "anchor": "bottom_center", "desc": "圆柱:{x²+y²≤r², 0≤z≤h}"},
    "box":      {"params": {"L":  float, "W": float, "H": float}, "anchor": "bottom_center", "desc": "长方体:[0,L]×[0,W]×[0,H]"},
}

# 特征算子:通用数学算子,作用于任何体
FEATURE_OPS = {
    "shell": {"params": {"t": float}, "desc": "壳:体 ∖ 体.offset(−t),通用掏壳"},
}

# 关系谓词:约束方程,闭式解
RELATIONS = {
    "rests_on_centered": {"params": {}, "a_over_b": True, "desc": "a 贴合置于 b 顶面中心:z(a.bottom)=z(b.top), xy 对中"},
    "coaxial_z":         {"params": {}, "desc": "a 与 b 轴线同为 (x0,y0) 平行 Z 轴"},
    "gap_z":             {"params": {"g": float}, "a_over_b": True, "desc": "a 底面高于 b 顶面 g"},
}

LANG = "dsl.v0"


def describe():
    """词汇表说明(prompt 动态注入用;词汇表唯一出口)。"""
    return {
        "lang": LANG,
        "body_kinds": {k: {"params": sorted(v["params"]), "desc": v["desc"]}
                       for k, v in BODY_KINDS.items()},
        "feature_ops": {k: {"params": sorted(v["params"]), "desc": v["desc"]}
                        for k, v in FEATURE_OPS.items()},
        "relations": {k: {"params": sorted(v["params"]), "desc": v["desc"]}
                      for k, v in RELATIONS.items()},
    }


def _check_params(where, name, spec, got, errors):
    """参数完备性+类型+多余项:可判定,无默认值——翻译必须完整。"""
    for p, t in spec.items():
        if p not in got:
            errors.append("%s '%s' 缺参数 %s(%s)" % (where, name, p, t.__name__))
        elif not isinstance(got[p], (int, float)) or isinstance(got[p], bool):
            errors.append("%s '%s' 参数 %s 必须为数值" % (where, name, p))
        elif t is float and got[p] <= 0:
            errors.append("%s '%s' 参数 %s 必须为正数" % (where, name, p))
    for p in got:
        if p not in spec:
            errors.append("%s '%s' 未知参数 %s(词汇表中不存在)" % (where, name, p))


def validate(sentence):
    """句子合法性判定。返回 (ok, errors[], normalized)。

    可判定三件事:词汇∈表 / 结构合文法 / 参数完备且为正。
    不做几何计算(那是 resolver 的事)。
    """
    errors = []
    if not isinstance(sentence, dict):
        return False, ["句子必须是 JSON 对象"], None
    if sentence.get("lang") != LANG:
        errors.append("lang 必须为 '%s'" % LANG)

    bodies = sentence.get("bodies")
    if not isinstance(bodies, list) or not bodies:
        errors.append("bodies 必须为非空数组")
        bodies = []

    seen = set()
    norm_bodies = []
    for b in bodies:
        if not isinstance(b, dict):
            errors.append("body 条目必须为对象")
            continue
        bid = b.get("id")
        if not bid or not isinstance(bid, str) or not bid.isascii():
            errors.append("body.id 必须为非空 ASCII 标识符")
            continue
        if bid in seen:
            errors.append("body.id '%s' 重复" % bid)
            continue
        seen.add(bid)
        kind = b.get("kind")
        if kind not in BODY_KINDS:
            errors.append("body '%s' kind '%s' 不在体元表中(可用: %s)"
                          % (bid, kind, ",".join(BODY_KINDS)))
            continue
        _check_params("body", bid, BODY_KINDS[kind]["params"],
                      {k: v for k, v in b.items() if k in BODY_KINDS[kind]["params"]},
                      errors)
        feats = b.get("features", [])
        if not isinstance(feats, list):
            errors.append("body '%s' features 必须为数组" % bid)
            feats = []
        norm_feats = []
        for f in feats:
            if not isinstance(f, dict) or f.get("op") not in FEATURE_OPS:
                errors.append("body '%s' 特征算子不在算子表中(可用: %s)"
                              % (bid, ",".join(FEATURE_OPS)))
                continue
            op = f["op"]
            _check_params("feature", "%s.%s" % (bid, op), FEATURE_OPS[op]["params"],
                          {k: v for k, v in f.items() if k in FEATURE_OPS[op]["params"]},
                          errors)
            norm_feats.append(f)
        norm_bodies.append({"id": bid, "kind": kind, "params": b, "features": norm_feats})

    rels = sentence.get("relations", [])
    if not isinstance(rels, list):
        errors.append("relations 必须为数组")
        rels = []
    norm_rels = []
    for r in rels:
        if not isinstance(r, dict) or r.get("rel") not in RELATIONS:
            errors.append("关系 '%s' 不在关系谓词表中(可用: %s)"
                          % (r.get("rel") if isinstance(r, dict) else r,
                             ",".join(RELATIONS)))
            continue
        rel = r["rel"]
        for side in ("a", "b"):
            if r.get(side) not in seen:
                errors.append("关系 %s 引用了不存在的 body id '%s'" % (rel, r.get(side)))
        norm_rels.append(r)

    ok = not errors
    normalized = {"lang": LANG, "bodies": norm_bodies, "relations": norm_rels} if ok else None
    return ok, errors, normalized
