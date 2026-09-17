#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试用的小工具：临时 SQLite 摘要库 + 算法指纹

``main.process_entries`` 现在必须走 SQLite（``store`` 是必填参数、断点续跑
与缓存判定都在库里），所以凡是端到端跑一遍流水线的测试都用这里造库。
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from summary_database import SummaryStore  # noqa: E402
from summary_fingerprint import algorithm_fingerprint, algorithm_payload  # noqa: E402

#: 与 config.get_settings() 同形状的最小参数集（只用于算算法指纹）
FINGERPRINT_SETTINGS = {
    "llm_temperature": 0.2,
    "llm_max_tokens": 4096,
    "llm_reasoning_effort": "",
    "llm_json_mode": False,
    "content_head_chars": 4000,
    "content_tail_chars": 1000,
    "max_summary_chars": 60,
}


def make_store(tmp, *, model: str = "fake", prompt: str = "p1"):
    """在 ``tmp`` 下建一个临时摘要库，返回 ``(SummaryStore, 算法指纹)``"""
    db = Path(tmp) / "test.db"
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute(
            "CREATE TABLE diary_entries (id INTEGER PRIMARY KEY,date TEXT,year INT,month INT,"
            "day INT,content TEXT,file_source TEXT,entry_type TEXT,word_count INT,"
            "UNIQUE(date,entry_type))"
        )
    store = SummaryStore(db)
    store.migrate()
    payload = algorithm_payload(FINGERPRINT_SETTINGS, model, prompt)
    fingerprint = algorithm_fingerprint(payload)
    store.register_algorithm(fingerprint, payload)
    return store, fingerprint
