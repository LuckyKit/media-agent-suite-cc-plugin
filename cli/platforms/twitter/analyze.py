"""
cli.platforms.twitter.analyze — Twitter 分析模块

职责：
  - 单条推文 / Thread 深度分析
  - 用户画像分析：调用 twitterapi.io user 接口
  - Hashtag 效能分析

一件事原则：
  - 只做"分析提炼"，不发现新推文，不写新推文，不发送推文

命令映射：
  mekit twitter analyze tweet --url="https://..."
  mekit twitter analyze thread --thread-id=xxx
  mekit twitter analyze user --username=xxx
  mekit twitter analyze hashtag --tag=#AI
"""

import os

import requests

from cli.core.registry import command

_TWITTERAPI_IO_BASE = "https://api.twitterapi.io"
_API_KEY = os.environ.get("TWITTERAPI_IO_KEY", "")

_HEADERS = {
    "X-API-Key": _API_KEY,
    "Accept": "application/json",
}


def _api_get(endpoint: str, params: dict | None = None) -> dict | None:
    """调用 twitterapi.io API，失败返回 None。"""
    if not _API_KEY:
        return None
    try:
        resp = requests.get(
            f"{_TWITTERAPI_IO_BASE}{endpoint}",
            headers=_HEADERS,
            params=params or {},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


@command("twitter", "analyze", "tweet")
def analyze_tweet(url: str = "", **kwargs) -> dict:
    """分析单条推文。"""
    if not url:
        return {
            "tweet_url": None,
            "notice": "需要提供 --url 参数。示例：mekit twitter analyze tweet --url=https://x.com/...",
        }

    tweet_id = url.rstrip("/").split("/")[-1]
    data = _api_get(f"/twitter/tweets/{tweet_id}")

    if not data:
        return {
            "tweet_url": url,
            "tweet_id": tweet_id,
            "source": "none" if not _API_KEY else "api_unavailable",
            "notice": "无法获取推文数据。请检查 API Key 或推文 ID。" if _API_KEY else "未配置 TWITTERAPI_IO_KEY",
        }

    return {
        "tweet_url": url,
        "tweet_id": tweet_id,
        "data": data,
        "source": "twitterapi_io",
    }


@command("twitter", "analyze", "thread")
def analyze_thread(thread_id: str = "", **kwargs) -> dict:
    """分析整个 Thread 串的结构与互动。"""
    if not thread_id:
        return {
            "thread_id": None,
            "notice": "需要提供 --thread-id 参数。",
        }
    return {
        "thread_id": thread_id,
        "notice": "Thread 深度分析需要多轮 API 调用，暂未实现。提供基础数据。",
    }


@command("twitter", "analyze", "user")
def analyze_user(username: str = "", **kwargs) -> dict:
    """分析 Twitter 用户的内容策略。"""
    if not username:
        return {
            "username": None,
            "notice": "需要提供 --username 参数。示例：mekit twitter analyze user --username=elonmusk",
        }

    clean_name = username.lstrip("@")
    data = _api_get(f"/twitter/users/{clean_name}")

    if not data:
        return {
            "username": username,
            "source": "none" if not _API_KEY else "api_unavailable",
            "notice": "无法获取用户数据。请检查 API Key 或用户名。" if _API_KEY else "未配置 TWITTERAPI_IO_KEY",
        }

    # 提取关键指标
    user = data.get("data", data)
    return {
        "username": username,
        "profile": {
            "name": user.get("name", ""),
            "description": user.get("description", "")[:200] if user.get("description") else "",
            "followers_count": user.get("public_metrics", {}).get("followers_count", 0),
            "following_count": user.get("public_metrics", {}).get("following_count", 0),
            "tweet_count": user.get("public_metrics", {}).get("tweet_count", 0),
            "verified": user.get("verified", False),
            "created_at": user.get("created_at", ""),
        },
        "source": "twitterapi_io",
    }


@command("twitter", "analyze", "hashtag")
def analyze_hashtag(tag: str = "", **kwargs) -> dict:
    """分析 Hashtag 的效能与趋势。"""
    if not tag:
        return {
            "tag": None,
            "notice": "需要提供 --tag 参数。示例：mekit twitter analyze hashtag --tag=#AI",
        }
    clean_tag = tag.lstrip("#")
    tweets = _api_get("/twitter/search", {"query": f"#{clean_tag}", "limit": 50})

    if not tweets:
        return {
            "tag": tag,
            "source": "none" if not _API_KEY else "api_unavailable",
            "notice": "无法获取 Hashtag 数据。" if _API_KEY else "未配置 TWITTERAPI_IO_KEY",
        }

    return {
        "tag": tag,
        "tweet_count": len(tweets.get("tweets", [])),
        "source": "twitterapi_io",
    }
