"""
cli.platforms.twitter.scoring — 发现评分引擎

职责：
  - 读取 discovery-rules.json，对所有推文计算多维度评分
  - 按阈值分配 S/A/B 等级
  - 不依赖任何人类判断，纯数据驱动

进化路径：
  - 规则中的 thresholds / weights 由 evolve 模块根据发布效果自动更新
  - 关键词 performance 字段由 publish hook 反哺
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


_RULES_PATH = Path("memory/discovery-rules.json")

# 规则缓存（进程级，首次加载后复用）
_RULES_CACHE: dict | None = None
_RULES_LOADED_AT: float = 0


def _load_rules() -> dict:
    """加载发现规则（带 60s 内存缓存）。"""
    global _RULES_CACHE, _RULES_LOADED_AT
    import time
    now = time.time()
    if _RULES_CACHE is not None and (now - _RULES_LOADED_AT) < 60:
        return _RULES_CACHE
    if _RULES_PATH.exists():
        _RULES_CACHE = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        _RULES_LOADED_AT = now
        return _RULES_CACHE
    return {}


def _hours_ago(created_at: str) -> float:
    """从 createdAt 计算距今小时数。"""
    try:
        # twitterapi.io 返回格式："Wed Jun 10 10:34:09 +0000 2026"
        dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 9999  # 解析失败，视为极旧


def _dimension_score(value: float, mapping: list[dict]) -> float:
    """根据映射表计算单维度分数（0-100）。
    使用区间匹配的离散分数，不做插值 — 避免假精度。"""
    for entry in mapping:
        low, high = entry["range"]
        if low <= value < high:
            return float(entry["score"])
    return 0


def score_tweet(tweet: dict) -> dict:
    """对单条推文计算多维度评分。

    输入：标准化的推文字典（来自 _parse_twitterapi_io）
    输出：附加 score_breakdown / total_score / grade 字段
    """
    rules = _load_rules()
    if not rules:
        return tweet

    scoring = rules.get("scoring", {})
    dimensions = scoring.get("dimensions", {})

    # 计算各维度原始值
    engagement_rate = tweet.get("engagement_rate", 0)
    followers = tweet.get("followers", 0)
    age_hours = _hours_ago(tweet.get("created_at", ""))
    text_length = len(tweet.get("text", ""))

    raw = {
        "engagement_rate": engagement_rate,
        "followers": followers,
        "hours_ago": age_hours,
        "text_length": text_length,
    }

    # 逐维度评分
    breakdown = {}
    total = 0.0
    for dim_key, dim_def in dimensions.items():
        weight = dim_def.get("weight", 0)
        raw_val = raw.get(dim_def.get("field"), 0)
        score = _dimension_score(raw_val, dim_def.get("mapping", []))
        weighted = round(score * weight, 2)
        breakdown[dim_key] = {
            "raw_value": raw_val if dim_def.get("field") != "hours_ago" else round(raw_val, 1),
            "score": round(score, 1),
            "weight": weight,
            "weighted": weighted,
        }
        total += weighted

    total = round(total, 2)

    # 等级判定
    grades = rules.get("grades", {}).get("thresholds", {})
    grade = "discard"
    if total >= grades.get("S", {}).get("min_total_score", 65):
        grade = "S"
    elif total >= grades.get("A", {}).get("min_total_score", 45):
        grade = "A"
    elif total >= grades.get("B", {}).get("min_total_score", 25):
        grade = "B"

    tweet["rule_score"] = total
    tweet["rule_grade"] = grade
    tweet["rule_breakdown"] = breakdown

    return tweet


def apply_exclusions(tweets: list[dict]) -> list[dict]:
    """应用排除规则，过滤掉不符合条件的推文。"""
    rules = _load_rules()
    if not rules:
        return tweets

    exclude_keywords = rules.get("filter_defaults", {}).get("exclude_keywords", [])
    exclude_rules = rules.get("filter_defaults", {}).get("exclude_if", {}).get("rules", [])

    filtered = []
    for t in tweets:
        text = (t.get("text", "") or "").lower()
        skip = False

        for kw in exclude_keywords:
            if kw.lower() in text:
                skip = True
                break
        if skip:
            continue

        for rule in exclude_rules:
            field = rule.get("field")
            condition = rule.get("condition")
            if field == "text" and condition == "length < 50":
                if len(t.get("text", "")) < 50:
                    skip = True
            elif field == "text" and condition == "contains_excluded_keyword":
                pass  # already handled above
            elif field == "followers" and condition == "> 50000":
                if t.get("followers", 0) > 50000:
                    skip = True
            elif field == "hours_ago" and condition == "> 168":
                age = _hours_ago(t.get("created_at", ""))
                if age > 168:
                    skip = True
            if skip:
                break
        if not skip:
            filtered.append(t)

    return filtered


def score_and_grade(tweets: list[dict]) -> dict:
    """对推文列表执行：排除 → 评分 → 分级 → 排序 → 截断。

    返回：{"S": [...], "A": [...], "B": [...], "discarded": count, "breakdown": {...}}
    """
    rules = _load_rules()
    limits = rules.get("grades", {}).get("per_topic_limits", {"S_max": 3, "A_max": 5})

    # 1. 排除
    kept = apply_exclusions(tweets)
    discarded = len(tweets) - len(kept)

    # 2. 逐条评分
    for t in kept:
        score_tweet(t)

    # 3. 按总分降序
    kept.sort(key=lambda t: t.get("rule_score", 0), reverse=True)

    # 4. 按等级分组，按限额截断
    result = {"S": [], "A": [], "B": []}
    for t in kept:
        grade = t.get("rule_grade", "discard")
        if grade == "S" and len(result["S"]) < limits.get("S_max", 3):
            result["S"].append(t)
        elif grade == "A" and len(result["A"]) < limits.get("A_max", 5):
            result["A"].append(t)
        elif grade == "B":
            result["B"].append(t)

    result["discarded"] = discarded
    result["breakdown"] = {
        "total_input": len(tweets),
        "excluded": discarded,
        "scored": len(kept),
        "S_count": len(result["S"]),
        "A_count": len(result["A"]),
        "B_count": len(result["B"]),
    }

    return result


def get_active_keywords() -> list[dict]:
    """获取所有活跃搜索关键词。"""
    rules = _load_rules()
    items = rules.get("search_keywords", {}).get("items", [])
    return [kw for kw in items if kw.get("active", True)]


_KEYWORD_STATS_FILE = Path.home() / ".media-agent" / "memory" / "insights" / "twitter" / "keyword_stats.json"


def _load_keyword_stats() -> dict:
    if not _KEYWORD_STATS_FILE.exists():
        return {}
    try:
        return json.loads(_KEYWORD_STATS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_keyword_usage(keyword: str, tweet_count: int) -> None:
    """记录一次关键词搜索（同步更新 discovery-rules.json 和 keyword_stats.json）。"""
    rules = _load_rules()
    items = rules.get("search_keywords", {}).get("items", [])
    for item in items:
        if item["keyword"] == keyword:
            perf = item.setdefault("performance", {})
            perf["searches"] = perf.get("searches", 0) + 1
            perf["last_result_count"] = tweet_count
            break
    _RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    global _RULES_CACHE
    _RULES_CACHE = None  # 失效缓存，下次重新加载

    # 同步更新 keyword_stats.json，保持两个文件的 searches 计数一致
    stats = _load_keyword_stats()
    if keyword not in stats:
        stats[keyword] = {"searches": 0, "total_er": 0.0, "total_score": 0.0, "total_tweets": 0}
    stats[keyword]["searches"] = stats[keyword].get("searches", 0) + 1
    stats[keyword]["total_tweets"] = stats[keyword].get("total_tweets", 0) + tweet_count
    _KEYWORD_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEYWORD_STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def record_post_feedback(source_keyword: str, post_engagement_rate: float, post_url: str) -> None:
    """发布后反哺：记录某关键词产出的推文表现。"""
    rules = _load_rules()
    items = rules.get("search_keywords", {}).get("items", [])
    for item in items:
        if item["keyword"] == source_keyword:
            perf = item.setdefault("performance", {})
            perf["posts_from"] = perf.get("posts_from", 0) + 1
            old_avg = perf.get("avg_post_engagement")
            n = perf["posts_from"]
            if old_avg is not None:
                perf["avg_post_engagement"] = round((old_avg * (n - 1) + post_engagement_rate) / n, 2)
            else:
                perf["avg_post_engagement"] = round(post_engagement_rate, 2)
            # 记录最佳
            if perf.get("best_post_engagement") is None or post_engagement_rate > perf["best_post_engagement"]:
                perf["best_post_engagement"] = post_engagement_rate
                perf["best_post_url"] = post_url
            break
    _RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    global _RULES_CACHE
    _RULES_CACHE = None  # 下次重新加载
