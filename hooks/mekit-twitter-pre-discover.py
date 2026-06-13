#!/usr/bin/env python3
"""
hooks/twitter/pre-discover.py — Twitter 发现前准入检查

职责：
  - 校验数据源可用性（twitterapi.io key）
  - 频率限制：防止短时间重复调用烧 quota
  - 清理过期本地缓存

输入（stdin JSON）：
  {"platform": "twitter", "action": "discover", "target": "tweets", "args": {...}}

输出（stdout JSON）：
  {"ok": true}  通过
  {"ok": false, "errors": ["..."]}  阻断
"""

import json
import os
import sys
import time
from pathlib import Path

# 频率限制：每小时最多 N 次
_RATE_LIMIT_FILE = Path(".media-agent/shared/state/twitter_discover_rate.json")
_MAX_CALLS_PER_HOUR = 10


def _load_rate() -> dict:
    """加载频率计数器。"""
    if not _RATE_LIMIT_FILE.exists():
        return {"hour": int(time.time() // 3600), "count": 0}
    try:
        return json.loads(_RATE_LIMIT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"hour": int(time.time() // 3600), "count": 0}


def _save_rate(rate: dict) -> None:
    """保存频率计数器。"""
    _RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RATE_LIMIT_FILE.write_text(json.dumps(rate), encoding="utf-8")


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except (OSError, AttributeError):
            pass
    try:
        _payload = json.loads(sys.stdin.read())  # noqa: F841
    except (json.JSONDecodeError, ValueError):
        pass  # stdin 为空或非法 JSON 时不阻塞，继续准入检查
    warnings: list[str] = []

    # 1. 数据源检查
    has_twitterapi_io = bool(os.environ.get("TWITTERAPI_IO_KEY"))

    if not has_twitterapi_io:
        warnings.append("无可用数据源，将返回 mock 数据。设置 TWITTERAPI_IO_KEY 获取真实数据。")

    # 2. 频率限制
    rate = _load_rate()
    current_hour = int(time.time() // 3600)

    if rate["hour"] != current_hour:
        rate = {"hour": current_hour, "count": 0}

    rate["count"] += 1
    _save_rate(rate)

    if rate["count"] > _MAX_CALLS_PER_HOUR:
        # 超限阻断
        print(json.dumps({
            "ok": False,
            "errors": [f"频率限制：每小时最多 {_MAX_CALLS_PER_HOUR} 次 discover 调用，当前已 {rate['count'] - 1} 次"],
        }, ensure_ascii=False))
        sys.exit(1)

    # 通过
    result = {"ok": True}
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
