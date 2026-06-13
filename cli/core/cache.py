"""
cli.core.cache — 统一缓存管理

职责：
  - 提供稳定的 cache key 生成（namespace + 排序参数 + 版本 + 会话边界）
  - 支持按 TTL、配置变更、版本变更、会话结束等条件失效
  - 封装文件系统缓存存储，对业务层透明
  - 管理共享缓存生命周期（清理过期、LRU 淘汰、容量控制）

设计原则：
  - key 生成必须稳定：同一输入必须产生同一 key（跨进程、跨会话）
  - 失效必须可靠：配置/版本/会话变化时，旧缓存不能误命中
  - 缓存目录隔离：按 namespace 分目录，避免不同模块缓存冲突
  - 不缓存敏感数据：API Key、Token 等绝不写入缓存文件
  - 并发安全：写时原子 rename，读时容忍 miss

Cache Key 格式：
  {namespace}:{content_hash}:{capability_version}:{session_boundary}

  - namespace:       业务命名空间（如 "youtube.discover", "twitter.analyze"）
  - content_hash:    输入参数的确定性哈希（SHA256 前 16 位）
  - capability_version: 当前 capability/skill 版本号（来自 mediakit.toml）
  - session_boundary: 会话隔离标识（空字符串表示跨会话共享）

缓存目录（共享池）：
  项目级：{project}/.media-agent/shared/cache/{namespace}/
  文件名：{content_hash}_{capability_version}_{session_boundary}.json

缓存文件格式：
  {
    "_meta": {
      "created_at": 1717600000,
      "expire_at": 1717603600,        // TTL 到期时间戳，null 表示永不过期
      "capability_version": "0.1.0",  // 写入时的版本号
      "config_mtime": 1717600000,     // 写入时的 mediakit.toml mtime
      "size_bytes": 1024
    },
    "data": { ... }                    // 实际缓存数据
  }

失效策略（按优先级检查）：
  1. TTL 过期：expire_at < now
  2. 配置变更：mediakit.toml 或 .env 的 mtime > 缓存写入时的 config_mtime
  3. 版本变更：缓存中的 capability_version != 当前版本
  4. 会话结束：session_boundary 非空且与会话不匹配（仅本会话隔离缓存）
  5. 手动失效：通过 invalidate(pattern) 按 namespace 或 key 模式清除
  6. 容量失效：超出 max_entries 时 LRU 淘汰

清理机制：
  - 被动清理：get() 时检查过期，过期则删除（无额外开销）
  - 主动清理：mekit cache gc 命令扫描全部缓存，批量删除过期项
  - 启动清理：每次启动时异步清理 10% 最老的缓存（渐进式，避免卡顿）
  - 守护清理：后台线程定期扫描（可选，高频使用场景）

并发安全：
  - 写：先写 {key}.tmp，再原子 rename 为 {key}.json
  - 读：直接读，如果读到半写文件（JSON 解析失败）则视为 miss
  - 删：直接删除，miss 时自动重建
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal


class CacheManager:
    """统一缓存管理器。"""

    def __init__(
        self,
        cache_dir: Path,
        capability_version: str = "0.1.0",
        default_ttl: int | None = 3600,
        max_entries: int = 10000,
        max_file_size_mb: int = 10,
    ):
        """
        参数：
          cache_dir:          缓存根目录（通常为 {project}/.media-agent/shared/cache/）
          capability_version: 当前 capability 版本号，用于版本变更失效
          default_ttl:        默认 TTL（秒），None 表示永不过期（但仍受配置/版本变更失效）
          max_entries:        最大缓存条目数，超出时 LRU 淘汰
          max_file_size_mb:   最大单个缓存文件大小（MB）
        """
        self.cache_dir = cache_dir
        self.capability_version = capability_version
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    # -------------------------------------------------------------------------
    # Key 生成
    # -------------------------------------------------------------------------

    def make_key(
        self,
        namespace: str,
        params: dict[str, Any],
        session_boundary: str = "",
    ) -> str:
        """
        生成稳定的缓存 key。

        参数：
          namespace:        业务命名空间，如 "youtube.discover.trending"
          params:           输入参数字典（会被排序后序列化，确保稳定性）
          session_boundary: 会话隔离标识（空字符串表示跨会话共享）

        返回：
          完整 key 字符串
        """
        # 排序 params，JSON 序列化，确保跨进程/跨会话稳定性
        params_json = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        content_hash = hashlib.sha256(params_json.encode()).hexdigest()[:16]

        parts = [namespace, content_hash]
        if self.capability_version:
            parts.append(self.capability_version)
        if session_boundary:
            parts.append(session_boundary)

        return ":".join(parts)

    def _cache_file_path(self, namespace: str, key: str) -> Path:
        """根据 namespace 和 key 生成缓存文件路径。"""
        # key 中的 namespace 部分用于目录分层
        key_part = key.replace(":", "_")
        return self.cache_dir / namespace / f"{key_part}.json"

    # -------------------------------------------------------------------------
    # 读写操作
    # -------------------------------------------------------------------------

    def get(
        self,
        namespace: str,
        params: dict[str, Any],
        session_boundary: str = "",
        ttl: int | None = None,
    ) -> Any | None:
        """
        读取缓存。缓存不存在或已失效时返回 None。

        失效检查顺序（任一满足即失效）：
          1. 文件不存在
          2. TTL 过期（expire_at < now）
          3. 配置变更（mediakit.toml / .env mtime > 缓存 config_mtime）
          4. 版本变更（缓存 capability_version != 当前版本）
          5. 半写文件（JSON 解析失败）
        """
        key = self.make_key(namespace, params, session_boundary)
        cache_file = self._cache_file_path(namespace, key)

        if not cache_file.exists():
            return None

        try:
            content = cache_file.read_text(encoding="utf-8")
            cache_obj = json.loads(content)
            meta = cache_obj.get("_meta", {})
            data = cache_obj.get("data")

            # TTL 检查
            if meta.get("expire_at") is not None and meta["expire_at"] < time.time():
                cache_file.unlink(missing_ok=True)
                return None

            # 配置变更检查
            config_mtime = self._get_config_mtime()
            if config_mtime and meta.get("config_mtime") and config_mtime > meta["config_mtime"]:
                cache_file.unlink(missing_ok=True)
                return None

            # 版本变更检查
            if meta.get("capability_version") != self.capability_version:
                cache_file.unlink(missing_ok=True)
                return None

            return data

        except (json.JSONDecodeError, KeyError, OSError):
            # 半写文件或损坏，删除后返回 miss
            cache_file.unlink(missing_ok=True)
            return None

    def set(
        self,
        namespace: str,
        params: dict[str, Any],
        value: Any,
        ttl: int | None = None,
        session_boundary: str = "",
    ) -> None:
        """
        写入缓存。

        参数：
          ttl: 存活秒数，None 表示永不过期（但仍受配置/版本变更失效影响）

        并发安全：先写 .tmp，再原子 rename。
        """
        key = self.make_key(namespace, params, session_boundary)
        cache_file = self._cache_file_path(namespace, key)

        # 检查容量，必要时 LRU 淘汰
        self._maybe_evict_lru()

        # 构建缓存对象
        now = time.time()
        ttl_to_use = ttl if ttl is not None else self.default_ttl
        cache_obj = {
            "_meta": {
                "created_at": now,
                "expire_at": now + ttl_to_use if ttl_to_use is not None else None,
                "capability_version": self.capability_version,
                "config_mtime": self._get_config_mtime() or now,
                "size_bytes": 0,  # 写入后更新
            },
            "data": value,
        }

        content = json.dumps(cache_obj, ensure_ascii=False, indent=None, separators=(",", ":"))
        cache_obj["_meta"]["size_bytes"] = len(content.encode("utf-8"))

        # 检查单个文件大小
        if cache_obj["_meta"]["size_bytes"] > self.max_file_size_bytes:
            # 超大值不缓存
            return

        # 原子写入
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_text(content, encoding="utf-8")
        tmp_file.replace(cache_file)

        # 每 5 次写入触发一次过期清理（避免每次都扫磁盘）
        self._write_count = getattr(self, "_write_count", 0) + 1
        if self._write_count % 5 == 0:
            self._cleanup_expired()

    # -------------------------------------------------------------------------
    # 失效与清理
    # -------------------------------------------------------------------------

    def _cleanup_expired(self) -> int:
        """清理所有过期缓存文件（TTL 过期）。返回删除数量。"""
        removed = 0
        now = time.time()
        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                content = cache_file.read_text(encoding="utf-8")
                meta = json.loads(content).get("_meta", {})
                if meta.get("expire_at") and meta["expire_at"] < now:
                    cache_file.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                cache_file.unlink(missing_ok=True)
                removed += 1
        return removed

    def invalidate(self, pattern: str) -> int:
        """
        按模式清除缓存。

        参数：
          pattern: 支持通配符，如 "youtube.*" 或 "*.discover.*"

        返回：清除的缓存文件数量
        """
        import fnmatch

        removed = 0
        for cache_file in self.cache_dir.rglob("*.json"):
            # 从文件路径推导 namespace
            rel = cache_file.relative_to(self.cache_dir)
            namespace = rel.parent.as_posix() if str(rel.parent) != "." else ""
            key = rel.stem.replace("_", ":")
            full_key = f"{namespace}:{key}"

            if fnmatch.fnmatch(full_key, pattern) or fnmatch.fnmatch(namespace, pattern):
                cache_file.unlink(missing_ok=True)
                removed += 1

        return removed

    def invalidate_on(
        self,
        trigger: Literal["config_change", "version_change", "session_end", "all"],
        session_boundary: str = "",
    ) -> int:
        """
        按触发器批量失效缓存。

        参数：
          trigger: 失效原因
          session_boundary: session_end 时使用，清除本会话隔离缓存
        """
        if trigger == "config_change":
            # 清除所有缓存（因为无法精确判断哪些受配置影响）
            return self.invalidate("*")

        if trigger == "version_change":
            # 遍历所有缓存，检查 capability_version 不匹配
            return self._evict_by_version()

        if trigger == "session_end" and session_boundary:
            # 清除带本会话 boundary 的缓存
            return self.invalidate(f"*:{session_boundary}")

        if trigger == "all":
            return self.invalidate("*")

        return 0

    def gc(self, dry_run: bool = False) -> dict[str, int]:
        """
        垃圾回收：扫描并清理所有过期缓存。

        参数：
          dry_run: True 只统计不删除

        返回：{"scanned": N, "removed": N, "freed_bytes": N}
        """
        scanned = 0
        removed = 0
        freed_bytes = 0

        for cache_file in self.cache_dir.rglob("*.json"):
            scanned += 1
            try:
                content = cache_file.read_text(encoding="utf-8")
                cache_obj = json.loads(content)
                meta = cache_obj.get("_meta", {})

                expired = (
                    meta.get("expire_at") is not None and meta["expire_at"] < time.time()
                ) or (meta.get("capability_version") != self.capability_version)

                if expired:
                    freed_bytes += meta.get("size_bytes", cache_file.stat().st_size)
                    if not dry_run:
                        cache_file.unlink(missing_ok=True)
                    removed += 1

            except (json.JSONDecodeError, OSError):
                if not dry_run:
                    cache_file.unlink(missing_ok=True)
                removed += 1

        return {"scanned": scanned, "removed": removed, "freed_bytes": freed_bytes}

    # -------------------------------------------------------------------------
    # 内部工具
    # -------------------------------------------------------------------------

    def _get_config_mtime(self) -> float | None:
        """获取 mediakit.toml 或 .env 的最新修改时间。"""
        mtimes = []
        for filename in ["mediakit.toml", "mediakit.local.toml", ".env"]:
            path = Path.cwd() / filename
            if path.exists():
                mtimes.append(path.stat().st_mtime)
        return max(mtimes) if mtimes else None

    def _maybe_evict_lru(self) -> None:
        """检查缓存容量，超出时 LRU 淘汰最老的条目。"""
        all_files = sorted(
            self.cache_dir.rglob("*.json"),
            key=lambda p: p.stat().st_mtime,
        )

        if len(all_files) >= self.max_entries:
            # 淘汰 10% 最老的缓存
            to_evict = max(1, len(all_files) // 10)
            for old_file in all_files[:to_evict]:
                old_file.unlink(missing_ok=True)

    def _evict_by_version(self) -> int:
        """按版本号不匹配淘汰缓存。"""
        removed = 0
        for cache_file in self.cache_dir.rglob("*.json"):
            try:
                content = cache_file.read_text(encoding="utf-8")
                cache_obj = json.loads(content)
                meta = cache_obj.get("_meta", {})
                if meta.get("capability_version") != self.capability_version:
                    cache_file.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                cache_file.unlink(missing_ok=True)
                removed += 1
        return removed

    def stats(self) -> dict[str, Any]:
        """返回缓存统计：总条目数、总大小、各 namespace 分布。"""
        total_files = 0
        total_bytes = 0
        namespace_counts: dict[str, int] = {}

        for cache_file in self.cache_dir.rglob("*.json"):
            total_files += 1
            try:
                size = cache_file.stat().st_size
                total_bytes += size
                rel = cache_file.relative_to(self.cache_dir)
                ns = rel.parent.as_posix() if str(rel.parent) != "." else "default"
                namespace_counts[ns] = namespace_counts.get(ns, 0) + 1
            except OSError:
                pass

        return {
            "total_entries": total_files,
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "max_entries": self.max_entries,
            "namespace_distribution": namespace_counts,
        }
