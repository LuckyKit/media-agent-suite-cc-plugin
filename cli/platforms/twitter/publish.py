"""
cli.platforms.twitter.publish — Twitter 发布模块

职责：
  - 推文发布（纯文本 / 媒体 / 投票 Poll）
  - Thread 串发布（多推文联发）
  - 定时发布（利用第三方调度或 Twitter API 的 schedule）
  - 草稿管理（本地草稿 JSON 的读取与校验）

一件事原则：
  - 只做"发布执行"，不发现趋势，不分析竞品，不撰写文案
  - 所有发布操作必须通过 hooks/pre-publish.py 安全检查
  - Thread 发布需保证原子性：要么全部发完，要么全部不发

命令映射：
  mekit twitter publish tweet --draft=./draft.json
  mekit twitter publish thread --draft=./draft.json
"""

from cli.core.registry import command


@command("twitter", "publish", "tweet")
def publish_tweet(draft: str, **kwargs) -> dict:
    """发布单条推文。"""
    pass


@command("twitter", "publish", "thread")
def publish_thread(draft: str, **kwargs) -> dict:
    """发布 Thread 串。"""
    pass
