"""
cli.platforms.twitter.evolve — Twitter 自进化模块

职责：
  - 分析历史数据（SQLite + history.jsonl + template_usage.jsonl），计算 KPI 指标
  - 读取模板追踪数据，输出模板使用×互动率关联，供 Agent 更新评分
  - 生成改进建议

一件事原则：
  - 只做"数据分析与进化建议"，不发现新内容，不创作，不发布

命令映射：
  mekit twitter evolve analyze --since=7d
  mekit twitter evolve suggest
  mekit twitter evolve apply --insight-id=xxx
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cli.core.registry import command
from cli.core.storage import DataStore

_HISTORY_FILE = Path(".media-agent/shared/history.jsonl")
_PHASE_FILE = Path("memory/phase.json")
_USER_HISTORY = Path.home() / ".media-agent" / "memory" / "history.jsonl"
_TEMPLATE_TRACKING = Path(".media-agent/shared/tracking/twitter/template_usage.jsonl")
_KEYWORD_STATS = Path.home() / ".media-agent" / "memory" / "insights" / "twitter" / "keyword_stats.json"


def _read_jsonl(path: Path) -> list[dict]:
    """读取 JSONL 文件。"""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def _load_json(path: Path) -> dict:
    """安全加载 JSON 文件。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_phase() -> dict:
    """加载阶段追踪数据。"""
    return _load_json(_PHASE_FILE)


def _get_template_usage_stats(days: int = 7) -> list[dict]:
    """从模板追踪文件统计各模板的使用次数和待评分状态。"""
    records = _read_jsonl(_TEMPLATE_TRACKING)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 按 template_id 聚合
    template_stats: dict[str, dict] = {}
    for r in records:
        try:
            t = datetime.fromisoformat(r.get("time", "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if t < cutoff:
            continue

        for ref in r.get("template_refs", []):
            tid = ref.get("template_id", "")
            if not tid:
                continue
            if tid not in template_stats:
                template_stats[tid] = {
                    "template_id": tid,
                    "type": ref.get("type", ""),
                    "score": ref.get("score", 0),
                    "times_used": 0,
                    "tweets": [],
                    "score_updated": r.get("score_updated", False),
                }
            template_stats[tid]["times_used"] += 1
            template_stats[tid]["tweets"].append({
                "tweet_url": r.get("tweet_url"),
                "tweet_id": r.get("tweet_id"),
                "time": r.get("time"),
                "engagement_data": r.get("engagement_data"),
            })

    return sorted(template_stats.values(), key=lambda x: x["times_used"], reverse=True)


def _get_keyword_performance() -> dict:
    """读取关键词效果统计。"""
    return _load_json(_KEYWORD_STATS)


@command("twitter", "evolve", "analyze")
def evolve_analyze(since: str = "7d", **kwargs) -> dict:
    """分析 Twitter 历史数据，输出 KPI 仪表盘 + 模板追踪 + 关键词效果。"""
    days = 7
    if since.endswith("d"):
        try:
            days = int(since[:-1])
        except ValueError:
            pass
    elif since == "30d":
        days = 30
    elif since == "all":
        days = 365

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    project_records = _read_jsonl(_HISTORY_FILE)
    user_records = _read_jsonl(_USER_HISTORY)
    all_records = project_records + user_records

    filtered = []
    for r in all_records:
        try:
            t = datetime.fromisoformat(r.get("time", "").replace("Z", "+00:00"))
            if t >= cutoff:
                filtered.append(r)
        except (ValueError, TypeError):
            continue

    publish_actions = [r for r in filtered if "publish" in r.get("action", "")]
    discover_actions = [r for r in filtered if "discover" in r.get("action", "")]
    analyze_actions = [r for r in filtered if "analyze" in r.get("action", "")]

    store = DataStore("twitter.discover", mode="store")
    store_stats = store.stats()

    phase_data = _load_phase()
    current_phase = phase_data.get("current_phase", 0)
    phase_def = phase_data.get("phase_definitions", {}).get(str(current_phase), {})

    # 模板追踪 — 这是自进化的核心数据
    template_usage = _get_template_usage_stats(days)

    # 关键词效果 — 供下次搜索优选
    keyword_perf = _get_keyword_performance()

    warnings = []
    if days >= 7 and len(publish_actions) < days * 0.5:
        warnings.append(f"发布频率偏低：{days} 天内仅发布 {len(publish_actions)} 条")
    if len(publish_actions) == 0 and days >= 7:
        warnings.append("该时间段内无发布记录，无法计算互动率")

    # 模板待评分提醒
    pending_scoring = [t for t in template_usage if not t["score_updated"]]
    if pending_scoring:
        warnings.append(
            f"有 {len(pending_scoring)} 个模板引用尚未关联互动数据，"
            "请在复盘中提供各推文的互动数据以完成模板评分闭环"
        )

    return {
        "period": f"last_{days}d",
        "cutoff": cutoff.isoformat(),
        "summary": {
            "total_publishes": len(publish_actions),
            "total_discovers": len(discover_actions),
            "total_analyzes": len(analyze_actions),
            "daily_avg_publishes": round(len(publish_actions) / max(days, 1), 1),
            "store_records": (
                store_stats.get("store", {}).get("records", 0)
                if store_stats.get("store") else 0
            ),
            "store_days": (
                store_stats.get("store", {}).get("days", 0)
                if store_stats.get("store") else 0
            ),
        },
        "phase": {
            "current": current_phase,
            "name": phase_def.get("name", "未知"),
            "exit_criteria": phase_def.get("exit_criteria", {}),
        },
        "published_tweets": [
            {
                "time": r.get("time"),
                "tweet_url": r.get("tweet_url"),
                "tweet_id": r.get("tweet_id"),
            }
            for r in publish_actions if r.get("tweet_url")
        ],
        "template_usage": template_usage,
        "keyword_performance": keyword_perf,
        "warnings": warnings,
    }


@command("twitter", "evolve", "suggest")
def evolve_suggest(**kwargs) -> dict:
    """基于历史分析生成改进建议。"""
    template_usage = _get_template_usage_stats(7)
    keyword_perf = _get_keyword_performance()

    suggestions = []

    # 1. 模板评分建议
    pending = [t for t in template_usage if not t["score_updated"]]
    if pending:
        suggestions.append({
            "insight_id": "suggest-template-score",
            "category": "模板评分",
            "finding": f"有 {len(pending)} 个模板需要关联互动数据",
            "suggestion": "在复盘中逐一提供互动率，系统自动更新模板评分",
            "expected_impact": "模板评分越准确，生成内容质量越高",
            "risk": "低",
        })

    # 2. 关键词优化建议
    if keyword_perf:
        best_kw = max(keyword_perf.items(), key=lambda x: x[1].get("avg_engagement_rate", 0)) if keyword_perf else None
        if best_kw:
            suggestions.append({
                "insight_id": "suggest-keyword",
                "category": "关键词优化",
                "finding": f"关键词 '{best_kw[0]}' 历史均互动率 {best_kw[1].get('avg_engagement_rate', 0)}%",
                "suggestion": f"后续搜索优先使用 '{best_kw[0]}'",
                "expected_impact": "提高发现素材的质量",
                "risk": "低",
            })

    # 3. 如果数据不足
    if not suggestions:
        suggestions.append({
            "insight_id": "suggest-data-needed",
            "category": "数据积累",
            "finding": "需要至少 7 天的发布数据才能生成有意义的建议",
            "suggestion": "保持每日 1-2 条推文的发布频率，积累数据后重新分析",
            "expected_impact": "建立数据基线",
            "risk": "低",
        })

    return {
        "suggestions": suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


_TEMPLATES_DIR = Path("memory/templates/twitter")


def _find_template_file(template_id: str) -> Path | None:
    """在 memory/templates/twitter/ 下查找指定 template_id 的文件。

    优先按 {template_id}.json 直接寻址（O(1)），回退到全量扫描（兼容旧文件名）。
    """
    # 快速路径：模板文件名与 template_id 对应（新约定）
    for subdir in _TEMPLATES_DIR.iterdir() if _TEMPLATES_DIR.exists() else []:
        candidate = subdir / f"{template_id}.json"
        if candidate.exists():
            return candidate

    # 慢速路径：兼容旧文件名（按内容匹配）
    for f in _TEMPLATES_DIR.rglob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            if t.get("template_id") == template_id:
                return f
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _update_template_score(template_path: Path, engagement_rate: float | None, delta: int | None) -> dict:
    """更新模板评分，返回更新摘要。"""
    t = json.loads(template_path.read_text(encoding="utf-8"))
    old_score = t.get("score", 5)

    if delta is not None:
        new_score = old_score + delta
    elif engagement_rate is not None:
        if engagement_rate > 3.0:
            new_score = old_score + 1
        elif engagement_rate < 1.5:
            new_score = old_score - 1
        else:
            new_score = old_score
    else:
        return {"changed": False, "reason": "未提供 --engagement-rate 或 --delta"}

    new_score = max(1, min(10, new_score))  # 限制在 [1, 10]

    # 追加评分历史
    score_history = t.get("score_history", [])
    score_history.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "old_score": old_score,
        "new_score": new_score,
        "engagement_rate": engagement_rate,
        "delta": new_score - old_score,
    })
    t["score"] = new_score
    t["score_history"] = score_history[-20:]  # 只保留最近 20 条

    # 更新互动率均值
    if engagement_rate is not None:
        times_used = t.get("times_used", 0) + 1
        prev_avg = t.get("avg_engagement_rate") or 0.0
        t["avg_engagement_rate"] = round(
            (prev_avg * (times_used - 1) + engagement_rate) / times_used, 2
        )
        t["times_used"] = times_used

    # 退役检查
    retire_threshold = t.get("retire_if_score_below", 4)
    consecutive_low = sum(
        1 for h in score_history[-3:] if h.get("engagement_rate") is not None and h["engagement_rate"] < 2.0
    )
    if new_score < retire_threshold or consecutive_low >= 3:
        t["status"] = "retired"

    template_path.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "changed": new_score != old_score,
        "old_score": old_score,
        "new_score": new_score,
        "status": t["status"],
        "retired": t["status"] == "retired",
    }


def _mark_usage_scored(template_id: str) -> int:
    """将 template_usage.jsonl 中含该 template_id 且 score_updated=False 的条目标记为已评分。

    使用原子写（临时文件 → rename）避免崩溃导致文件截断。
    """
    if not _TEMPLATE_TRACKING.exists():
        return 0

    lines = _TEMPLATE_TRACKING.read_text(encoding="utf-8").splitlines()
    updated_count = 0
    new_lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if not r.get("score_updated") and any(
                ref.get("template_id") == template_id for ref in r.get("template_refs", [])
            ):
                r["score_updated"] = True
                updated_count += 1
            new_lines.append(json.dumps(r, ensure_ascii=False))
        except json.JSONDecodeError:
            new_lines.append(line)

    # 原子写：先写临时文件，再 replace（rename），避免崩溃导致文件截断
    tmp = _TEMPLATE_TRACKING.with_suffix(".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(_TEMPLATE_TRACKING)
    return updated_count


@command("twitter", "evolve", "apply")
def evolve_apply(
    template_id: str = "",
    engagement_rate: float | None = None,
    delta: int | None = None,
    insight_id: str = "",
    **kwargs,
) -> dict:
    """更新模板评分并标记追踪记录为已评分。

    用法:
      mekit twitter evolve apply --template-id=hook-xxx --engagement-rate=6.2
      mekit twitter evolve apply --template-id=hook-xxx --delta=1
    """
    if not template_id:
        return {
            "ok": False,
            "error": {"code": "MISSING_PARAM", "message": "缺少参数: --template-id"},
        }

    template_path = _find_template_file(template_id)
    if template_path is None:
        return {
            "ok": False,
            "error": {
                "code": "TEMPLATE_NOT_FOUND",
                "message": f"未找到模板: {template_id}",
                "hint": "检查 memory/templates/twitter/ 下的 template_id 是否正确",
            },
        }

    score_result = _update_template_score(template_path, engagement_rate, delta)
    usage_updated = _mark_usage_scored(template_id)

    return {
        "ok": True,
        "template_id": template_id,
        "template_file": str(template_path),
        "score": score_result,
        "usage_records_marked": usage_updated,
        "message": (
            f"模板 {template_id} 评分 {score_result['old_score']} → {score_result['new_score']}"
            + (f"（已退役）" if score_result.get("retired") else "")
            + f"，{usage_updated} 条追踪记录标记为已评分"
        ),
    }
