"""
cli.platforms — 平台适配器包

职责：
  - 容纳所有社交媒体平台的 CLI 适配器
  - 每个平台一个独立子目录，内部三件事分离：discover / analyze / publish

约束（强制执行）：
  - 平台之间禁止互相 import（如 youtube 不得 import twitter）
  - 平台只能依赖 cli.core.*，不得依赖其他平台
  - 所有平台共享 base.py 的抽象接口，但实现完全独立

当前平台：
  - youtube/ — YouTube 平台适配
  - twitter/ — Twitter/X 平台适配
"""
