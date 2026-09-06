"""DraftEngine VLM 标注决策:让视觉模型看中间态图纸,决定该标哪些尺寸。

约定(与 Anvil 生态一致,不复制密钥):
- 环境变量 DRAFTENGINE_VISION_{BASE_URL,API_KEY,MODEL}
- 回退 ANVIL_VISION_*(Anvil .env 同款)
- 再回退直接读 ../Anvil/.env

VLM 只做"标什么"的决策(输出 JSON 意图列表),
"怎么标/标在哪"由 core 用确定性几何计算完成——AI 不碰坐标。
"""

import json
import os
import re
import urllib.error
import urllib.request

PROMPT = """你是机械制图工程师。这是一张零件三视图工程图纸(第一角投影:主视图左上、
俯视图正下、左视图右侧;红色为已有内容,黑色实线为可见轮廓,虚线为隐藏线)。

请根据视图判断这张图纸【需要哪些尺寸标注】,只输出 JSON(不要其他文字):
{"annotations": [
  {"kind": "overall-length"|"overall-width"|"overall-height"
        |"hole-position"|"hole-dia"|"boss-height"|"feature",
   "view": "top"|"front"|"left",
   "target": <hole/boss 在下方特征列表中的下标,kind 为 hole-*/boss-* 时必填>,
   "reason": "简短理由(中文)"
  }]}

零件特征列表(下标即 target):%(features)s

标注原则(GB/T 4458):
1. 总体长/宽/高必标
2. 孔:标注定位尺寸(到基准边距离)与定形尺寸(直径),同规格孔标一次
3. 凸台/台阶:标注高度或深度
4. 不要重复标注同一尺寸
"""


def _load_env_file(path):
    """极简 .env 解析(KEY=VALUE)。"""
    cfg = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.*)\s*$", line.strip())
                if m and m.group(2):
                    cfg[m.group(1)] = m.group(2)
    except Exception:
        pass
    return cfg


# 已知 provider 的视觉模型映射(用 LLM key 降级时选型)
_VISION_MODEL_BY_PROVIDER = {
    "deepseek": "deepseek-v4-flash-vision-exp",
    "moonshot": "moonshot-v1-128k-vision-preview",
}


def vision_cfg():
    """返回 (base_url, api_key, model);不可用返回 None。

    优先级:DRAFTENGINE_VISION_* > ANVIL_VISION_* > ANVIL_LLM_*(自动配视觉模型)。
    """
    env = dict(os.environ)
    here = os.path.dirname(os.path.abspath(__file__))
    anvil_env = os.path.join(here, "..", "..", "Anvil", ".env")
    env.update({k: v for k, v in _load_env_file(anvil_env).items() if not env.get(k)})

    v_base = (env.get("DRAFTENGINE_VISION_BASE_URL") or env.get("ANVIL_VISION_BASE_URL") or "").rstrip("/")
    v_key = env.get("DRAFTENGINE_VISION_API_KEY") or env.get("ANVIL_VISION_API_KEY") or ""
    v_model = env.get("DRAFTENGINE_VISION_MODEL") or env.get("ANVIL_VISION_MODEL") or ""
    if v_base and v_key and v_model:
        return v_base, v_key, v_model

    # 降级:复用 LLM key,按 provider 选视觉模型
    base = (env.get("ANVIL_LLM_BASE_URL") or "").rstrip("/")
    key = env.get("ANVIL_LLM_API_KEY") or ""
    if not (base and key):
        return None
    model = v_model
    if not model:
        for provider, m in _VISION_MODEL_BY_PROVIDER.items():
            if provider in base:
                model = m
                break
    if not model:
        return None
    return base, key, model


def _encode_png_b64(png_path):
    import base64
    with open(png_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _llm_fallback_cfg():
    """LLM key 降级配置(与 vision_cfg 不同时才有意义)。"""
    env = dict(os.environ)
    here = os.path.dirname(os.path.abspath(__file__))
    anvil_env = os.path.join(here, "..", "..", "Anvil", ".env")
    env.update({k: v for k, v in _load_env_file(anvil_env).items() if not env.get(k)})
    base = (env.get("ANVIL_LLM_BASE_URL") or "").rstrip("/")
    key = env.get("ANVIL_LLM_API_KEY") or ""
    if not (base and key):
        return None
    model = ""
    for provider, m in _VISION_MODEL_BY_PROVIDER.items():
        if provider in base:
            model = m
            break
    return (base, key, model) if model else None


def _post_chat(base, key, model, body, timeout):
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def suggest_annotations(png_path, meta, timeout=90):
    """VLM 看中间态图纸 → 标注意图列表。

    主配置 401/403(key 失效)时自动降级 LLM key 重试。
    返回 {"annotations": [...]} 或 {"error": ...}。
    """
    cfg = vision_cfg()
    if not cfg:
        return {"error": "VLM 未配置(DRAFTENGINE_VISION_*/ANVIL_VISION_*)"}
    cfgs = [cfg]
    fb = _llm_fallback_cfg()
    if fb and (fb[0], fb[2]) != (cfg[0], cfg[2]):
        cfgs.append(fb)

    feats = json.dumps(meta.get("vlm_features") or meta.get("holes", []),
                       ensure_ascii=False)
    body = {
        "model": None,  # 每次填充
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + _encode_png_b64(png_path)}},
                {"type": "text", "text": PROMPT % {"features": feats}},
            ],
        }],
    }
    last_err = ""
    for base, key, model in cfgs:
        body["model"] = model
        try:
            data = _post_chat(base, key, model, body, timeout)
            text = data["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                last_err = "VLM 返回非 JSON: " + text[:120]
                continue
            out = json.loads(m.group(0))
            out.setdefault("annotations", [])
            out["vlm_model"] = model
            return out
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s" % e.code
            if e.code in (401, 403):
                continue  # key 失效 → 试下一个配置
        except Exception as e:
            last_err = str(e)[:200]
    return {"error": "VLM 调用失败: %s" % last_err}
