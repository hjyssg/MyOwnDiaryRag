#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性数据迁移：把日记类型 single_day / multi_day 合并成普通日记 diary

背景：导入器不再区分「单日文件 / 多日合一」，普通日记一律以 entry_type='diary'
一天一条写进 diary_entries。本脚本处理旧库里的历史数据：

1. 重建 diary_entries：旧表的 CHECK 约束只认 single_day / multi_day，而 SQLite 改不了
   CHECK，所以直接 DROP 后按 create_diary_db.sql 重建（表会被清空，正文需重新导入）；
   顺带清掉 diary_fts 里的旧索引行，以及老库里遗留的 summary 列。
2. entry_summaries：把 single_day / multi_day 的 entry_type 改成 diary，并同步重算
   entry_key / cache_key / emotion_cache_key —— 否则已经跑好的摘要与情绪会被判定为
   「过期」而重新调用模型（全量重跑要几小时）。

可重复执行（幂等）。用法：

    python scripts/merge_daily_entry_types.py
    python scripts/import_diary_to_db.py      # 重建后的空表需要重新导入正文
"""

import io
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Windows 控制台编码修复（与项目其它脚本一致）
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from summary_fingerprint import (  # noqa: E402
    DEFAULT_CACHE_NAMESPACE,
    EMOTION_CACHE_NAMESPACE,
    cache_key as make_cache_key,
    entry_key as make_entry_key,
)

SCHEMA_FILE = ROOT_DIR / "create_diary_db.sql"
LEGACY_TYPES = ("single_day", "multi_day")
NEW_TYPE = "diary"


def table_exists(connection, name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def rebuild_diary_entries(connection):
    """按最新 DDL 重建 diary_entries（旧 CHECK 约束不认 diary）"""
    if table_exists(connection, "diary_entries"):
        connection.execute("DROP TABLE diary_entries")
    if table_exists(connection, "diary_fts"):
        connection.execute("DELETE FROM diary_fts")
    connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    print("[1/2] diary_entries 已按 create_diary_db.sql 重建（正文等待重新导入）")


def migrate_summaries(connection):
    """entry_type 改名 + 重算 entry_key / 缓存键，保住已生成的摘要与情绪"""
    if not table_exists(connection, "entry_summaries"):
        print("[2/2] 没有 entry_summaries 表，跳过")
        return 0

    placeholders = ", ".join("?" for _ in LEGACY_TYPES)
    rows = connection.execute(
        "SELECT entry_key, entry_date, source_hash, algorithm_fingerprint, "
        "emotion_algorithm_fingerprint, emotion_cache_key "
        f"FROM entry_summaries WHERE entry_type IN ({placeholders})",
        LEGACY_TYPES,
    ).fetchall()
    if not rows:
        print("[2/2] entry_summaries 里没有 single_day / multi_day，跳过")
        return 0

    # 迁移后 entry_key 是 v1:{entry_date}:diary，同一天的两条会撞车，先检查
    collisions = connection.execute(
        f"SELECT entry_date FROM entry_summaries WHERE entry_type IN ({placeholders}) "
        "GROUP BY entry_date HAVING COUNT(*) > 1",
        LEGACY_TYPES,
    ).fetchall()
    already = connection.execute(
        "SELECT s.entry_date FROM entry_summaries s JOIN entry_summaries d "
        "ON d.entry_date = s.entry_date AND d.entry_type = ? "
        f"WHERE s.entry_type IN ({placeholders})",
        (NEW_TYPE, *LEGACY_TYPES),
    ).fetchall()
    if collisions or already:
        bad = sorted({row[0] for row in list(collisions) + list(already)})
        raise SystemExit(f"[错误] 以下日期已有相同分类的条目，请先手工处理：{bad}")

    for old_key, entry_date, source_digest, algorithm_fp, emotion_fp, emotion_cache in rows:
        new_key = make_entry_key({"entry_date": entry_date, "entry_type": NEW_TYPE})
        new_cache = make_cache_key(new_key, source_digest, algorithm_fp, DEFAULT_CACHE_NAMESPACE)
        new_emotion_cache = emotion_cache
        if emotion_fp:
            new_emotion_cache = make_cache_key(
                new_key, source_digest, emotion_fp, EMOTION_CACHE_NAMESPACE
            )
        connection.execute(
            "UPDATE entry_summaries SET entry_key = ?, entry_type = ?, cache_key = ?, "
            "emotion_cache_key = ? WHERE entry_key = ?",
            (new_key, NEW_TYPE, new_cache, new_emotion_cache, old_key),
        )

    print(f"[2/2] entry_summaries 已迁移 {len(rows)} 条（entry_key / cache_key / 情绪缓存键同步重算）")
    return len(rows)


def main():
    from config import get_config

    db_path = get_config()["database_path"]
    print(f"数据库：{db_path}")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        rebuild_diary_entries(connection)
        migrate_summaries(connection)
        connection.commit()
    finally:
        connection.close()
    print("完成。请运行： python scripts/import_diary_to_db.py")


if __name__ == "__main__":
    main()
