"""
cli.platforms.twitter.create — Twitter 内容生成模块

职责：
  - 基于模板库生成推文/Thread/钩子的结构化草稿
  - 不执行实际 AI 文本生成（由 Agent 层完成），只返回草稿模板和模板引用

一件事原则：
  - 只做"生成草稿结构"，不发现内容，不分析，不发布
  - 输出统一的 draft.json 结构，供 Agent 层填充实际内容

命令映射：
  mekit twitter create tweet --topic="AI工具推荐" --style=educational
  mekit twitter create thread --topic="省钱工具" --style=story-driven
  mekit twitter create hook --topic="免费替代品" --style=hot-take
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from cli.core.registry import command

_TEMPLATES_DIR = Path("memory/templates/twitter")
_DRAFTS_DIR = Path(".media-agent/shared/drafts/twitter")


def _load_top_templates(template_type: str, limit: int = 5) -> list[dict]:
    """按 score 降序加载模板。"""
    type_dir = _TEMPLATES_DIR / template_type
    if not type_dir.exists():
        return []
    templates = []
    for f in type_dir.glob("*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            if t.get("status") == "active":
                templates.append(t)
        except (json.JSONDecodeError, OSError):
            continue
    templates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return templates[:limit]


def _generate_draft_id() -> str:
    """生成唯一的草稿 ID。"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"draft-{ts}"


@command("twitter", "create", "tweet")
def create_tweet(topic: str = "", style: str = "educational", **kwargs) -> dict:
    """生成单条推文草稿。"""
    hooks = _load_top_templates("hooks", 5)
    ctas = _load_top_templates("ctas", 3)

    draft_id = _generate_draft_id()
    draft = {
        "draft_id": draft_id,
        "platform": "twitter",
        "type": "tweet",
        "status": "draft",
        "text": "",
        "hook_type": hooks[0]["category"] if hooks else "",
        "structure_type": "",
        "cta_type": ctas[0]["category"] if ctas else "",
        "template_refs": [],
        "source_tweet_url": None,
        "source_type": "original",
        "media_paths": [],
        "scheduled_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "published_at": None,
        "published_tweet_url": None,
        "published_tweet_id": None,
        "post_metrics": None,
    }

    for t in hooks[:2]:
        draft["template_refs"].append({
            "template_id": t["template_id"], "type": "hook", "score": t["score"]
        })
    for t in ctas[:1]:
        draft["template_refs"].append({
            "template_id": t["template_id"], "type": "cta", "score": t["score"]
        })

    return {"draft": draft, "topic": topic, "style": style}


@command("twitter", "create", "thread")
def create_thread(topic: str = "", style: str = "educational", **kwargs) -> dict:
    """生成 Thread 草稿结构。"""
    hooks = _load_top_templates("hooks", 5)
    structures = _load_top_templates("structures", 5)
    ctas = _load_top_templates("ctas", 3)

    draft_id = _generate_draft_id()
    draft = {
        "draft_id": draft_id,
        "platform": "twitter",
        "type": "thread",
        "status": "draft",
        "text": "",
        "hook_type": hooks[0]["category"] if hooks else "",
        "structure_type": structures[0]["category"] if structures else "",
        "cta_type": ctas[0]["category"] if ctas else "",
        "template_refs": [],
        "source_tweet_url": None,
        "source_type": "original",
        "media_paths": [],
        "scheduled_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "published_at": None,
        "published_tweet_url": None,
        "published_tweet_id": None,
        "post_metrics": None,
    }

    for t in hooks[:2]:
        draft["template_refs"].append({
            "template_id": t["template_id"], "type": "hook", "score": t["score"]
        })
    for t in structures[:1]:
        draft["template_refs"].append({
            "template_id": t["template_id"], "type": "structure", "score": t["score"]
        })
    for t in ctas[:1]:
        draft["template_refs"].append({
            "template_id": t["template_id"], "type": "cta", "score": t["score"]
        })

    return {"draft": draft, "topic": topic, "style": style}


@command("twitter", "create", "hook")
def create_hook(topic: str = "", style: str = "hot-take", **kwargs) -> dict:
    """生成钩子备选列表。"""
    hooks = _load_top_templates("hooks", 7)

    variants = []
    for t in hooks:
        variants.append({
            "template_id": t["template_id"],
            "category": t["category"],
            "pattern": t["pattern"],
            "example": t["example"],
            "score": t["score"],
            "suggestion": f"基于「{t['category']}」模板，结合主题「{topic}」生成钩子",
        })

    return {
        "topic": topic,
        "style": style,
        "variants": variants,
        "total_templates": len(hooks),
    }
