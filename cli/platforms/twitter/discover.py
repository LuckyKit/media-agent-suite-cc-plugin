"""
cli.platforms.twitter.discover — Twitter 发现模块

职责：
  - Trending Topics 发现（基于 twitterapi.io advanced_search）
  - Viral Tweets 发现（高互动推文：高 reply/retweet/like 比例）
  - Spaces 直播发现（API 已关闭，返回提示）

一件事原则：
  - 只做"找内容"，不分析传播原因，不生成推文，不执行发布
  - 输出原始推文/话题元数据（text, author, metrics, created_at 等）

命令映射：
  mekit twitter discover tweets --keyword="deepseek codex"
  mekit twitter discover tweets --hashtag="claude" --viral
  mekit twitter discover tweets --personal --diverse
  mekit twitter discover spaces --topic=tech
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from cli.core.errors import raise_discover_failed, raise_no_api_key
from cli.core.registry import command
from cli.core.storage import DataStore
from cli.platforms.twitter.scoring import score_and_grade, record_keyword_usage

_TWITTERAPI_IO_BASE = "https://api.twitterapi.io"

# Twitter discover 存储（进程级单例，默认持久化+缓存）
_DISCOVER_STORE: DataStore | None = None


def _get_store(mode: str = "both") -> DataStore:
    """获取 Twitter discover 专用存储管理器。

    mode: "both"=持久化+缓存 / "store"=只持久化 / "cache"=只缓存 / "none"=都不
    """
    global _DISCOVER_STORE
    if _DISCOVER_STORE is None or _DISCOVER_STORE.mode != mode:
        _DISCOVER_STORE = DataStore("twitter.discover", mode=mode)
    return _DISCOVER_STORE


@command("twitter", "discover", "tweets")
def discover_tweets(
    keyword: str | None = None,
    hashtag: str | None = None,
    limit: int = 3,
    hours: int = 168,
    viral: bool = False,
    personal: bool = False,
    fresh: bool = False,
    diverse: bool = False,
    lang: str | None = None,
    min_followers: int = 2000,
    storage: str = "both",
    **kwargs,
) -> dict:
    """发现 Twitter 推文，用于内容创作灵感挖掘。

    参数：
      keyword:       搜索词，如 "deepseek codex"
      hashtag:       话题标签，如 "claude"
      limit:         返回条数（默认 3，最大 50）
      hours:         时间范围（默认 168 小时=1周），API 级过滤
      viral:         True=按互动率排序找潜力股，False=按热度排序
      personal:       True=只看素人（<5万粉）
      fresh:         True=跳过缓存
      diverse:       True=每个作者最多 1 条
      lang:          语言过滤，如 zh / en / ja（默认不限语言）
      min_followers: 最低粉丝数过滤（默认 0 不过滤）
      storage:       存储模式

    示例：
      mekit twitter discover tweets --keyword="deepseek codex" --diverse
      mekit twitter discover tweets --hashtag="claude" --viral --personal --hours=24
      mekit twitter discover tweets --keyword="I built AI" --fresh
      mekit twitter discover tweets --keyword="deepseek" --lang=zh
      mekit twitter discover tweets --keyword="MIT license" --min-followers=1000
    """
    # 构建查询
    if hashtag:
        query = f"#{hashtag.lstrip('#')}"
    elif keyword:
        query = keyword
    else:
        query = '("I built" OR "just launched" OR "how I" OR "my experience" OR "I made") AI'

    # 时间过滤：twitterapi.io 支持 since_time / until_time（Unix 秒），
    # 不支持 Twitter 原生 -filter:retweets 语法。
    now_ts = int(time.time())
    since_ts = now_ts - hours * 3600
    query = f"{query} since_time:{since_ts} until_time:{now_ts}"

    if lang:
        query = f"{query} lang:{lang}"

    fetch_count = max(limit * 5, 20) if diverse else max(limit, 10)
    tweets, source = _search_tweets(query, max_results=fetch_count, fresh=fresh, storage=storage)

    if not tweets:
        if _get_twitterapi_io_key():
            return raise_discover_failed(_last_api_error or "未知错误")
        else:
            return raise_no_api_key("twitterapi.io")

    tweets = _apply_filters(tweets, personal=personal, fresh=fresh, diverse=diverse, min_followers=min_followers)

    # 规则引擎：排除 → 评分 → 分级 → 排序 → 截断
    # 替代人工主观判断，所有评分由 discovery-rules.json 驱动
    graded = score_and_grade(tweets)

    # 记录关键词使用（用于 evolve 分析效果）
    if keyword:
        record_keyword_usage(keyword, len(tweets))

    return {
        "tweets": graded["S"] + graded["A"] + graded["B"],
        "grades": {
            "S": graded["S"],
            "A": graded["A"],
            "B": graded["B"],
        },
        "breakdown": graded["breakdown"],
        "meta": {
            "count": len(graded["S"]) + len(graded["A"]),
            "keyword": keyword,
            "hashtag": hashtag,
            "viral": viral,
            "personal": personal,
            "diverse": diverse,
            "fresh": fresh,
            "lang": lang,
            "source": source,
            "scored_by": "discovery-rules.json",
        },
    }


@command("twitter", "discover", "spaces")
def discover_spaces(topic: str | None = None, **kwargs) -> dict:
    """发现热门 Twitter Spaces（Spaces API 已关闭，返回提示）。"""
    return {
        "spaces": [],
        "notice": (
            "Twitter Spaces API 已于 2023 年关闭。如需 Spaces 数据，建议通过第三方工具获取。"
        ),
        "meta": {"count": 0, "topic": topic, "source": "none"},
    }


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _get_twitterapi_io_key() -> str | None:
    """从环境变量读取 twitterapi.io API Key。"""
    api_key = os.environ.get("TWITTERAPI_IO_KEY")
    if api_key and not api_key.startswith("${"):
        return api_key
    return None


# twitterapi.io 最后一次错误信息（供上层报告）
_last_api_error: str | None = None


def _call_twitterapi_io_search(query: str, max_results: int = 10) -> dict | None:
    """通过 twitterapi.io advanced_search 搜索推文，失败返回 None 并设置 _last_api_error。

    注册获取 API Key：https://twitterapi.io/dashboard
    文档：https://docs.twitterapi.io
    """
    global _last_api_error
    _last_api_error = None

    api_key = os.environ.get("TWITTERAPI_IO_KEY")
    if not api_key:
        _last_api_error = "TWITTERAPI_IO_KEY 未设置"
        return None

    url = f"{_TWITTERAPI_IO_BASE}/twitter/tweet/advanced_search"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    params = {"query": query, "queryType": "Top"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        # 非 200：记录错误详情
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]
        _last_api_error = f"HTTP {resp.status_code}: {body}"
    except requests.RequestException as e:
        _last_api_error = f"请求失败: {e}"

    return None


def _search_tweets(
    query: str,
    max_results: int = 10,
    fresh: bool = False,
    storage: str = "both",
) -> tuple[list[dict], str]:
    """搜索推文，按优先级尝试数据源。

    返回：(tweets_list, source_name)
    source: "twitterapi_io" | "none"

    storage: "both"=持久化+缓存 / "store"=只持久化 / "cache"=只缓存 / "none"=都不
    fresh=True 时跳过缓存，但仍会持久化（如果 storage 包含 store）。
    """
    store = _get_store(storage)
    store_params = {"query": query, "max_results": max_results}

    # 0. 查缓存（fresh 模式或 storage 不含 cache 时跳过）
    if not fresh and storage in ("both", "cache"):
        cached = store.load_cached(store_params, ttl=300)
        if cached is not None:
            return cached["data"]["tweets"], cached["_meta"]["source"]

    # 1. twitterapi.io
    api_key = os.environ.get("TWITTERAPI_IO_KEY")
    if api_key:
        data = _call_twitterapi_io_search(query, max_results)
        if data:
            tweets = _parse_twitterapi_io(data)
            if tweets:
                store.save(store_params, {"tweets": tweets, "_raw": data}, source="twitterapi_io")
                return tweets, "twitterapi_io"
            else:
                # API 返回了数据但解析为 0 条，记录原因
                global _last_api_error
                tweet_count = len(data.get("tweets", []))
                _last_api_error = f"API 返回 {tweet_count} 条推文，解析后为 0（可能字段格式变更）"
        # 如果 data 为 None，_last_api_error 已由 _call_twitterapi_io_search 设置

    return [], "none"


def _parse_twitterapi_io(data: dict) -> list[dict]:
    """解析 twitterapi.io advanced_search 响应为标准推文列表。

    API 真实响应格式：
      {tweets: [{id, text, createdAt, lang, author: {id, userName, name,
        isBlueVerified, followers, ...}, likeCount, retweetCount, replyCount,
        viewCount, bookmarkCount, quoteCount, ...}], has_next_page, next_cursor}
    """
    tweets: list[dict] = []
    for t in data.get("tweets", []):
        # 跳过转推（twitterapi.io 不支持 -filter:retweets 查询语法）
        if t.get("retweeted_tweet"):
            continue
        author = t.get("author") or {}
        tweet_id = str(t.get("id", ""))
        text = t.get("text") or ""
        likes = t.get("likeCount", 0)
        rts = t.get("retweetCount", 0)
        replies = t.get("replyCount", 0)
        followers = author.get("followers", 1) or 1  # 避免除零
        interactions = likes + rts + replies
        tweets.append({
            "id": tweet_id,
            "text": text,
            "author_id": str(author.get("id", "")),
            "author": f"@{author.get('userName', '')}",
            "author_name": author.get("name", ""),
            "verified": author.get("isBlueVerified", False),
            "followers": followers,
            "created_at": t.get("createdAt", ""),
            "lang": t.get("lang", "en"),
            "url": f"https://x.com/i/status/{tweet_id}",
            "is_thread": _is_thread(text),
            "metrics": {
                "like_count": likes,
                "retweet_count": rts,
                "reply_count": replies,
                "impression_count": t.get("viewCount", 0),
                "bookmark_count": t.get("bookmarkCount", 0),
                "quote_count": t.get("quoteCount", 0),
            },
            "engagement_rate": round(interactions / followers * 100, 2),  # 互动率 %
            "score": likes + rts * 2 + replies * 3,
        })
    return tweets


def _apply_filters(
    tweets: list[dict],
    personal: bool = False,
    fresh: bool = False,
    diverse: bool = False,
    min_followers: int = 0,
) -> list[dict]:
    """公共过滤管道：作者去重 → 素人过滤 → 粉丝数下限 → 已看去重。"""
    if diverse:
        seen: set[str] = set()
        diverse_list = []
        for t in sorted(tweets, key=lambda t: t["score"], reverse=True):
            if t["author_id"] not in seen:
                diverse_list.append(t)
                seen.add(t["author_id"])
        tweets = diverse_list

    if personal:
        tweets = [t for t in tweets if t.get("followers", 0) < 50000]

    if min_followers > 0:
        tweets = [t for t in tweets if t.get("followers", 0) >= min_followers]

    if fresh:
        seen_ids = _load_seen_ids()
        tweets = [t for t in tweets if t["id"] not in seen_ids]
        _mark_seen([t["id"] for t in tweets])

    return tweets


def _is_thread(text: str) -> bool:
    """判断是否是 Thread（长文串），超过 500 字且含 🧵 或 1/ 等标记。"""
    if len(text) < 500:
        return False
    markers = ["🧵", "1/", "👇", "thread", "Thread"]
    return any(m in text for m in markers)


# 已看推文去重
_SEEN_FILE = Path(".media-agent/shared/seen/twitter.json")


def _load_seen_ids() -> set[str]:
    """加载已看过的推文 ID 集合。"""
    if not _SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(_SEEN_FILE.read_text(encoding="utf-8"))
        return set(data.get("ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _mark_seen(ids: list[str]) -> None:
    """标记推文 ID 为已看（保留最近 500 条，按添加顺序）。"""
    if not ids:
        return
    # 用 list 维护插入顺序，去重后只保留最近 500 条
    existing = list(_load_seen_ids())
    new_ids = [i for i in ids if i not in set(existing)]
    merged = (existing + new_ids)[-500:]
    _SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SEEN_FILE.write_text(
        json.dumps({"ids": merged, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, ensure_ascii=False),
        encoding="utf-8",
    )



