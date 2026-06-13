#!/usr/bin/env python3
"""
hooks/twitter/post-discover.py — Twitter 发现后经验沉淀

职责：
  - 记录执行历史到 memory/history.jsonl
  - 沉淀发现经验到 memory/insights/twitter/
    · 关键词效果追踪（哪个词产出最高互动率？）
    · 作者热度排行（谁的内容反复被搜到？）
    · 数据源效率（twitterapi_io vs mock 占比）
  - 输出摘要，不影响主流程

输入（stdin JSON）：
  {"platform": "twitter", "action": "discover", "target": "tweets",
   "args": {"keyword": "deepseek", ...},
   "result": {"tweets": [...], "meta": {...}}}

输出（stdout JSON）：
  {"ok": true, "summary": "..."}
"""

import json
import sys
import time
from pathlib import Path

_MEMORY_DIR = Path.home() / ".media-agent" / "memory"
_HISTORY_FILE = _MEMORY_DIR / "history.jsonl"
_PROJECT_HISTORY = Path(".media-agent/shared/history.jsonl")
_INSIGHTS_DIR = _MEMORY_DIR / "insights" / "twitter"
_KEYWORD_STATS_FILE = _INSIGHTS_DIR / "keyword_stats.json"
_AUTHOR_STATS_FILE = _INSIGHTS_DIR / "author_stats.json"

# 用户可见的问题记录
_QUESTION_FILE = Path("my/twitter/Question.md")


def _ensure_dirs() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    _PROJECT_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    _QUESTION_FILE.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, record: dict) -> None:
    """追加一行 JSON 到文件。"""
    _ensure_dirs()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> dict:
    """安全加载 JSON 文件。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    _INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 经验沉淀
# ---------------------------------------------------------------------------


def _record_history(payload: dict) -> None:
    """追加执行历史。"""
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
    _append_jsonl(_PROJECT_HISTORY, record)


def _update_keyword_stats(payload: dict) -> None:
    """更新关键词效果统计：哪个词产出互动率最高？"""
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

    # 只保留最近 100 个关键词
    stats = dict(sorted(stats.items(), key=lambda x: x[1].get("avg_er", 0), reverse=True)[:100])
    _save_json(_KEYWORD_STATS_FILE, stats)


def _update_author_stats(payload: dict) -> None:
    """更新作者热度：谁的内容反复被搜到？"""
    tweets = payload.get("result", {}).get("tweets", [])
    if not tweets:
        return

    stats = _load_json(_AUTHOR_STATS_FILE)

    for t in tweets:
        author = t.get("author", "")
        if not author:
            continue
        if author not in stats:
            stats[author] = {"name": t.get("author_name", ""), "appearances": 0, "total_score": 0,
                             "followers": t.get("followers", 0), "verified": t.get("verified", False)}
        stats[author]["appearances"] += 1
        stats[author]["total_score"] += t.get("score", 0)

    stats = dict(sorted(stats.items(), key=lambda x: x[1]["appearances"], reverse=True)[:200])
    _save_json(_AUTHOR_STATS_FILE, stats)


# ---------------------------------------------------------------------------
# 问题记录（用户可见）
# ---------------------------------------------------------------------------


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

    # 质量信号
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
        md = md + existing
    _QUESTION_FILE.write_text(md, encoding="utf-8")
    _QUESTION_FILE.write_text(md, encoding="utf-8")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except (OSError, AttributeError):
            pass
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"ok": True, "summary": "stdin 为空，跳过沉淀"}))
        return
    result = payload.get("result", {})

    # 无结果（mock 或失败）不记录
    if not result.get("tweets"):
        print(json.dumps({"ok": True, "summary": "无数据，跳过沉淀"}))
        return

    try:
        _record_history(payload)
        _update_keyword_stats(payload)
        _update_author_stats(payload)
        _write_question_md(payload)
    except Exception as e:
        # 沉淀失败不能阻断主流程
        print(json.dumps({"ok": True, "summary": f"沉淀异常: {e}"}, ensure_ascii=False))
        return

    meta = result.get("meta", {})
    summary = (
        f"已沉淀 {meta.get('count', 0)} 条推文，"
        f"关键词: {meta.get('keyword') or meta.get('hashtag')}, "
        f"来源: {meta.get('source')}"
    )
    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
