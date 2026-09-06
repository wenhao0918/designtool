"""LLM integration — OpenAI-compatible API only.

Configure via environment variables:
  ANVIL_LLM_BASE_URL      (default: empty — LLM disabled)
  ANVIL_LLM_API_KEY       (default: empty)
  ANVIL_MODEL             (default: glm-4.5-flash)
  ANVIL_VISION_BASE_URL   (default: same as LLM)
  ANVIL_VISION_API_KEY    (default: same as LLM)
  ANVIL_VISION_MODEL      (default: glm-4.5-flash)
"""

import os


class ModelNotConfigured(Exception):
    """非测试用户未自配模型(推理/视觉),拒绝回退平台默认 key。"""

    def __init__(self, kind="inference"):
        self.kind = kind
        super().__init__(kind)


def _user_model_exempt(user_id):
    """是否豁免"必须自配模型"策略。

    豁免:无用户上下文(系统调用) / 用户不存在 / 测试用户(is_test) / admin。
    DB 异常时豁免(fail-open),避免数据库抖动导致全站 AI 不可用。
    """
    if not user_id:
        return True
    try:
        from anvil.db import User, SessionLocal
        db = SessionLocal()
        try:
            u = db.query(User).filter_by(id=user_id).first()
            if u is None:
                return True
            return bool(u.is_test) or (u.role or "") == "admin"
        finally:
            db.close()
    except Exception:
        return True


def _get_user_config(user_id, kind="text"):
    """从 model_configs 表读用户模型配置(用户自设 API key)。

    kind: inference(推理) / vision(视觉) / voice(语音)。
    返回 (base_url, api_key, model) 或 None(未配置 → 用 .env 回退)。
    """
    try:
        from anvil.db import ModelConfig, SessionLocal
        db = SessionLocal()
        try:
            row = db.query(ModelConfig).filter_by(user_id=user_id, kind=kind).first()
            if row and row.base_url and row.api_key:
                return row.base_url.rstrip("/"), row.api_key, row.model or ""
        finally:
            db.close()
    except Exception:
        pass
    return None


def _get_config(model_type="text", user_id=None):
    """Get API config for text/vision/voice model.

    用户自配(model_configs 表)优先。未自配时:
    - voice:回退 .env(不强制)
    - text/vision:测试用户/admin 回退 .env(即测试用户默认配置);
      非测试用户抛 ModelNotConfigured,必须先在设置页自配。
    """
    kind = "inference" if model_type == "text" else model_type
    if user_id:
        uc = _get_user_config(user_id, kind)
        if uc:
            return uc
        if model_type in ("text", "vision") and not _user_model_exempt(user_id):
            raise ModelNotConfigured(kind)
    if model_type == "vision":
        base_url = os.environ.get("ANVIL_VISION_BASE_URL") or os.environ.get("ANVIL_LLM_BASE_URL", "")
        api_key = os.environ.get("ANVIL_VISION_API_KEY") or os.environ.get("ANVIL_LLM_API_KEY", "")
        model_name = os.environ.get("ANVIL_VISION_MODEL") or os.environ.get("ANVIL_MODEL", "glm-4.5-flash")
    elif model_type == "voice":
        base_url = os.environ.get("ANVIL_VOICE_BASE_URL") or os.environ.get("ANVIL_LLM_BASE_URL", "")
        api_key = os.environ.get("ANVIL_VOICE_API_KEY") or os.environ.get("ANVIL_LLM_API_KEY", "")
        model_name = os.environ.get("ANVIL_VOICE_MODEL") or os.environ.get("ANVIL_MODEL", "glm-4.5-flash")
    else:
        base_url = os.environ.get("ANVIL_LLM_BASE_URL", "").rstrip("/")
        api_key = os.environ.get("ANVIL_LLM_API_KEY", "")
        model_name = os.environ.get("ANVIL_MODEL", "glm-4.5-flash")
    return base_url.rstrip("/"), api_key, model_name


def _record_usage(user_id, username, kind, model, response):
    """记录一次 LLM 调用的 token 消耗到 token_usage 表(失败静默)。"""
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total = prompt_tokens + completion_tokens
        if total <= 0:
            return
        from anvil.db import TokenUsage, SessionLocal
        db = SessionLocal()
        try:
            db.add(TokenUsage(
                user_id=user_id or 0,
                username=username or "",
                kind=kind,
                model=model or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def chat(messages, model=None, temperature=0.4, tools=None, stream=False, user_id=None):
    base_url, api_key, model_name = _get_config("text", user_id=user_id)
    if model:
        model_name = model

    if not base_url or not api_key:
        return _mock_response(
            "> LLM not configured.\n\n"
            "Set `ANVIL_LLM_BASE_URL` and `ANVIL_LLM_API_KEY` to enable.\n"
            "Examples:\n"
            "  export ANVIL_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4\n"
            "  export ANVIL_LLM_API_KEY=xxx\n"
            "  export ANVIL_MODEL=glm-4.5-flash"
        )

    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120)
    kwargs = {"model": model_name, "messages": messages, "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
    if stream:
        kwargs["stream"] = True
    # 智谱 glm-4.5 系默认开思维链:content 为空+工具调用偶发丢失,
    # 显式关闭(Agent 工具编排不需要内置 CoT,靠 system prompt 驱动)。
    if "bigmodel" in base_url:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = client.chat.completions.create(**kwargs)
    _record_usage(user_id, "", "inference", model_name, resp)
    return resp


def chat_vision(messages, temperature=0.4, tools=None, user_id=None):
    """Call vision model for image understanding."""
    base_url, api_key, model_name = _get_config("vision", user_id=user_id)
    if not base_url or not api_key:
        return _mock_response("> Vision model not configured. Set ANVIL_VISION_MODEL and ANVIL_VISION_BASE_URL.")

    from openai import OpenAI

def _is_fatal_api_error(e):
    """Check if API error is fatal (should not retry)."""
    return getattr(e, 'status_code', None) in {401, 402, 403}


def _friendly_error(e):
    """Convert API exception to user-friendly Chinese message."""
    try:
        from openai import APIStatusError, APITimeoutError, APIConnectionError
    except ImportError:
        return f"LLM error: {e}"
    if isinstance(e, APIStatusError):
        code = e.status_code
        msgs = {
            401: "API Key 无效，请检查 ANVIL_LLM_API_KEY",
            402: "API 账户余额不足，请充值后重试",
            403: "API 访问被拒绝，请检查权限",
            429: "API 限流，稍后自动重试",
        }
        if code in msgs:
            return f"({code}) {msgs[code]}"
        if 500 <= code < 600:
            return f"({code}) API 服务器故障，稍后重试"
        return f"({code}) API 错误: {e.message}"
    if isinstance(e, APITimeoutError):
        return "API 请求超时，即将重试"
    if isinstance(e, APIConnectionError):
        return "API 连接失败，即将重试"
    return f"LLM 调用失败: {e}"


    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120)
    kwargs = {"model": model_name, "messages": messages, "temperature": temperature}
    if tools:
        kwargs["tools"] = tools
    resp = client.chat.completions.create(**kwargs)
    _record_usage(user_id, "", "vision", model_name, resp)
    return resp


class _MockChoice:
    def __init__(self, content):
        self.message = _MockMessage(content)


class _MockMessage:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _MockResponse:
    def __init__(self, content):
        self.choices = [_MockChoice(content)]


def _mock_response(content):
    return _MockResponse(content)
