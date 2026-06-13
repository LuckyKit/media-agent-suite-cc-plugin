"""
cli.platforms.twitter.hooks — Twitter 平台内嵌 Hook

不再依赖外部脚本文件，所有 hook 逻辑作为 Python 函数内嵌在 CLI 包中。
解决了插件安装后 hook 路径不可达、Windows stdin 编码等问题。

接口规范（与旧版外部脚本兼容）：
  输入：payload dict
  输出：{"ok": bool, "warnings": [...], "errors": [...]}
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

# ============================================================================
# pre-discover: 准入检查（数据源可用性）
# ============================================================================


def pre_discover(_payload: dict) -> dict:
    """Discover 前准入检查：仅检查数据源可用性。"""
    result: dict = {"ok": True}
    if not os.environ.get("TWITTERAPI_IO_KEY"):
        result["warnings"] = ["无可用数据源。设置 TWITTERAPI_IO_KEY 以获取真实数据。"]
    return result


# ============================================================================
# post-discover: 经验沉淀（历史 + 关键词统计 + 作者排行）
# ============================================================================

_MEMORY_DIR = Path.home() / ".media-agent" / "memory"
_HISTORY_FILE = _MEMORY_DIR / "history.jsonl"
_INSIGHTS_DIR = _MEMORY_DIR / "insights" / "twitter"
_KEYWORD_STATS_FILE = _INSIGHTS_DIR / "keyword_stats.json"
_AUTHOR_STATS_FILE = _INSIGHTS_DIR / "author_stats.json"

# 用户可见的问题记录
_QUESTION_FILE = Path("my/twitter/Question.md")


def _ensure_dirs() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    _QUESTION_FILE.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, record: dict) -> None:
    _ensure_dirs()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    _INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_history(payload: dict) -> None:
    args = payload.get("args", {})
    result = payload.get("result", {})
    meta = result.get("meta", {})

    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": "twitter discover tweets",
        "keyword": args.get("keyword"),
        "hashtag": args.get("hashtag"),
        "tweets_found": meta.get("count", 0),
        "source": meta.get("source", "unknown"),
        "flags": {
            "viral": args.get("viral", False),
            "personal": args.get("personal", False),
            "diverse": args.get("diverse", False),
        },
    }
    _append_jsonl(_HISTORY_FILE, record)


def _update_keyword_stats(payload: dict) -> None:
    result = payload.get("result", {})
    meta = result.get("meta", {})
    keyword = meta.get("keyword") or meta.get("hashtag") or payload.get("args", {}).get("keyword")

    if not keyword or not result.get("tweets"):
        return

    tweets = result["tweets"]
    avg_er = sum(t.get("engagement_rate", 0) for t in tweets) / max(len(tweets), 1)
    avg_score = sum(t.get("score", 0) for t in tweets) / max(len(tweets), 1)

    stats = _load_json(_KEYWORD_STATS_FILE)

    if keyword not in stats:
        stats[keyword] = {"searches": 0, "total_er": 0, "total_score": 0, "total_tweets": 0}

    entry = stats[keyword]
    entry["searches"] += 1
    entry["total_er"] += avg_er
    entry["total_score"] += avg_score
    entry["total_tweets"] += len(tweets)
    entry["avg_engagement_rate"] = round(entry["total_er"] / entry["searches"], 2)
    entry["avg_score"] = round(entry["total_score"] / entry["searches"], 1)
    entry["last_search"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    stats = dict(sorted(stats.items(), key=lambda x: x[1].get("avg_er", 0), reverse=True)[:100])
    _save_json(_KEYWORD_STATS_FILE, stats)


def _update_author_stats(payload: dict) -> None:
    tweets = payload.get("result", {}).get("tweets", [])
    if not tweets:
        return

    stats: dict = _load_json(_AUTHOR_STATS_FILE)

    for t in tweets:
        author = t.get("author", "")
        if not author:
            continue
        if author not in stats:
            stats[author] = {
                "name": t.get("author_name", ""),
                "appearances": 0,
                "total_score": 0,
                "followers": t.get("followers", 0),
                "verified": t.get("verified", False),
            }
        stats[author]["appearances"] += 1
        stats[author]["total_score"] += t.get("score", 0)

    stats = dict(sorted(stats.items(), key=lambda x: x[1]["appearances"], reverse=True)[:200])
    _save_json(_AUTHOR_STATS_FILE, stats)


def _write_question_md(payload: dict) -> None:
    """将每次搜索的「问题」追加到 my/twitter/Question.md，供用户进化问题质量。"""
    args = payload.get("args", {})
    result = payload.get("result", {})
    meta = result.get("meta", {})
    breakdown = result.get("breakdown", {})

    keyword = args.get("keyword")
    hashtag = args.get("hashtag")
    q = keyword or (f"#{hashtag}" if hashtag else "默认搜索")
    now = time.strftime("%Y-%m-%d %H:%M", time.gmtime())

    # 维度拆解
    dims = []
    if args.get("viral"):
        dims.append("按互动率排序（找素人爆款）")
    if args.get("personal"):
        dims.append("只看素人（<5 万粉）")
    if args.get("diverse"):
        dims.append("作者去重")
    if args.get("lang"):
        dims.append(f"语言：{args['lang']}")
    if args.get("hours"):
        dims.append(f"时间范围：{args['hours']}h")
    dim_str = "、".join(dims) if dims else "无额外维度"

    # 质量信号（不写结果内容，只写"这次问题好不好"的指标）
    total = breakdown.get("total_input", 0)
    excluded = breakdown.get("excluded", 0)
    scored = breakdown.get("scored", 0)
    s_count = breakdown.get("S_count", 0)
    a_count = breakdown.get("A_count", 0)
    b_count = breakdown.get("B_count", 0)
    good = s_count + a_count
    junk_rate = round((1 - good / max(scored, 1)) * 100)

    _ensure_dirs()

    md = f"""### {now}

**问题**：`{q}`

**覆盖维度**：{dim_str}

**问题质量信号**：
- 输入 {total} → 排除 {excluded} → 评分 {scored}
- 可策展 {good} 条（S={s_count} A={a_count}），垃圾率 {junk_rate}%
- 数据源：{meta.get('source', 'unknown')}

---
"""

    if _QUESTION_FILE.exists():
        existing = _QUESTION_FILE.read_text(encoding="utf-8")
        # 新问题插在最前面
        md = md + existing
    _QUESTION_FILE.write_text(md, encoding="utf-8")


def post_discover(payload: dict) -> dict:
    """Discover 后经验沉淀。"""
    result = payload.get("result", {})

    if not result.get("tweets"):
        return {"ok": True, "summary": "无数据，跳过沉淀"}

    try:
        _record_history(payload)
        _update_keyword_stats(payload)
        _update_author_stats(payload)
        _write_question_md(payload)
    except Exception as e:
        return {"ok": True, "summary": f"沉淀异常: {e}"}

    meta = result.get("meta", {})
    summary = (
        f"已沉淀 {meta.get('count', 0)} 条推文，"
        f"关键词: {meta.get('keyword') or meta.get('hashtag')}, "
        f"来源: {meta.get('source')}"
    )
    return {"ok": True, "summary": summary}


# ============================================================================
# post-publish: 模板追踪（template_usage.jsonl）+ 操作历史
# ============================================================================

_PROJECT_HISTORY = Path(".media-agent/shared/history.jsonl")
_TEMPLATE_TRACKING = Path(".media-agent/shared/tracking/twitter/template_usage.jsonl")


def _ensure_tracking_dir() -> None:
    _TEMPLATE_TRACKING.parent.mkdir(parents=True, exist_ok=True)


def _load_draft(draft_path: str) -> dict:
    """从路径加载草稿 JSON，失败返回空字典。"""
    try:
        p = Path(draft_path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def post_publish(payload: dict) -> dict:
    """发布后将 template_refs 写入 template_usage.jsonl，供复盘时评分。"""
    args = payload.get("args", {})
    result = payload.get("result", {}) or {}

    draft_path = args.get("draft", "")
    draft = _load_draft(draft_path)
    template_refs = draft.get("template_refs", [])

    tweet_id = result.get("tweet_id") or draft.get("published_tweet_id")
    tweet_url = result.get("tweet_url") or draft.get("published_tweet_url")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 写入模板追踪（即使 template_refs 为空也记录本次发布）
    _ensure_tracking_dir()
    record = {
        "time": now,
        "tweet_url": tweet_url,
        "tweet_id": tweet_id,
        "draft_id": draft.get("draft_id"),
        "draft_path": draft_path,
        "tweet_type": draft.get("type", "tweet"),
        "hook_type": draft.get("hook_type", ""),
        "structure_type": draft.get("structure_type", ""),
        "cta_type": draft.get("cta_type", ""),
        "template_refs": template_refs,
        "engagement_data": None,   # 复盘时填充
        "score_updated": False,
    }
    _append_jsonl(_TEMPLATE_TRACKING, record)

    # 写入项目级操作历史
    _PROJECT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history_record = {
        "time": now,
        "action": "twitter publish tweet",
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "draft_id": draft.get("draft_id"),
        "template_count": len(template_refs),
    }
    _append_jsonl(_PROJECT_HISTORY, history_record)

    # 写入用户级操作历史（evolve analyze 会合并两个文件统计）
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _append_jsonl(_HISTORY_FILE, history_record)

    # 将草稿状态更新为已发布
    if draft_path and Path(draft_path).exists():
        try:
            draft["status"] = "published"
            draft["published_at"] = now
            if tweet_id:
                draft["published_tweet_id"] = tweet_id
            if tweet_url:
                draft["published_tweet_url"] = tweet_url
            Path(draft_path).write_text(
                json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # 草稿写回失败不阻断主流程

    return {
        "ok": True,
        "summary": (
            f"已追踪发布记录：{len(template_refs)} 个模板引用，"
            f"tweet_id={tweet_id or '未知'}，待复盘时评分"
        ),
    }


# ============================================================================
# Hook 注册表（平台 + 时机 → 函数）
# ============================================================================

_HOOK_REGISTRY: dict[str, dict[str, dict[str, Callable]]] = {
    "twitter": {
        "discover": {
            "pre": pre_discover,
            "post": post_discover,
        },
        "publish": {
            "post": post_publish,
        },
    },
}


def get_hook(platform: str, action: str, timing: str) -> Callable | None:
    """根据平台、动作、时机获取内嵌 hook 函数。"""
    platform_hooks = _HOOK_REGISTRY.get(platform, {})
    action_hooks = platform_hooks.get(action, {})
    return action_hooks.get(timing)
