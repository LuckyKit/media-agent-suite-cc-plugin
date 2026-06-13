"""
cli.core.runtime — 跨平台运行时抽象

职责：
  - 识别当前宿主环境（Claude Code / Codex / Cursor / OpenClaw / 其他）
  - 提供统一的项目根目录、.media-agent 目录、会话标识接口
  - 封装平台差异，避免扩散到 Skill / Agent / Platform 业务层
  - 按优先级加载环境变量（进程 > 项目级 .media-agent/.env > 用户级 ~/.media-agent/.env）

设计原则：
  - 业务代码禁止直接判断宿主平台，统一通过本模块获取能力与路径
  - 会话隔离透明化：调用方无需关心 session ID 如何生成
  - 路径发现可覆盖：通过环境变量 MKIT_PROJECT_ROOT / MKIT_MEDIA_KIT_DIR 可强制指定
  - 宿主检测可扩展：新平台（OpenClaw/Cursor 等）通过注册检测器接入，零侵入业务层

.media-agent 目录层级：
  用户级：~/.media-agent/（Windows: ~/.media-agent/）
  项目级：{project_root}/.media-agent/
  会话级：{project_root}/.media-agent/sessions/{session_id}/

宿主检测机制：
  1. 注册检测器（内置 + mediakit.toml 配置 + 代码动态注册）
  2. 按 priority 从高到低依次执行
  3. 第一个返回非 None host 的检测器获胜
  4. 全部失败则回退到 "unknown"
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Callable


# =============================================================================
# HostDetector — 可扩展的宿主检测器
# =============================================================================

HostDetectResult = tuple[str | None, int]  # (host_name, priority)
HostDetectorFunc = Callable[[], HostDetectResult]


class HostDetector:
    """
    可扩展宿主检测器。

    使用示例：
      # 内置检测器自动注册（Claude Code / Codex / CLI）
      detector = HostDetector()
      host = detector.detect()  # -> "claude_code" | "codex" | "cli" | ...

      # 第三方扩展（如 OpenClaw）
      def detect_openclaw():
          if os.environ.get("OPENCLAW_SESSION"):
              return "openclaw", 100
          return None, 0

      HostDetector.register(detect_openclaw)
    """

    _detectors: list[HostDetectorFunc] = []
    _builtins_registered: bool = False

    @classmethod
    def _register_builtin(cls) -> None:
        """注册内置检测器（只执行一次）。"""
        if cls._builtins_registered:
            return
        cls._builtins_registered = True

        # Claude Code（最高优先级）
        cls.register(
            lambda: (
                ("claude_code", 100)
                if os.environ.get("CLAUDE_CODE_WORKSPACE") or os.environ.get("CLAUDE_CODE")
                else (None, 0)
            )
        )

        # Codex
        cls.register(
            lambda: (
                ("codex", 100)
                if os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX")
                else (None, 0)
            )
        )

        # Cursor
        cls.register(
            lambda: (
                ("cursor", 100)
                if os.environ.get("CURSOR_AGENT_SESSION") or os.environ.get("CURSOR_AGENT")
                else (None, 0)
            )
        )

        # OpenClaw
        cls.register(lambda: ("openclaw", 100) if os.environ.get("OPENCLAW_SESSION") else (None, 0))

        # 其他 AI IDE（通用环境变量模式）
        cls.register(
            lambda: (
                (os.environ.get("AI_IDE_HOST", "unknown"), 50)
                if os.environ.get("AI_IDE_HOST")
                else (None, 0)
            )
        )

        # 无明确匹配时回退 "unknown"（不根据 isatty 猜测，避免误判）
        # 用户可通过 MKIT_HOST 环境变量强制指定任何宿主标识

    @classmethod
    def register(cls, detector: HostDetectorFunc) -> None:
        """注册自定义检测器。"""
        cls._detectors.append(detector)

    @classmethod
    def register_from_config(cls, configs: list[dict[str, Any]]) -> None:
        """
        从 mediakit.toml 配置注册检测器。

        配置格式：
          [{"env": "OPENCLAW_SESSION", "host": "openclaw", "priority": 100}, ...]
        """
        for cfg in configs:
            env_var = cfg.get("env")
            host_name = cfg.get("host")
            priority = cfg.get("priority", 50)

            if env_var and host_name:
                cls.register(
                    lambda e=env_var, h=host_name, p=priority: (
                        (h, p) if os.environ.get(e) else (None, 0)
                    )
                )

    @classmethod
    def detect(cls) -> str:
        """
        检测当前宿主环境。

        返回宿主标识符，如："claude_code", "codex", "cursor", "openclaw", "unknown"
        未识别时回退 "unknown"，业务层通过 capability 判断能力，不依赖 host 名称。
        """
        cls._register_builtin()

        results: list[tuple[str, int]] = []
        for detector in cls._detectors:
            try:
                host, priority = detector()
                if host is not None:
                    results.append((host, priority))
            except Exception:
                continue

        if not results:
            return "unknown"

        # 按优先级降序，取最高
        results.sort(key=lambda x: x[1], reverse=True)
        return results[0][0]


# =============================================================================
# RuntimeAdapter — 运行时适配器
# =============================================================================


class RuntimeAdapter:
    """跨平台运行时适配器。进程级单例。"""

    def __init__(self):
        self._host: str | None = None
        self._project_root: Path | None = None
        self._session_id: str | None = None

    # -------------------------------------------------------------------------
    # 宿主检测
    # -------------------------------------------------------------------------

    def detect_host(self) -> str:
        """检测当前宿主环境（带缓存）。"""
        if self._host is None:
            # 优先从环境变量读取（强制覆盖）
            self._host = os.environ.get("MKIT_HOST") or HostDetector.detect()
        return self._host

    # -------------------------------------------------------------------------
    # 路径发现
    # -------------------------------------------------------------------------

    def get_project_root(self) -> Path:
        """
        获取项目根目录。

        优先级：
          1. 环境变量 MKIT_PROJECT_ROOT
          2. Git 仓库根目录（如有 .git）
          3. 当前工作目录（cwd）
        """
        if self._project_root is not None:
            return self._project_root

        # 1. 环境变量强制指定
        if env_root := os.environ.get("MKIT_PROJECT_ROOT"):
            self._project_root = Path(env_root).resolve()
            return self._project_root

        # 2. Git 仓库根
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            if (parent / ".git").exists():
                self._project_root = parent
                return self._project_root

        # 3. 回退 cwd
        self._project_root = cwd
        return self._project_root

    def get_media_kit_dir(self, level: str = "project") -> Path:
        """
        获取 .media-agent 目录路径。

        参数：
          level: "user" → ~/.media-agent/
                 "project" → {project}/.media-agent/
        """
        if level == "user":
            return Path.home() / ".media-agent"

        # project 级
        return self.get_project_root() / ".media-agent"

    # -------------------------------------------------------------------------
    # 会话管理
    # -------------------------------------------------------------------------

    def _generate_session_id(self) -> str:
        """
        生成会话标识。

        策略：
          1. 读取宿主环境变量（CLAUDE_CODE_SESSION_ID / CODEX_SESSION_ID / ...）
          2. 回退：{host}-{pid}-{cwd_short_hash}
        """
        host = self.detect_host()

        # 尝试读取宿主提供的 session ID
        env_map = {
            "claude_code": "CLAUDE_CODE_SESSION_ID",
            "codex": "CODEX_SESSION_ID",
            "cursor": "CURSOR_AGENT_SESSION",
            "openclaw": "OPENCLAW_SESSION",
        }
        env_key = env_map.get(host, "MKIT_SESSION_ID")
        if session_env := os.environ.get(env_key):
            return f"{host}-{session_env}"

        # 回退生成
        pid = os.getpid()
        cwd_hash = hashlib.sha256(str(self.get_project_root()).encode()).hexdigest()[:8]
        return f"{host}-{pid}-{cwd_hash}"

    def get_session_id(self) -> str:
        """获取当前会话标识（带缓存）。"""
        if self._session_id is None:
            self._session_id = self._generate_session_id()
        return self._session_id

    def get_host_dir(self) -> Path:
        """
        获取当前宿主的数据目录。

        路径：{project}/.media-agent/{host}/
        参考 orca 设计：每个宿主有自己独立的目录树。
        """
        return self.get_media_kit_dir("project") / self.detect_host()

    def get_session_dir(self) -> Path:
        """
        获取当前会话的隔离目录。

        路径：{project}/.media-agent/{host}/sessions/{session_local_id}/
        参考 orca：按宿主分顶层目录，sessions 在宿主内部。

        示例：
          Claude Code → .media-agent/claude_code/sessions/abc123/
          Codex       → .media-agent/codex/sessions/xyz789/
          其他        → .media-agent/unknown/sessions/pid-hash/
        """
        host = self.detect_host()
        # session_id 去掉 host 前缀，得到本地 ID
        raw_id = self.get_session_id()
        if raw_id.startswith(f"{host}-"):
            local_id = raw_id[len(host) + 1 :]
        else:
            local_id = raw_id
        return self.get_host_dir() / "sessions" / local_id

    def get_shared_dir(self) -> Path:
        """
        获取跨宿主共享数据目录。

        路径：{project}/.media-agent/shared/
        参考 orca 设计：宿主专属目录与共享目录分离。
        shared/ 下存放所有宿主共同读写的数据。
        """
        shared = self.get_media_kit_dir("project") / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        return shared

    def get_shared_drafts_dir(self) -> Path:
        """
        获取跨宿主共享的草稿目录。

        路径：{project}/.media-agent/shared/drafts/
        所有宿主（Claude Code / Codex / 其他）创建的草稿都放这里，按 draft-{host}-{n}.json 命名。
        各宿主的 state.json 只记录引用了哪些 draft_id，不持有草稿实体。
        """
        drafts_dir = self.get_shared_dir() / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        return drafts_dir

    def get_shared_history_path(self) -> Path:
        """获取跨宿主共享的历史记录文件路径。"""
        return self.get_shared_dir() / "history.jsonl"

    def get_shared_cache_dir(self) -> Path:
        """获取跨宿主共享的缓存目录。"""
        cache_dir = self.get_shared_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def ensure_session_dir(self) -> Path:
        """确保会话目录存在，并写入 session.json 元数据。"""
        session_dir = self.get_session_dir()
        session_dir.mkdir(parents=True, exist_ok=True)

        # 初始化本会话子目录（不含 drafts，草稿提升到项目级共享池）
        (session_dir / "temp").mkdir(exist_ok=True)
        (session_dir / "cache").mkdir(exist_ok=True)

        # 确保共享目录存在
        self.get_shared_drafts_dir()
        self.get_shared_cache_dir()

        # 写入 session.json
        session_meta = {
            "session_id": self.get_session_id(),
            "host": self.detect_host(),
            "host_version": os.environ.get("MKIT_HOST_VERSION", "unknown"),
            "project_root": str(self.get_project_root()),
            "pid": os.getpid(),
            "started_at": self._now_iso(),
            "last_active_at": self._now_iso(),
        }
        import json

        (session_dir / "session.json").write_text(
            json.dumps(session_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return session_dir

    def _now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------------------------------
    # 能力查询
    # -------------------------------------------------------------------------

    def get_capabilities(self) -> list[str]:
        """
        获取当前宿主支持的能力列表。

        各宿主能力：
          claude_code: ["skills", "agents", "hooks", "mcp", "subagent"]
          codex:       ["commands", "hooks", "mcp"]
          cursor:      ["commands", "hooks"]
          openclaw:    ["skills", "agents", "hooks"]
          unknown:     ["cli"]   # 未识别宿主只保留基础 CLI 能力
        """
        host = self.detect_host()
        capability_map = {
            "claude_code": ["skills", "agents", "hooks", "mcp", "subagent"],
            "codex": ["commands", "hooks", "mcp"],
            "cursor": ["commands", "hooks"],
            "openclaw": ["skills", "agents", "hooks"],
            "unknown": ["cli"],
        }
        return capability_map.get(host, ["cli"])

    def is_capability_available(self, capability: str) -> bool:
        """检查当前宿主是否支持指定能力。"""
        return capability in self.get_capabilities()


# =============================================================================
# 进程级单例
# =============================================================================

_runtime: RuntimeAdapter | None = None


def get_runtime() -> RuntimeAdapter:
    """获取全局 RuntimeAdapter 单例。"""
    global _runtime
    if _runtime is None:
        _runtime = RuntimeAdapter()
    return _runtime
