"""国标文档采集与入库管线。

用法(三步):
  # 1. 初始化标准目录(从 00_CATALOG.md 解析标准清单,建骨架)
  python -m gbstd.collect init

  # 2. 添加内容:把某标准的内容写成 docs/GB_T_xxx/sections/*.md
  #    (自动校验:每个 section 必须含标准号头部,禁止无头chunk)
  python -m gbstd.collect validate GB_T_4458.4-2003

  # 3. 入库 RAGFlow(整库或单标准;manual 模式,一节一chunk)
  python -m gbstd.collect push                # 全部未入库的
  python -m gbstd.collect push GB_T_4458.4-2003

设计要点(讨论定稿):
- 权威分级:meta.json 记 source/replacement;替代内容必须显式标记
- 分块不跨条:每节自包含,头部强制"【GB/T 号 · 条款】",validate 断言
- 幂等:push 过的(meta.pushed)跳过;RAGFlow 文档名=目录名
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")

RAGFLOW_URL = os.environ.get("RAGFLOW_URL", "http://localhost:1800")
RAGFLOW_API_KEY = os.environ.get(
    "RAGFLOW_API_KEY",
    "ragflow-9IGG6y08i6itpjXiF4ae_QA82eOzkLbt5swQWGVB0EM")
RAGFLOW_DATASET = os.environ.get(
    "RAGFLOW_DATASET", "64cc97e4a0ef11f19e5b7eb885516d10")


def _req(method, path, body=None, is_json=True, timeout=30):
    url = RAGFLOW_URL + path
    data = json.dumps(body).encode() if (body is not None and is_json) else body
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + RAGFLOW_API_KEY)
    if data is not None:
        req.add_header("Content-Type",
                       "application/json" if is_json else "multipart/form-data; boundary=----kb")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------- 目录解析 ----------

def parse_catalog():
    """00_CATALOG.md → [{code, name, status, priority}]"""
    out = []
    path = os.path.join(DOCS, "00_CATALOG.md")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\|\s*(GB/T\s*[\d.]+(?:-[±\d]+)?)\s*\|([^|]+)\|([^|]*)\|([^|]*)\|", line)
            if not m:
                continue
            code = re.sub(r"\s+", "", m.group(1))
            name = m.group(2).strip()
            status = m.group(3).strip()
            priority = m.group(4).strip()
            if not name or name.startswith("—") or "已列" in name:
                continue
            out.append({"code": code, "name": name,
                        "status": status, "priority": priority})
    return out


def dir_name(code):
    """GB/T 4458.4-2003 → GB_T_4458.4-2003"""
    return code.replace("/", "_").replace(" ", "")


def cmd_init(force=False):
    stds = parse_catalog()
    made = 0
    for s in stds:
        d = os.path.join(DOCS, dir_name(s["code"]))
        meta_path = os.path.join(d, "meta.json")
        if os.path.exists(meta_path) and not force:
            continue
        os.makedirs(os.path.join(d, "sections"), exist_ok=True)
        meta = {
            "code": s["code"], "name": s["name"],
            "status": s["status"] or "待收",
            "priority": s["priority"] or "P1",
            "source": "openstd.samr.gov.cn",
            "source_url": "https://openstd.samr.gov.cn/bzgk/gb/std_list?p.p2=" + s["code"],
            "collected": None, "replacement": False, "pushed": False,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        made += 1
    print("init: %d 个标准目录就绪(共 %d 项)" % (made, len(stds)))
    for s in stds:
        d = dir_name(s["code"])
        has = any(".md" in f for f in os.listdir(os.path.join(DOCS, d, "sections")))
        print("  %-24s %-8s %-6s %s" % (s["code"], s["status"], s["priority"],
                                        "✓有内容" if has else ""))


# ---------- 校验(分块不跨条) ----------

def validate_one(code):
    """校验一个标准目录:
    1. 每节第一行必须含标准号(自包含头部)
    2. 每节 ≤ 1500 字(naive 兜底也不会被二切)
    3. meta.json 存在且 replacement 标记与实际一致
    """
    d = os.path.join(DOCS, dir_name(code))
    if not os.path.isdir(d):
        return [ "%s: 目录不存在" % code ]
    errs = []
    meta_path = os.path.join(d, "meta.json")
    if not os.path.exists(meta_path):
        errs.append("%s: 缺 meta.json" % code)
        return errs
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    sec_dir = os.path.join(d, "sections")
    secs = sorted(f for f in os.listdir(sec_dir) if f.endswith(".md")) \
        if os.path.isdir(sec_dir) else []
    if not secs:
        errs.append("%s: 无 sections/*.md" % code)
        return errs
    code_norm = code.replace(" ", "")
    for fn in secs:
        p = os.path.join(sec_dir, fn)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        first = text.strip().splitlines()[0] if text.strip() else ""
        # 头部必须含标准号(允许【】/全角空格差异)
        head_norm = first.replace("【", "").replace("】", "").replace(" ", "")
        if code_norm not in head_norm:
            errs.append("%s/%s: 首行缺标准号头部: %r" % (code, fn, first[:50]))
        if len(text) > 1500:
            errs.append("%s/%s: 超 1500 字(%d),需再分条" % (code, fn, len(text)))
        if meta.get("replacement") and "替代" not in first:
            errs.append("%s/%s: replacement=True 但首行未标'替代'" % (code, fn))
    return errs


def cmd_validate(code=None):
    if code:
        errs = validate_one(code)
        if errs:
            print("\n".join("✗ " + e for e in errs)); sys.exit(1)
        print("✓ %s 校验通过" % code); return
    stds = parse_catalog()
    bad = 0
    for s in stds:
        d = os.path.join(DOCS, dir_name(s["code"]))
        if not os.path.isdir(d):
            continue
        if not any(f.endswith(".md") for f in os.listdir(os.path.join(d, "sections"))):
            continue
        errs = validate_one(s["code"])
        if errs:
            bad += 1
            print("\n".join("✗ " + e for e in errs))
        else:
            print("✓ %s" % s["code"])
    if bad:
        sys.exit(1)


# ---------- 推送 RAGFlow ----------

def _multipart_upload(doc_name, content):
    """RAGFlow 上传 markdown(手工 multipart,避免额外依赖)。"""
    boundary = "----kb"
    body = (
        ("--%s\r\n" % boundary) +
        ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % doc_name) +
        ("Content-Type: text/markdown\r\n\r\n") + content + ("\r\n--%s--\r\n" % boundary)
    ).encode()
    return _req("POST", "/api/v1/datasets/%s/documents" % RAGFLOW_DATASET,
                body=body, is_json=False)


def push_one(code):
    """一节一文档:每节独立上传为单独文档(短文档=单 chunk),
    从机制上杜绝跨条目切块(naive 对长文档会腰斩条款)。
    文档名:GB_T4458.4-2003#01_basic_rules.md
    """
    d = os.path.join(DOCS, dir_name(code))
    meta_path = os.path.join(d, "meta.json")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    sec_dir = os.path.join(d, "sections")
    secs = sorted(f for f in os.listdir(sec_dir) if f.endswith(".md"))
    if not secs:
        print("- %s: 无内容,跳过" % code)
        return False
    # 先清旧:同名多文档会重复(删除已有同名前缀文档)
    try:
        r = _req("GET", "/api/v1/datasets/%s/documents?page=1&page_size=100"
                 % RAGFLOW_DATASET)
        prefix = dir_name(code) + "#"
        for doc in ((r.get("data") or {}).get("docs") or []):
            if doc.get("name", "").startswith(prefix):
                _req("DELETE", "/api/v1/datasets/%s/documents" % RAGFLOW_DATASET,
                     body={"ids": [doc["id"]]})
    except Exception:
        pass
    doc_ids = []
    for fn in secs:
        content = open(os.path.join(sec_dir, fn), encoding="utf-8").read().strip()
        doc_name = "%s#%s" % (dir_name(code), fn)
        r = _multipart_upload(doc_name, content)
        if r.get("code") != 0:
            print("✗ %s 上传失败: %s" % (fn, r.get("message")))
            return False
        doc_ids += [x["id"] for x in (r.get("data") or [])]
    # 触发解析
    _req("POST", "/api/v1/datasets/%s/chunks" % RAGFLOW_DATASET,
         body={"document_ids": doc_ids})
    # 标记
    meta["pushed"] = True
    meta["pushed_date"] = date.today().isoformat()
    meta["ragflow_doc_ids"] = doc_ids
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("✓ %s 已入库(%d 节 = %d 文档)" % (code, len(secs), len(doc_ids)))
    return True


def cmd_push(code=None):
    stds = parse_catalog()
    n = 0
    for s in stds:
        if code and s["code"] != code:
            continue
        d = os.path.join(DOCS, dir_name(s["code"]))
        mp = os.path.join(d, "meta.json")
        if not os.path.exists(mp):
            continue
        meta = json.load(open(mp, encoding="utf-8"))
        if meta.get("pushed"):
            print("- %s: 已入库过,跳过" % s["code"])
            continue
        errs = validate_one(s["code"])
        if errs:
            print("✗ %s 校验未过,不入库: %s" % (s["code"], errs[0]))
            continue
        if push_one(s["code"]):
            n += 1
    print("push 完成: %d 个标准" % n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "validate", "push", "list"])
    ap.add_argument("code", nargs="?", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "init":
        cmd_init(a.force)
    elif a.cmd == "validate":
        cmd_validate(a.code)
    elif a.cmd == "push":
        cmd_push(a.code)
    elif a.cmd == "list":
        for s in parse_catalog():
            print("%-24s %-14s %-4s %s" % (s["code"], s["status"], s["priority"], s["name"]))


if __name__ == "__main__":
    main()
