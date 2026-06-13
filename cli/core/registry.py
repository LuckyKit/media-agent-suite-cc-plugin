"""
cli.core.registry — 命令注册中心

职责：
  - 提供 @command(platform, action, target) 装饰器，用于注册 CLI 命令
  - 维护全局 _COMMANDS 注册表：{(platform, action, target): handler_func}
  - 提供 list_commands() / get_command(platform, action, target) 查询接口

设计原则：
  - 注册发生在模块导入时（装饰器副作用），零配置发现
  - 平台适配器只需 import 本模块并使用装饰器，无需修改中央文件
  - 注册表只读暴露，禁止运行时修改（防并发问题）
"""

from typing import Callable

# 全局命令注册表，结构：{(platform, action, target): callable}
_COMMANDS: dict[tuple[str, str, str], Callable] = {}


def command(platform: str, action: str, target: str):
    """主谓宾命令注册装饰器。"""

    def decorator(func: Callable) -> Callable:
        key = (platform, action, target)
        if key in _COMMANDS:
            raise ValueError(
                f"命令重复注册: ({platform}, {action}, {target}) "
                f"已指向 {_COMMANDS[key].__module__}.{_COMMANDS[key].__name__}"
            )
        _COMMANDS[key] = func
        return func

    return decorator


def get_command(platform: str, action: str, target: str) -> Callable | None:
    """根据主谓宾三元组获取命令处理器，未找到返回 None。"""
    return _COMMANDS.get((platform, action, target))


def list_commands() -> list[tuple[str, str, str]]:
    """返回所有已注册的 (platform, action, target) 列表。"""
    return list(_COMMANDS.keys())
