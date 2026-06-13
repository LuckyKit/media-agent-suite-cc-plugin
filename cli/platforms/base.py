"""
cli.platforms.base — 平台抽象基类

职责：
  - 定义 Platform 抽象接口，约定每个平台必须实现的能力签名
  - 提供通用工具方法（HTTP 请求重试、日志、本地缓存、速率限制）

抽象方法（子类可选实现）：
  - discover_trending(**kwargs) -> dict
  - discover_search(**kwargs) -> dict
  - analyze_video(url, **kwargs) -> dict
  - analyze_tweet(url, **kwargs) -> dict
  - publish_video(draft, **kwargs) -> dict
  - publish_tweet(draft, **kwargs) -> dict

设计原则：
  - 基类无状态，所有数据通过方法参数传递
  - 子类只覆盖需要定制的方法，不强制全部实现
  - 未实现的方法返回 {"ok": false, "error": {"code": "NOT_IMPLEMENTED"}}
"""

from abc import ABC, abstractmethod


class Platform(ABC):
    """平台适配器抽象基类。"""

    name: str = ""

    @abstractmethod
    def discover_trending(self, **kwargs) -> dict:
        """发现趋势内容，返回统一协议格式。"""
        pass

    @abstractmethod
    def analyze_content(self, content_id: str, **kwargs) -> dict:
        """分析单个内容，返回统一协议格式。"""
        pass

    @abstractmethod
    def publish(self, draft: dict, **kwargs) -> dict:
        """发布内容，返回统一协议格式。"""
        pass
