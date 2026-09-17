"""摘要 SQLite 存储（batch 写）与查询（Web 只读）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from summary_fingerprint import canonical_json, source_hash

MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "summaries"
LATEST_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS summary_schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in connection.execute("SELECT version FROM summary_schema_migrations")}
            unknown = [version for version in applied if version > LATEST_SCHEMA_VERSION]
            if unknown:
                raise RuntimeError(f"摘要数据库版本不受支持：{max(unknown)}")
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in applied:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO summary_schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, now_iso()),
                )

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

    def start_run(self, fingerprint: str, scope: dict, total: int) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO summary_runs(algorithm_fingerprint, scope_json, status, total, started_at) "
                "VALUES (?, ?, 'running', ?, ?)", (fingerprint, canonical_json(scope), total, now_iso())
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

    def list(self, *, year=None, month=None, entry_type=None, query=None, status="ok", page=1, per_page=20):
        with self.connect() as connection:
            if not tables_exist(connection):
                return [], 0
            clauses, params = [], []
            for column, value in (("e.year", year), ("e.month", month), ("e.entry_type", entry_type), ("s.status", status)):
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

    def for_entry(self, entry_id: int) -> Optional[dict]:
        with self.connect() as connection:
            entry = connection.execute("SELECT * FROM diary_entries WHERE id=?", (entry_id,)).fetchone()
            if not entry:
                return None
            if not tables_exist(connection):
                return {"entry_key": None, "status": "missing", "summary": "", "model": None, "generated_at": None}
            row = connection.execute(
                "SELECT s.*, e.id entry_id, e.content, a.model FROM diary_entries e "
                "LEFT JOIN entry_summaries s ON s.entry_date=e.date AND s.entry_type=e.entry_type "
                "LEFT JOIN summary_algorithms a ON a.fingerprint=s.algorithm_fingerprint WHERE e.id=?", (entry_id,)
            ).fetchone()
            if not row or row["entry_key"] is None:
                return {"entry_key": None, "status": "missing", "summary": "", "model": None, "generated_at": None}
            return self._public(dict(row), connection)

    @staticmethod
    def _scope_matches(scope: dict, row: dict) -> bool:
        years = scope.get("years")
        entry_types = scope.get("entry_types")
        return (not years or row.get("year") in years) and (
            not entry_types or row.get("entry_type") in entry_types
        )

    def _algorithm_stale(self, connection: sqlite3.Connection, row: dict) -> bool:
        runs = connection.execute(
            "SELECT algorithm_fingerprint, scope_json FROM summary_runs "
            "WHERE status IN ('running','completed') ORDER BY id DESC"
        ).fetchall()
        for run in runs:
            try:
                scope = json.loads(run["scope_json"])
            except (TypeError, ValueError):
                continue
            if self._scope_matches(scope, row):
                return run["algorithm_fingerprint"] != row.get("algorithm_fingerprint")
        return False

    def _public(self, row: dict, connection: Optional[sqlite3.Connection] = None) -> dict:
        stale = row.get("content") is not None and source_hash(row["content"]) != row.get("source_hash")
        if connection is not None and not stale:
            stale = self._algorithm_stale(connection, row)
        status = "stale" if stale else row.get("status")
        return {k: row.get(k) for k in (
            "entry_key", "entry_id", "entry_date", "entry_type", "word_count", "summary", "model", "generated_at"
        )} | {"status": status, "summary": "" if stale or status == "failed" else row.get("summary", "")}

    def all_records(self) -> list[dict]:
        items, _ = self.list(status="all", page=1, per_page=1_000_000)
        return sorted(items, key=lambda item: (item["entry_date"], item["entry_id"]))