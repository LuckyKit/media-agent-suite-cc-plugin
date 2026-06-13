#!/usr/bin/env python3
"""
hooks/twitter/post-publish.py — Twitter/X 发布后钩子

职责：
  1. 接收 publish 结果（stdin JSON）
  2. 追加操作历史到项目级 .media-agent/shared/history.jsonl
  3. 更新 draft 文件：status → "published"，写入 tweet_url/tweet_id
  4. 写入模板追踪数据到 .media-agent/shared/tracking/twitter/template_usage.jsonl
  5. 追加用户级 ~/.media-agent/memory/history.jsonl
  6. 输出归档确认

输入（stdin JSON）：
  {"platform": "twitter", "action": "publish", "target": "tweet",
   "draft_path": ".media-agent/shared/drafts/twitter/draft-xxx.json",
   "result": {"tweet_url": "...", "tweet_id": "...", "published_at": "..."}}

输出（stdout JSON）：
  {"ok": true, "archived": true, "draft_updated": true, "tracking_written": true}
"""

import json
import sys
import time
from pathlib import Path

_PROJECT_HISTORY = Path(".media-agent/shared/history.jsonl")
_USER_HISTORY = Path.home() / ".media-agent" / "memory" / "history.jsonl"
_TEMPLATE_TRACKING = Path(".media-agent/shared/tracking/twitter/template_usage.jsonl")


def _append_jsonl(path: Path, record: dict) -> None:
    """追加一行 JSON 到文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _update_draft(draft_path: str, result: dict) -> bool:
    """更新 draft.json：status→published，写入 tweet_url/id。"""
    path = Path(draft_path)
    if not path.exists():
        return False
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    draft["status"] = "published"
    draft["published_at"] = result.get(
        "published_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    draft["published_tweet_url"] = result.get("tweet_url")
    draft["published_tweet_id"] = result.get("tweet_id")
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _write_template_tracking(draft_path: str, result: dict) -> bool:
    """从 draft 中提取 template_refs，写入追踪文件供后续模板评分使用。"""
    path = Path(draft_path)
    if not path.exists():
        return False
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    template_refs = draft.get("template_refs", [])
    if not template_refs:
        return False

    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tweet_url": result.get("tweet_url"),
        "tweet_id": result.get("tweet_id"),
        "draft_path": draft_path,
        "hook_type": draft.get("hook_type", ""),
        "structure_type": draft.get("structure_type", ""),
        "cta_type": draft.get("cta_type", ""),
        "template_refs": template_refs,
        "engagement_data": None,  # 待复盘时填充
        "score_updated": False,
    }
    _append_jsonl(_TEMPLATE_TRACKING, record)
    return True


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except (OSError, AttributeError):
            pass

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"ok": False, "error": "stdin 为空或非法 JSON"}))
        return

    result = payload.get("result", {})
    draft_path = payload.get("draft_path", "")
    tweet_url = result.get("tweet_url", "")

    if not tweet_url:
        print(json.dumps({"ok": False, "error": "缺少 tweet_url"}))
        return

    # 1. 追加项目级历史
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": f"twitter publish {payload.get('target', 'tweet')}",
        "draft_path": draft_path,
        "tweet_url": tweet_url,
        "tweet_id": result.get("tweet_id"),
    }
    _append_jsonl(_PROJECT_HISTORY, record)

    # 2. 追加用户级历史
    _append_jsonl(_USER_HISTORY, record)

    # 3. 更新 draft 状态
    draft_updated = _update_draft(draft_path, result)

    # 4. 写入模板追踪 — 这是模板自进化的数据基础
    tracking_written = _write_template_tracking(draft_path, result)

    print(json.dumps({
        "ok": True,
        "archived": True,
        "draft_updated": draft_updated,
        "tracking_written": tracking_written,
        "tweet_url": tweet_url,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
