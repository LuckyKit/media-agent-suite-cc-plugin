"""
cli.core.config — 配置管理

职责：
  - 读取项目根目录 mediakit.toml 配置
  - 读取环境变量（MKIT_* / YOUTUBE_API_KEY / TWITTERAPI_IO_KEY 等）
  - 提供 get_platform_config(platform: str) -> dict 接口

设计原则：
  - 配置单例，进程级懒加载缓存
  - 敏感信息（密钥、Token）只能从环境变量读取，禁止写入任何配置文件
  - 环境变量优先级高于 mediakit.toml
  - 配置不可变（返回深拷贝或只读视图）
"""

import os
import re
from copy import deepcopy
from pathlib import Path

# 尝试导入 tomli（Python < 3.11），否则用标准库 tomllib
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# 进程级配置缓存
_CONFIG_CACHE: dict[str, "ConfigManager"] = {}


class ConfigManager:
    """配置管理器，进程级单例。"""

    def __init__(self, project_root: Path | None = None):
        """初始化配置管理器，自动发现项目根目录。"""
        self._project_root = project_root or self._find_project_root()
        self._toml: dict = {}
        self._local_toml: dict = {}
        self._env: dict[str, str] = {}
        self._loaded = False

    def _find_project_root(self) -> Path:
        """从当前目录向上查找包含 mediakit.toml 的目录。

        优先级：
          1. 环境变量 MKIT_PROJECT_ROOT（test_claude 隔离环境会设置）
          2. 从 cwd 向上遍历查找 mediakit.toml
          3. 兜底返回 cwd
        """
        env_root = os.environ.get("MKIT_PROJECT_ROOT")
        if env_root and Path(env_root).is_dir():
            return Path(env_root)

        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            if (parent / "mediakit.toml").exists():
                return parent
        return cwd

    def _load(self) -> None:
        """懒加载配置，只执行一次。"""
        if self._loaded:
            return

        # 1. 加载 mediakit.toml
        toml_path = self._project_root / "mediakit.toml"
        if toml_path.exists():
            with toml_path.open("rb") as f:
                self._toml = tomllib.load(f)

        # 2. 加载 mediakit.local.toml（本地覆盖）
        local_path = self._project_root / "mediakit.local.toml"
        if local_path.exists():
            with local_path.open("rb") as f:
                self._local_toml = tomllib.load(f)

        # 3. 从 .env 文件加载环境变量（按优先级，高覆盖低）
        self._env = self._load_dotenv_files()

        self._loaded = True

    def _load_dotenv_files(self) -> dict[str, str]:
        """按优先级加载 .env 文件，注入 os.environ，返回合并后的环境变量字典。"""
        import re

        result = dict(os.environ)
        whitelist = re.compile(
            r"^(MKIT_|YOUTUBE_|TWITTERAPI_IO_|TWITTER_|SOCIALDATA_|FEISHU_|SLACK_|ANTHROPIC_|OPENAI_|CLAUDE_)"
        )

        def _load(path: Path) -> None:
            if not path.is_file():
                return
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not key or not whitelist.match(key):
                    continue
                # 文件级 .env 不覆盖已存在的环境变量
                if key not in result:
                    result[key] = val
                    os.environ[key] = val

        # 加载顺序 = 优先级从低到高：
        #   用户级 ~/.media-agent/.env  → 项目根 .env  → 项目 .media-agent/.env
        # 因为 _load 只在 key 不存在时写入，所以先加载的优先级更高。
        # 即：用户级 > 项目根 > 项目 .media-agent（用户个人 Key 不被项目覆盖）
        _load(Path.home() / ".media-agent" / ".env")
        _load(self._project_root / ".env")
        _load(self._project_root / ".media-agent" / ".env")

        return result

    def get(self, *keys: str, default: "any" = None) -> "any":
        """按层级读取配置，支持深度访问。"""
        self._load()
        # 优先级：环境变量 > local.toml > mediakit.toml
        for source in (self._env, self._local_toml, self._toml):
            value = source
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    break
            else:
                # 解析占位符如 "${TWITTER_BEARER_TOKEN}"
                if isinstance(value, str):
                    value = self._resolve_placeholder(value)
                return value
        return default

    def _resolve_placeholder(self, value: str) -> str:
        """解析配置中的 ${ENV_VAR} 占位符为环境变量值。"""
        match = re.match(r"^\$\{(.+)\}$", value)
        if match:
            env_key = match.group(1)
            return os.environ.get(env_key, value)
        return value

    def get_platform_config(self, platform: str) -> dict:
        """获取指定平台的配置字典（深拷贝，不可变）。"""
        self._load()
        config: dict[str, any] = {}

        # 从 mediakit.toml 的 [platforms.xxx] 读取
        platform_cfg = self._toml.get("platforms", {}).get(platform, {})
        config.update(platform_cfg)

        # local.toml 覆盖
        local_platform = self._local_toml.get("platforms", {}).get(platform, {})
        config.update(local_platform)

        # 环境变量最高优先级（显式映射，避免字符串处理歧义）
        env_mapping: dict[str, dict[str, str]] = {
            "youtube": {"YOUTUBE_API_KEY": "api_key"},
            "twitter": {"TWITTERAPI_IO_KEY": "api_key", "TWITTER_BEARER_TOKEN": "bearer_token"},
        }
        for env_key, cfg_key in env_mapping.get(platform, {}).items():
            if env_key in self._env:
                config[cfg_key] = self._env[env_key]

        return deepcopy(config)

    def get_cache_config(self) -> dict:
        """获取缓存配置。"""
        self._load()
        return deepcopy(self._toml.get("cache", {}))


def get_config(project_root: Path | None = None) -> ConfigManager:
    """获取全局 ConfigManager 单例（首次调用自动加载 .env 到 os.environ）。"""
    key = str(project_root or "default")
    if key not in _CONFIG_CACHE:
        cfg = ConfigManager(project_root)
        cfg._load()  # 立即注入 .env，确保下游 os.environ.get() 能读到
        _CONFIG_CACHE[key] = cfg
    return _CONFIG_CACHE[key]
