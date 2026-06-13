"""
cli.core.protocol — 统一输出协议

职责：
  - 定义所有 CLI 命令的成功/失败输出格式
  - 提供 emit_data() / emit_error() 辅助函数
  - 确保 YouTube、Twitter、content 等所有命令输出结构一致
  - 支持 JSON 模式（默认）和人类可读模式（--pretty）

协议格式（v1）：
  成功：
    {
      "ok": true,
      "data": {},
      "meta": {
        "cmd": "twitter discover tweets",
        "took_ms": 42,
        "version": "0.1.0"
      }
    }

  失败：
    {
      "ok": false,
      "error": {
        "code": "PLATFORM_ERROR",
        "message": "...",
        "hint": "检查 API Key 是否正确"
      }
    }
"""

import time

_VERSION = "0.1.0"


def emit_data(
    data: dict, meta: dict | None = None, cmd: str = "", start_time: float | None = None
) -> dict:
    """包装成功响应，自动计算耗时。"""
    took_ms = 0
    if start_time is not None:
        took_ms = round((time.time() - start_time) * 1000, 2)
    merged_meta = {
        "cmd": cmd,
        "took_ms": took_ms,
        "version": _VERSION,
    }
    if meta:
        merged_meta.update(meta)
    return {
        "ok": True,
        "data": data,
        "meta": merged_meta,
    }


def emit_error(code: str, message: str, hint: str | None = None) -> dict:
    """包装错误响应，code 为机器可读错误码。"""
    error_payload: dict[str, str | None] = {
        "code": code,
        "message": message,
    }
    if hint is not None:
        error_payload["hint"] = hint
    return {
        "ok": False,
        "error": error_payload,
    }
