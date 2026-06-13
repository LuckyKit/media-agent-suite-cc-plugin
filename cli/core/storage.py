"""
cli.core.storage — 统一持久化 + 缓存存储层

职责：
  - SQLite 持久化 + JSON 文件缓存，统一 save/load/query 接口
  - 支持四种模式：both（默认）/ cache / store / none
  - 持久化支持 SQL 查询，便于后续分析（按日期、来源、关键词过滤）
  - 缓存独立管理 TTL，过期自动清理

存储结构：
  .media-agent/shared/storage/{namespace}/
    ├── store.db              # SQLite 持久化（永久保存，支持 SQL 查询）
    └── cache/                # JSON 文件缓存（TTL 过期）
        └── {hash}_{version}.json

SQLite 表结构：
  CREATE TABLE records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      timestamp REAL NOT NULL,
      datetime TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT '',
      keyword TEXT,
      params_json TEXT NOT NULL,
      data_json TEXT NOT NULL
  );
  CREATE INDEX idx_datetime ON records(datetime);
  CREATE INDEX idx_source ON records(source);
  CREATE INDEX idx_keyword ON records(keyword);

使用示例：
  store = DataStore("twitter.discover", mode="both")

  store.save({"keyword": "deepseek"}, tweets, source="twitterapi_io")

  # 缓存读取
  result = store.load_cached({"keyword": "deepseek"}, ttl=300)

  # SQL 查询
  records = store.query(date="2026-06-06", source="twitterapi_io", limit=50)

  # 统计
  store.stats()
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

StorageMode = Literal["both", "store", "cache", "none"]
DEFAULT_STORAGE_DIR = Path(".media-agent/shared/storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    datetime TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    keyword TEXT,
    params_json TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tweet_id ON records(tweet_id);
CREATE INDEX IF NOT EXISTS idx_datetime ON records(datetime);
CREATE INDEX IF NOT EXISTS idx_source ON records(source);
CREATE INDEX IF NOT EXISTS idx_keyword ON records(keyword);
"""


class DataStore:
    """统一持久化（SQLite）+ 缓存（JSON 文件）存储管理器。"""

    def __init__(
        self,
        namespace: str,
        mode: StorageMode = "both",
        root_dir: Path | None = None,
    ):
        self.namespace = namespace
        self.mode = mode
        self.root = (root_dir or DEFAULT_STORAGE_DIR) / namespace
        self._write_count = 0
        self._db: sqlite3.Connection | None = None

    # -------------------------------------------------------------------------
    # 数据库连接
    # -------------------------------------------------------------------------

    @property
    def db(self) -> sqlite3.Connection:
        """获取 SQLite 连接（惰性初始化）。"""
        if self._db is None:
            self.root.mkdir(parents=True, exist_ok=True)
            db_path = self.root / "store.db"
            self._db = sqlite3.connect(str(db_path))
            self._db.row_factory = sqlite3.Row
            self._db.executescript(_SCHEMA)
            self._db.commit()
        return self._db

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._db:
            self._db.close()
            self._db = None

    # -------------------------------------------------------------------------
    # 写入
    # -------------------------------------------------------------------------

    def save(
        self,
        params: dict[str, Any],
        data: Any,
        *,
        source: str = "",
        ttl: int = 300,
    ) -> None:
        """写入存储。data._raw 中的每条 raw tweet 单独存一行。

        mode="both" → SQLite + 缓存
        mode="store" → 仅 SQLite
        mode="cache" → 仅缓存
        mode="none" → 不写
        """
        now = time.time()
        dt_str = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        keyword = params.get("keyword", "")

        if self.mode in ("both", "store"):
            # 提取 raw tweets，逐一入库
            raw_tweets = data.get("_raw", {}).get("tweets", [])
            rows = [
                (str(t.get("id_str", t.get("id", ""))), now, dt_str, source, keyword,
                 json.dumps(params, ensure_ascii=False), json.dumps(t, ensure_ascii=False))
                for t in raw_tweets
            ]
            if rows:
                self.db.executemany(
                    "INSERT OR IGNORE INTO records "
                    "(tweet_id, timestamp, datetime, source, keyword, params_json, raw_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                self.db.commit()

            # 保留最近 10000 条
            count = self.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            excess = count - 10000
            if excess > 0:
                self.db.execute(
                    "DELETE FROM records WHERE id IN "
                    "(SELECT id FROM records ORDER BY timestamp ASC LIMIT ?)",
                    (excess,),
                )
                self.db.commit()

        if self.mode in ("both", "cache"):
            self._write_cache(params, data, source, now, ttl)

    def _write_cache(self, params: dict, data: Any, source: str, now: float, ttl: int) -> None:
        """写 JSON 缓存文件。"""
        params_hash = self._hash_params(params)
        id_ver = "0.1.0"

        cache_dir = self.root / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_obj = {
            "_meta": {"created_at": now, "expire_at": now + ttl, "source": source},
            "data": data,
        }
        (cache_dir / f"{params_hash}_{id_ver}.json").write_text(
            json.dumps(cache_obj, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        self._write_count += 1
        if self._write_count % 5 == 0:
            self._cleanup_cache()

    # -------------------------------------------------------------------------
    # 缓存读取
    # -------------------------------------------------------------------------

    def load_cached(self, params: dict[str, Any], ttl: int = 300) -> dict | None:
        """读 JSON 缓存。过期或 miss 返回 None。"""
        if self.mode not in ("both", "cache"):
            return None

        params_hash = self._hash_params(params)
        id_ver = "0.1.0"
        cache_file = self.root / "cache" / f"{params_hash}_{id_ver}.json"

        if not cache_file.exists():
            return None

        try:
            obj = json.loads(cache_file.read_text(encoding="utf-8"))
            meta = obj.get("_meta", {})
            if meta.get("expire_at") and meta["expire_at"] < time.time():
                cache_file.unlink(missing_ok=True)
                return None
            return {"_meta": meta, "data": obj.get("data")}
        except (json.JSONDecodeError, OSError):
            cache_file.unlink(missing_ok=True)
            return None

    # -------------------------------------------------------------------------
    # 查询历史（SQLite）
    # -------------------------------------------------------------------------

    def query(
        self,
        date: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """SQL 查询持久化历史记录，返回完整原始 tweet。

        返回：[{tweet_id, timestamp, datetime, source, keyword, params, raw: {...}}, ...]
        """
        if self.mode not in ("both", "store"):
            return []

        conditions = []
        sql_params: list[Any] = []

        if date:
            conditions.append("date(datetime) = ?")
            sql_params.append(date)
        if source:
            conditions.append("source = ?")
            sql_params.append(source)
        if keyword:
            conditions.append("keyword LIKE ?")
            sql_params.append(f"%{keyword}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM records {where} ORDER BY timestamp DESC LIMIT ?"
        sql_params.append(limit)

        rows = self.db.execute(sql, sql_params).fetchall()
        return [
            {
                "tweet_id": r["tweet_id"],
                "timestamp": r["timestamp"],
                "datetime": r["datetime"],
                "source": r["source"],
                "keyword": r["keyword"],
                "params": json.loads(r["params_json"]),
                "raw": json.loads(r["raw_json"]),
            }
            for r in rows
        ]

    # -------------------------------------------------------------------------
    # 统计
    # -------------------------------------------------------------------------

    def stats(self) -> dict:
        """返回存储统计。"""
        result: dict[str, Any] = {"namespace": self.namespace, "mode": self.mode}

        if self.mode in ("both", "store"):
            row = self.db.execute(
                "SELECT COUNT(*) as total, COUNT(DISTINCT tweet_id) as tweets, "
                "COUNT(DISTINCT date(datetime)) as days, "
                "COUNT(DISTINCT source) as sources, COUNT(DISTINCT keyword) as keywords "
                "FROM records"
            ).fetchone()
            result["store"] = {
                "records": row["total"],
                "days": row["days"],
                "sources": row["sources"],
                "keywords": row["keywords"],
                "db_size_kb": (self.root / "store.db").stat().st_size // 1024
                if (self.root / "store.db").exists()
                else 0,
            }
        else:
            result["store"] = None

        cache_dir = self.root / "cache"
        cache_files = list(cache_dir.rglob("*.json")) if cache_dir.exists() else []
        result["cache"] = {
            "files": len(cache_files),
            "size_kb": sum(f.stat().st_size for f in cache_files) // 1024,
        }

        return result

    # -------------------------------------------------------------------------
    # 内部工具
    # -------------------------------------------------------------------------

    def _hash_params(self, params: dict) -> str:
        params_json = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(params_json.encode()).hexdigest()[:16]

    def _cleanup_cache(self) -> int:
        cache_dir = self.root / "cache"
        if not cache_dir.exists():
            return 0
        removed = 0
        now = time.time()
        for f in cache_dir.iterdir():
            if f.suffix != ".json":
                continue
            try:
                meta = json.loads(f.read_text(encoding="utf-8")).get("_meta", {})
                if meta.get("expire_at") and meta["expire_at"] < now:
                    f.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                f.unlink(missing_ok=True)
                removed += 1
        return removed
