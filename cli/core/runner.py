"""
cli.core.runner — 命令解析与执行器

职责：
  - 将 sys.argv 解析为 (platform: str, action: str, target: str, options: dict)
  - 从 registry 查找对应 handler
  - 调用 handler，将其返回值包装为统一协议输出
  - 捕获所有异常，转换为 protocol 错误格式
  - 支持 Hook 调用（pre-action / post-action）

设计原则：
  - 只做路由与协议包装，不做任何业务逻辑
  - 每个请求独立，无全局可变状态
  - 异常隔离：handler 崩溃不影响 runner 本身
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from cli.core.config import get_config
from cli.core.protocol import emit_data, emit_error
from cli.core.registry import get_command


USAGE = """\
mekit — MediaKit 社交媒体运营工具箱

用法: mekit <platform> <action> <target> [options]

平台 (platform):
  twitter        Twitter/X 内容运营

动作 (action):
  discover       发现爆款内容
  analyze        分析内容/账号
  create         生成内容
  publish        发布内容

目标 (target):
  discover:      tweets / spaces
  analyze:       tweet / thread / user / hashtag
  create:        thread / tweet / hook
  publish:       tweet / thread

选项:
  --output=pretty        人类可读 JSON 输出
  --region=US            地区过滤
  --lang=zh              语言过滤（zh/en/ja 等）
  --category=gaming      内容分类
  --limit=20             结果数量限制
  --url=...              目标 URL
  --hashtag=...           话题标签
  --hours=168            时间范围（小时，默认168=1周）
  --min-followers=2000    最低粉丝数过滤（默认2000）
  --keyword=...          搜索关键词
  --viral                按互动率排序
  --personal             只看素人（<5 万粉）
  --diverse              每个作者最多 1 条
  --fresh                跳过缓存 + 过滤已看
  --min-followers=1000    最低粉丝数过滤

示例:
  mekit twitter discover tweets --keyword="deepseek codex"
  mekit twitter analyze tweet --url="https://x.com/..."
  mekit twitter discover tweets --hashtag="claude" --viral
  mekit twitter discover tweets --keyword="MIT license" --min-followers=1000
  mekit cache stats"""


def _parse_argv(argv: list[str]) -> tuple[str, str, str, dict[str, any], bool]:
    """解析命令行参数，提取主谓宾和选项。"""
    if len(argv) < 3:
        raise ValueError("参数不足，至少需要 <platform> <action> <target>")

    platform = argv[0]
    action = argv[1]
    target = argv[2]

    options: dict[str, any] = {}
    pretty = False

    i = 3
    while i < len(argv):
        arg = argv[i]
        if arg == "--output=pretty":
            pretty = True
            i += 1
            continue
        if arg.startswith("--"):
            # --key=value 或 --key value 或 --key
            key = arg[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                options[k] = _coerce_type(v)
                i += 1
            else:
                # 查看下一个 arg 是否是值（不是 -- 开头）
                if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                    options[key] = _coerce_type(argv[i + 1])
                    i += 2
                else:
                    options[key] = True
                    i += 1
        else:
            # 位置参数，忽略
            i += 1

    return platform, action, target, options, pretty


def _coerce_type(value: str) -> str | int | float | bool:
    """将字符串参数转换为合适的 Python 类型。"""
    # 布尔值
    lowered = value.lower()
    if lowered in ("true", "yes", "1"):
        return True
    if lowered in ("false", "no", "0"):
        return False
    # 整数
    try:
        return int(value)
    except ValueError:
        pass
    # 浮点数
    try:
        return float(value)
    except ValueError:
        pass
    # 字符串（去掉引号）
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _call_hook_in_process(platform: str, action: str, timing: str, payload: dict) -> dict:
    """调用内嵌 Hook 函数（优先），不存在时返回 None 表示无内嵌 hook。"""
    try:
        from cli.platforms.twitter.hooks import get_hook
        hook_fn = get_hook(platform, action, timing)
        if hook_fn is not None:
            return hook_fn(payload)
    except ImportError:
        pass
    return None  # sentinel: 无内嵌 hook，回退到外部脚本


def _call_hook_external(hook_path: str, payload: dict) -> dict:
    """调用外部 Hook 脚本（子进程方式，仅用于未内嵌的自定义 hook）。"""
    resolved = Path(hook_path)
    if not resolved.exists():
        config = get_config()
        alt = config._project_root / hook_path
        if alt.exists():
            resolved = alt
        else:
            return {"ok": True}

    try:
        proc = subprocess.run(
            [sys.executable, str(resolved)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "errors": [f"Hook 退出码 {proc.returncode}: {proc.stderr.strip()}"],
            }
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "errors": [f"Hook 输出不是合法 JSON: {proc.stdout.strip()[:200]}"]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "errors": ["Hook 执行超时（30s）"]}
    except Exception as e:
        return {"ok": False, "errors": [f"Hook 调用异常: {e}"]}


def _call_hook(platform: str, action: str, timing: str, payload: dict) -> dict:
    """调用 Hook：优先内嵌函数，回退到 mediakit.toml 配置的外部脚本。"""
    # 1. 优先内嵌 hook
    result = _call_hook_in_process(platform, action, timing, payload)
    if result is not None:
        return result

    # 2. 回退外部脚本（兼容旧版 / 自定义 hook）
    config = get_config()
    hook_key = f"{timing}-{action}"
    hook_path = config.get("hooks", platform, hook_key, default=None)
    if hook_path:
        return _call_hook_external(hook_path, payload)

    return {"ok": True}


def run(argv: list[str]) -> dict:
    """解析参数并执行对应命令，返回统一协议字典。"""
    # --help / -h：打印帮助文本并退出
    if not argv or any(a in ("--help", "-h") for a in argv):
        print(USAGE)
        sys.exit(0)

    start_time = time.time()

    # 1. 解析参数
    try:
        platform, action, target, options, pretty = _parse_argv(argv)
    except ValueError as e:
        return emit_error(
            "ARG_PARSE_ERROR", str(e), hint="用法: mekit <platform> <action> <target> [options]"
        )

    cmd_str = f"{platform} {action} {target}"

    # 2. 查找 handler
    handler = get_command(platform, action, target)
    if handler is None:
        return emit_error(
            "COMMAND_NOT_FOUND",
            f"未找到命令: {cmd_str}",
            hint=f"已注册命令: {', '.join(f'{p} {a} {t}' for p, a, t in __import__('cli.core.registry', fromlist=['list_commands']).list_commands())}",
        )

    # 3. 调用 pre-hook
    pre_result = _call_hook(platform, action, "pre", {
        "platform": platform,
        "action": action,
        "target": target,
        "args": options,
    })
    if not pre_result.get("ok", True):
        errors = pre_result.get("errors", ["pre-hook 阻断"])
        return emit_error("PRE_HOOK_BLOCKED", "; ".join(errors))

    # 4. 执行 handler
    try:
        data = handler(**options)
    except Exception as e:
        return emit_error(
            "HANDLER_ERROR",
            f"命令执行失败: {e}",
            hint="检查参数是否正确，或查看日志获取详细堆栈",
        )

    # 5. 调用 post-hook（记录失败但不阻断主响应）
    post_result = _call_hook(platform, action, "post", {
        "platform": platform,
        "action": action,
        "target": target,
        "args": options,
        "result": data,
    })
    if not post_result.get("ok", True):
        import sys
        print(
            f"[mekit warn] post-hook {platform}/{action} 失败: "
            + "; ".join(post_result.get("errors", ["未知错误"])),
            file=sys.stderr,
        )

    # 6. 包装输出
    result = emit_data(data, cmd=cmd_str, start_time=start_time)
    if pretty:
        result["meta"]["pretty"] = True
    return result
