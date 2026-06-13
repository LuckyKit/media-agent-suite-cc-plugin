"""
cli.platforms.twitter — Twitter/X 平台适配器

职责：
  - 实现 Twitter/X 相关的发现、分析、发布能力
  - 三件事严格分离：discover.py / analyze.py / publish.py

设计原则：
  - 只处理 Twitter/X，绝不涉及 YouTube 或其他平台
  - 所有 Twitter API v2 / Scraping 调用封装在本包内
  - Bearer Token 从 cli.core.config 读取，不硬编码

一件事：
  本包只做"Twitter 平台交互"，不做策略决策、内容创作或跨平台编排。
"""
