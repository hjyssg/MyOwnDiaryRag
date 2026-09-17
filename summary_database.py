"""摘要 SQLite 存储（batch 写）与查询（Web 只读）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from summary_fingerprint import canonical_json, source_hash

SCHEMA_FILE = Path(__file__).parent / "create_diary_db.sql"   # 唯一 DDL 来源（日记表 + 摘要表）

# 早期版本建的摘要表缺少这些列：migrate() 按"列不存在才 ALTER"补齐，不动已有数据。
LEGACY_COLUMNS = {
    "entry_summaries": (
        ("emotion", "TEXT NOT NULL DEFAULT ''"),
        ("emotion_status", "TEXT"),
        ("emotion_cache_key", "TEXT"),
        ("emotion_algorithm_fingerprint", "TEXT"),
        ("emotion_error", "TEXT"),
    ),
    "summary_runs": (
        ("emotion_algorithm_fingerprint", "TEXT"),
    ),
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """表里是否已有该列（表不存在时返回 False）"""
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    """这是否是一张已存在的普通表"""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def tables_exist(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entry_summaries'"
    ).fetchone()
    return row is not None


class SummaryStore:
    """batch 唯一写入者；每篇 UPSERT 都是独立短事务。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self) -> None:
        """确保库结构就绪（不重建表、不动已有数据）

        * 先给"已存在但缺列"的老摘要表补列（索引可能依赖这些列）；
        * 再执行唯一 DDL 来源 ``create_diary_db.sql``（全是 IF NOT EXISTS）建缺的表与索引。
        """
        with self.connect() as connection:
            self._upgrade_legacy_columns(connection)
            connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))

    def _upgrade_legacy_columns(self, connection: sqlite3.Connection) -> None:
        """按 :data:`LEGACY_COLUMNS` 给老表补列；表不存在就跳过（交给建表 SQL）"""
        for table, columns in LEGACY_COLUMNS.items():
            if not table_exists(connection, table):
                continue
            for column, definition in columns:
                if not column_exists(connection, table, column):
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def register_algorithm(self, fingerprint: str, payload: dict) -> None:
        parameters = {k: v for k, v in payload.items() if k not in {"algorithm_version", "prompt_hash", "model"}}
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO summary_algorithms "
                "(fingerprint, algorithm_version, prompt_hash, model, parameters_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fingerprint, payload["algorithm_version"], payload["prompt_hash"], payload["model"],
                 canonical_json(parameters), now_iso()),
            )

    def get(self, key: str) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM entry_summaries WHERE entry_key = ?", (key,)).fetchone()
            return dict(row) if row else None

    def is_cache_hit(self, key: str, current_cache_key: str) -> bool:
        record = self.get(key)
        return bool(record and record["cache_key"] == current_cache_key and record["status"] in ("ok", "empty"))

    def upsert(self, entry: dict, *, entry_key: str, source_hash_value: str,
               algorithm_fingerprint: str, cache_key: str, status: str,
               summary: str = "", error: Optional[str] = None) -> None:
        stamp = now_iso()
        generated_at = stamp if status in ("ok", "empty") else None
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO entry_summaries
                (entry_key, entry_date, entry_type, year, month, day, word_count, source_hash,
                 algorithm_fingerprint, cache_key, status, summary, error, generated_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_key) DO UPDATE SET
                  entry_date=excluded.entry_date, entry_type=excluded.entry_type, year=excluded.year,
                  month=excluded.month, day=excluded.day, word_count=excluded.word_count,
                  source_hash=excluded.source_hash, algorithm_fingerprint=excluded.algorithm_fingerprint,
                  cache_key=excluded.cache_key, status=excluded.status, summary=excluded.summary,
                  error=excluded.error, generated_at=excluded.generated_at, updated_at=excluded.updated_at""",
                (entry_key, entry["date"], entry["entry_type"], entry["year"], entry["month"], entry["day"],
                 entry.get("word_count", 0), source_hash_value, algorithm_fingerprint, cache_key, status,
                 summary, error, generated_at, stamp),
            )

    # -- 情绪分类（与摘要共享同一行，但缓存/指纹彼此独立）--

    def emotion_record(self, key: str) -> Optional[dict]:
        """读取某篇的情绪缓存状态（行不存在时返回 None）"""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT emotion, emotion_status, emotion_cache_key, emotion_algorithm_fingerprint "
                "FROM entry_summaries WHERE entry_key = ?", (key,)
            ).fetchone()
            return dict(row) if row else None

    def emotion_cache_hit(self, key: str, current_cache_key: str) -> bool:
        """情绪是否可复用（与摘要同口径：ok/empty 且缓存键一致）"""
        record = self.emotion_record(key)
        return bool(
            record
            and record.get("emotion_cache_key") == current_cache_key
            and record.get("emotion_status") in ("ok", "empty")
        )

    def upsert_emotion(self, key: str, *, emotion: str, status: str, cache_key: str,
                       algorithm_fingerprint: str, error: Optional[str] = None) -> bool:
        """只更新某篇的情绪列（摘要列保持不动）；行不存在时返回 False 且不改库

        情绪与摘要解耦：补情绪 / 换情绪标签与 prompt 都不会让已产出的摘要失效。
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE entry_summaries SET emotion=?, emotion_status=?, emotion_cache_key=?, "
                "emotion_algorithm_fingerprint=?, emotion_error=?, updated_at=? WHERE entry_key=?",
                (emotion, status, cache_key, algorithm_fingerprint,
                 (error or "")[:500] or None, now_iso(), key),
            )
            return cursor.rowcount > 0

    def start_run(self, fingerprint: str, scope: dict, total: int,
                  *, emotion_fingerprint: Optional[str] = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO summary_runs(algorithm_fingerprint, emotion_algorithm_fingerprint, "
                "scope_json, status, total, started_at) VALUES (?, ?, ?, 'running', ?, ?)",
                (fingerprint, emotion_fingerprint, canonical_json(scope), total, now_iso())
            )
            return int(cursor.lastrowid)

    def update_run(self, run_id: int, *, status: Optional[str] = None, processed: int = 0,
                   generated: int = 0, reused: int = 0, failed: int = 0) -> None:
        finished = now_iso() if status in ("completed", "interrupted", "failed") else None
        with self.connect() as connection:
            connection.execute(
                "UPDATE summary_runs SET status=COALESCE(?, status), processed=?, generated=?, reused=?, "
                "failed=?, finished_at=COALESCE(?, finished_at) WHERE id=?",
                (status, processed, generated, reused, failed, finished, run_id),
            )

    def delete_orphans(self, valid_keys: Iterable[str], *, years=None, entry_types=None) -> int:
        keys = list(valid_keys)
        clauses, params = [], []
        if years:
            clauses.append(f"year IN ({','.join('?' for _ in years)})"); params.extend(years)
        if entry_types:
            clauses.append(f"entry_type IN ({','.join('?' for _ in entry_types)})"); params.extend(entry_types)
        if keys:
            clauses.append(f"entry_key NOT IN ({','.join('?' for _ in keys)})"); params.extend(keys)
        where = " AND ".join(clauses) or "0"
        with self.connect() as connection:
            cursor = connection.execute(f"DELETE FROM entry_summaries WHERE {where}", params)
            return cursor.rowcount

    def reset(self) -> None:
        self.migrate()
        with self.connect() as connection:
            connection.execute("DELETE FROM entry_summaries")
            connection.execute("DELETE FROM summary_runs")
            connection.execute("DELETE FROM summary_algorithms")


class SummaryRepository:
    """Web/导出使用的只读查询层；摘要表未创建时返回空。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def available(self) -> bool:
        try:
            with self.connect() as connection:
                return tables_exist(connection)
        except sqlite3.DatabaseError:
            return False

    def list(self, *, year=None, month=None, entry_type=None, query=None, emotion=None,
             status="ok", page=1, per_page=20):
        with self.connect() as connection:
            if not tables_exist(connection):
                return [], 0
            clauses, params = [], []
            for column, value in (("e.year", year), ("e.month", month), ("e.entry_type", entry_type),
                                  ("s.status", status), ("s.emotion", emotion)):
                if value is not None and value != "all": clauses.append(f"{column} = ?"); params.append(value)
            if query:
                clauses.append("s.summary LIKE ?"); params.append(f"%{query}%")
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            join = " FROM diary_entries e JOIN entry_summaries s ON s.entry_date=e.date AND s.entry_type=e.entry_type JOIN summary_algorithms a ON a.fingerprint=s.algorithm_fingerprint"
            total = connection.execute("SELECT COUNT(*)" + join + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT s.*, e.id entry_id, e.content, a.model" + join + where +
                " ORDER BY e.date DESC, e.id DESC LIMIT ? OFFSET ?", (*params, per_page, (page - 1) * per_page)
            ).fetchall()
            return [self._public(dict(row), connection) for row in rows], total

    def emotion_counts(self) -> dict:
        """各情绪标签的条数（只统计有效摘要；供 Web 下拉显示计数）

        迁移前的旧库（还没有 emotion 列）返回空字典，不影响原文阅读。
        """
        with self.connect() as connection:
            if not tables_exist(connection):
                return {}
            try:
                rows = connection.execute(
                    "SELECT emotion, COUNT(*) AS count FROM entry_summaries "
                    "WHERE status = 'ok' AND emotion != '' GROUP BY emotion"
                ).fetchall()
            except sqlite3.OperationalError:
                return {}
            return {row["emotion"]: int(row["count"]) for row in rows}

    def for_entry(self, entry_id: int) -> Optional[dict]:
        with self.connect() as connection:
            entry = connection.execute("SELECT * FROM diary_entries WHERE id=?", (entry_id,)).fetchone()
            if not entry:
                return None
            if not tables_exist(connection):
                return {"entry_key": None, "status": "missing", "summary": "", "model": None,
                        "generated_at": None, "emotion": "", "emotion_status": "missing"}
            row = connection.execute(
                "SELECT s.*, e.id entry_id, e.content, a.model FROM diary_entries e "
                "LEFT JOIN entry_summaries s ON s.entry_date=e.date AND s.entry_type=e.entry_type "
                "LEFT JOIN summary_algorithms a ON a.fingerprint=s.algorithm_fingerprint WHERE e.id=?", (entry_id,)
            ).fetchone()
            if not row or row["entry_key"] is None:
                return {"entry_key": None, "status": "missing", "summary": "", "model": None,
                        "generated_at": None, "emotion": "", "emotion_status": "missing"}
            return self._public(dict(row), connection)

    @staticmethod
    def _scope_matches(scope: dict, row: dict) -> bool:
        years = scope.get("years")
        entry_types = scope.get("entry_types")
        return (not years or row.get("year") in years) and (
            not entry_types or row.get("entry_type") in entry_types
        )

    def _algorithm_stale(self, connection: sqlite3.Connection, row: dict) -> bool:
        """摘要是否需要重算（本轮 scope 的摘要算法与记录不一致）

        ``--emotion-only`` 的运行**不产出摘要**，因此不能用来判断摘要是否过期
        （否则用户改过摘要 Prompt 后补一次情绪，就会把好摘要全标成 stale）。
        """
        runs = connection.execute(
            "SELECT algorithm_fingerprint, scope_json FROM summary_runs "
            "WHERE status IN ('running','completed') ORDER BY id DESC"
        ).fetchall()
        for run in runs:
            try:
                scope = json.loads(run["scope_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(scope, dict) and scope.get("emotion_only"):
                continue
            if self._scope_matches(scope, row):
                return run["algorithm_fingerprint"] != row.get("algorithm_fingerprint")
        return False

    def _emotion_stale(self, connection: sqlite3.Connection, row: dict) -> bool:
        """记录上的情绪算法指纹与最近一次覆盖该 scope 的运行不一致（情绪需要重算）"""
        if not row.get("emotion_algorithm_fingerprint"):
            return False
        runs = connection.execute(
            "SELECT emotion_algorithm_fingerprint, scope_json FROM summary_runs "
            "WHERE status IN ('running','completed') ORDER BY id DESC"
        ).fetchall()
        for run in runs:
            fingerprint = run["emotion_algorithm_fingerprint"]
            if not fingerprint:
                continue
            try:
                scope = json.loads(run["scope_json"])
            except (TypeError, ValueError):
                continue
            if self._scope_matches(scope, row):
                return fingerprint != row.get("emotion_algorithm_fingerprint")
        return False

    def _public(self, row: dict, connection: Optional[sqlite3.Connection] = None) -> dict:
        stale = row.get("content") is not None and source_hash(row["content"]) != row.get("source_hash")
        if connection is not None and not stale:
            stale = self._algorithm_stale(connection, row)
        status = "stale" if stale else row.get("status")
        emotion = row.get("emotion") or ""
        emotion_status = row.get("emotion_status") or "missing"
        if emotion_status != "missing":
            if stale or (connection is not None and self._emotion_stale(connection, row)):
                emotion_status = "stale"
        if emotion_status != "ok":
            emotion = ""
        return {k: row.get(k) for k in (
            "entry_key", "entry_id", "entry_date", "entry_type", "word_count", "summary", "model", "generated_at"
        )} | {
            "status": status,
            "summary": "" if stale or status == "failed" else row.get("summary", ""),
            "emotion": emotion,
            "emotion_status": emotion_status,
        }

    def all_records(self) -> list[dict]:
        items, _ = self.list(status="all", page=1, per_page=1_000_000)
        return sorted(items, key=lambda item: (item["entry_date"], item["entry_id"]))