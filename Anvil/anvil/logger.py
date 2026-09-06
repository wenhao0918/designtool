"""
Unified logging for Anvil.

Usage:
    from anvil.logger import get_logger
    log = get_logger(__name__)
    log.info("something happened")
    log.error("something broke", extra={"tool": "freecad_execute"})

Writes to ANVIL_ROOT/anvil.log with rotation at 10MB (keeps 3 backups).
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime


_loggers: dict[str, logging.Logger] = {}
_handler: logging.Handler | None = None


def _get_log_path() -> str:
    """Determine anvil.log path. 数据目录(ANVIL_DATA_DIR)优先,否则爬源码根找 .env。"""
    data_dir = os.environ.get("ANVIL_DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "anvil.log")
    # Default: next to this file's package root
    cur = os.path.dirname(os.path.abspath(__file__))
    # Climb to DesignTool/Anvil
    for _ in range(3):
        if os.path.exists(os.path.join(cur, ".env")):
            return os.path.join(cur, "anvil.log")
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.join(cur, "anvil.log")


def _ensure_handler():
    global _handler
    if _handler is not None:
        return

    log_path = _get_log_path()
    log_dir = os.path.dirname(log_path)
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _handler.setFormatter(fmt)
    _handler.setLevel(logging.DEBUG)

    # Also log to stderr at WARNING+
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    stderr_handler.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(_handler)
    root.addHandler(stderr_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Automatically sets up file handler on first call."""
    _ensure_handler()
    if name not in _loggers:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        _loggers[name] = logger
    return _loggers[name]


def log_tool_call(tool_name: str, args: dict | None = None, result: str = "", duration_ms: float = 0):
    """Convenience: log a tool execution."""
    logger = get_logger("anvil.tool." + tool_name)
    args_str = str(args)[:200] if args else "{}"
    logger.info("CALL args=%s result=%s duration=%.0fms", args_str, result[:100], duration_ms)


def log_llm_error(error_type: str, message: str, retry: int = 0):
    """Convenience: log an LLM error."""
    logger = get_logger("anvil.llm")
    if retry > 0:
        logger.warning("%s (retry %d): %s", error_type, retry, message[:200])
    else:
        logger.error("%s: %s", error_type, message[:200])
