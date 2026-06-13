"""
cli.core.upgrade — mekit CLI 自动升级（参照 Orca 模式）

在 mekit 每次启动时检查是否需要升级：
- 通过 uv tool upgrade 将 CLI 升级到插件 repo 最新版
- 节流：默认 24 小时内最多检查一次
- 非阻塞：后台执行，不影响当前命令
- 可通过 MEKIT_NO_AUTO_UPGRADE=1 环境变量禁用
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def _get_upgrade_check_file() -> Path:
    """升级检查时间戳文件：~/.media-agent/.mekit-upgrade-check"""
    media_dir = Path.home() / ".media-agent"
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir / ".mekit-upgrade-check"


def _should_check_upgrade() -> bool:
    """判断是否应该检查升级（节流：24 小时内最多一次）。"""
    check_file = _get_upgrade_check_file()
    if not check_file.exists():
        return True

    try:
        last_check = float(check_file.read_text().strip())
        elapsed = time.time() - last_check
        return elapsed > 86400  # 24 小时
    except (ValueError, OSError):
        return True


def _mark_upgrade_checked() -> None:
    """记录本次检查时间戳。"""
    _get_upgrade_check_file().write_text(str(time.time()))


def check_and_upgrade() -> None:
    """检查并后台升级 mekit CLI（非阻塞，静默失败）。

    仅在 mekit 通过 uv tool 安装时生效。
    pip install / dev 模式下自动跳过。
    """
    if os.environ.get("MEKIT_NO_AUTO_UPGRADE"):
        return

    if not _should_check_upgrade():
        return

    _mark_upgrade_checked()

    # 优先用 shutil.which，回退硬编码
    try:
        from shutil import which
    except ImportError:
        which = lambda x: x  # noqa: E731

    uv_cmd = which("uv") or ("uv.exe" if sys.platform == "win32" else "uv")
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        popen_kwargs["stdout"] = subprocess.DEVNULL
        popen_kwargs["stderr"] = subprocess.DEVNULL

    try:
        # 检查 mediakit 是否通过 uv tool 安装
        result = subprocess.run(
            [uv_cmd, "tool", "list"],
            capture_output=True, text=True, timeout=15,
            **popen_kwargs,
        )
        if "mediakit" not in result.stdout:
            return  # 不是 uv tool 安装的，跳过

        # 后台升级，不阻塞当前命令
        subprocess.Popen(
            [uv_cmd, "tool", "upgrade", "mediakit"],
            **popen_kwargs,
        )
    except Exception:
        # 任何异常静默吞掉，不影响 CLI 主流程
        pass
