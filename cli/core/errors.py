"""
cli.core.errors — 全局错误码定义

所有 CLI 模块统一使用此处的错误码和 emit 辅助函数。
不再各自手写 emit_error 字符串。

用法：
    from cli.core.errors import raise_discover_failed, raise_no_api_key

    return raise_no_api_key()
    return raise_discover_failed("HTTP 402: 余额不足")
"""

from cli.core.protocol import emit_error

# ── 错误码常量 ──────────────────────────────────────────────
# 命名规范: CATEGORY_REASON

# 认证/配置
NO_API_KEY = "NO_API_KEY"
INVALID_API_KEY = "INVALID_API_KEY"

# API 响应
API_RATE_LIMITED = "API_RATE_LIMITED"
API_CREDITS_EXHAUSTED = "API_CREDITS_EXHAUSTED"
API_AUTH_FAILED = "API_AUTH_FAILED"
API_RETURNED_EMPTY = "API_RETURNED_EMPTY"

# 发现
DISCOVER_FAILED = "DISCOVER_FAILED"
DISCOVER_PARSE_ERROR = "DISCOVER_PARSE_ERROR"

# 网络
NETWORK_ERROR = "NETWORK_ERROR"
NETWORK_TIMEOUT = "NETWORK_TIMEOUT"

# 发布
PUBLISH_FAILED = "PUBLISH_FAILED"
PUBLISH_REJECTED = "PUBLISH_REJECTED"

# 分析
ANALYZE_FAILED = "ANALYZE_FAILED"

# 通用
INVALID_PARAMS = "INVALID_PARAMS"
INTERNAL_ERROR = "INTERNAL_ERROR"


# ── 快捷 emit 函数 ──────────────────────────────────────────

def raise_no_api_key(service: str = "twitterapi.io") -> dict:
    return emit_error(
        NO_API_KEY,
        f"未设置 {service} 的 API Key",
        hint=f"在 .env 中设置对应环境变量后重试",
    )


def raise_discover_failed(reason: str) -> dict:
    return emit_error(
        DISCOVER_FAILED,
        f"发现请求失败：{reason}",
        hint="检查 API Key 余额或网络后重试",
    )


def raise_api_error(http_status: int, body: str) -> dict:
    if http_status == 429:
        code, msg = API_RATE_LIMITED, "API 请求频率过高"
        hint = "等待 60 秒后重试"
    elif http_status == 402:
        code, msg = API_CREDITS_EXHAUSTED, "API 额度已用尽"
        hint = "前往 twitterapi.io 充值"
    elif http_status in (401, 403):
        code, msg = API_AUTH_FAILED, f"API 认证失败 (HTTP {http_status})"
        hint = "检查 API Key 是否正确"
    else:
        code, msg = API_RETURNED_EMPTY, f"API 返回异常 (HTTP {http_status}): {str(body)[:200]}"
        hint = "查看错误详情后重试"
    return emit_error(code, msg, hint=hint)


def raise_network_error(exception: str) -> dict:
    return emit_error(
        NETWORK_ERROR,
        f"网络请求失败：{exception}",
        hint="检查网络连接后重试",
    )


def raise_invalid_params(param: str, expected: str) -> dict:
    return emit_error(
        INVALID_PARAMS,
        f"参数 {param} 无效",
        hint=f"期望：{expected}",
    )
