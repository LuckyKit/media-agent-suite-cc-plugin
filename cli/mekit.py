#!/usr/bin/env python3
"""
mekit — MediaKit CLI 唯一入口

职责：
  - 解析命令行参数：mekit <platform> <action> <target> [options]
  - 委托 cli.core.runner 执行对应命令
  - 输出统一协议 JSON（ok / data / error / meta）

使用示例：
  mekit twitter discover tweets --keyword="deepseek codex"
  mekit twitter discover tweets --hashtag="claude" --viral --personal
"""

import json
import sys


def _ensure_platforms_loaded() -> None:
    """动态导入所有平台模块，触发 @command 装饰器注册。"""
    import importlib

    for module in ("discover", "analyze", "publish", "create", "evolve", "hooks"):
        try:
            importlib.import_module(f"cli.platforms.twitter.{module}")
        except ImportError:
            pass


def main() -> None:
    """CLI 入口点：加载 .env、解析参数、执行命令、输出 JSON 结果。"""
    # Windows 控制台强制 UTF-8，避免 emoji 输出报错
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    # 触发配置加载（包含 .env 注入 os.environ）
    from cli.core.config import get_config

    get_config()

    # 自动升级检查（uv tool upgrade，非阻塞，24h 节流）
    from cli.core.upgrade import check_and_upgrade

    check_and_upgrade()

    _ensure_platforms_loaded()

    from cli.core.runner import run

    result = run(sys.argv[1:])

    # 根据 pretty 标志决定输出格式
    pretty = result.get("meta", {}).get("pretty", False)
    indent = 2 if pretty else None

    print(json.dumps(result, ensure_ascii=False, indent=indent))

    # 非零退出码表示错误
    if not result.get("ok", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
