#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI 契约测试。

运行：python -m unittest tests.test_web_api -v
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# webapp-backend 目录名带连字符、不能作为包名导入，这里把项目根目录与后端目录加入 sys.path，
# 使 `from app import app` / `from dependencies import get_database` 可用。
ROOT_DIR = Path(__file__).resolve().parents[1]
WEBAPP_BACKEND_DIR = ROOT_DIR / "webapp-backend"
for _path in (ROOT_DIR, WEBAPP_BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from batch_summary import config as bs_config  # noqa: E402
from database import Database  # noqa: E402
from dependencies import get_database  # noqa: E402
from summary_database import SummaryStore  # noqa: E402
from summary_fingerprint import (  # noqa: E402
    algorithm_fingerprint,
    algorithm_payload,
    cache_key,
    emotion_payload,
    entry_key,
    source_hash,
)


SCHEMA_SQL = """
CREATE TABLE diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    content TEXT NOT NULL,
    file_source TEXT,
    entry_type TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(date, entry_type)
);
"""

ENTRIES = [
    ("2023-09-17", 2023, 9, 17, "旧年旅行记录", "2023.txt", "diary", 6),
    ("2024-08-01", 2024, 8, 1, "普通八月日记", "2024-08.txt", "note", 6),
    ("2024-09-17", 2024, 9, 17, "旅行与朋友聚会", "2024-09.txt", "diary", 8),
    ("2024-09-18", 2024, 9, 18, "工作记录", "2024-09.txt", "diary", 4),
]


def create_database(path: Path, entries=ENTRIES) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA_SQL)
        connection.executemany(
            """
            INSERT INTO diary_entries (
                date, year, month, day, content, file_source, entry_type, word_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            entries,
        )
        connection.commit()
    finally:
        connection.close()


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "diary.db"
        create_database(self.db_path)
        self.database = Database(self.db_path)
        app.dependency_overrides[get_database] = lambda: self.database
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp_dir.cleanup()

    def test_entries_returns_stable_pagination_contract(self):
        response = self.client.get("/api/entries", params={"page": 1, "per_page": 2})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            {key: body[key] for key in ("total", "page", "per_page", "pages")},
            {"total": 4, "page": 1, "per_page": 2, "pages": 2},
        )
        self.assertEqual([item["date"] for item in body["items"]], ["2024-09-18", "2024-09-17"])
        self.assertEqual(body["items"][0]["preview"], "工作记录")
        self.assertNotIn("content", body["items"][0])

    def test_entries_combines_filters_and_keyword(self):
        response = self.client.get(
            "/api/entries",
            params={
                "year": 2024,
                "month": 9,
                "entry_type": "diary",
                "q": "  旅行  ",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["query"], "旅行")
        self.assertEqual(body["items"][0]["date"], "2024-09-17")

    def test_full_entries_returns_all_matching_content_without_pagination(self):
        response = self.client.get("/api/entries/full", params={"year": 2024, "month": 9})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([item["date"] for item in body["items"]], ["2024-09-18", "2024-09-17"])
        self.assertEqual(body["items"][0]["content"], "工作记录")
        self.assertNotIn("page", body)

    def test_entries_empty_and_out_of_range_page_keep_pagination_shape(self):
        response = self.client.get("/api/entries", params={"q": "不存在", "page": 3})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "total": 0,
                "page": 3,
                "per_page": 20,
                "pages": 1,
                "items": [],
                "year": None,
                "month": None,
                "entry_type": None,
                "query": "不存在",
            },
        )

    def test_legacy_search_uses_same_service_contract(self):
        response = self.client.get("/api/search", params={"q": "旅行", "limit": 1})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["per_page"], 1)
        self.assertEqual(body["pages"], 2)
        self.assertEqual(len(body["items"]), 1)

    def test_entry_detail_and_not_found(self):
        found = self.client.get("/api/entries/3")
        missing = self.client.get("/api/entries/999")

        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["content"], "旅行与朋友聚会")
        self.assertEqual(found.json()["previous_entry"], {"id": 2, "date": "2024-08-01", "entry_type": "note"})
        self.assertEqual(found.json()["next_entry"], {"id": 4, "date": "2024-09-18", "entry_type": "diary"})
        self.assertIsNone(self.client.get("/api/entries/1").json()["previous_entry"])
        self.assertIsNone(self.client.get("/api/entries/4").json()["next_entry"])
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"detail": "日记不存在"})

    def test_years_and_months(self):
        years = self.client.get("/api/years")
        months = self.client.get("/api/months", params={"year": 2024})

        self.assertEqual(years.status_code, 200)
        self.assertEqual(
            years.json(),
            [
                {"year": 2023, "entries": 1, "words": 6},
                {"year": 2024, "entries": 3, "words": 18},
            ],
        )
        self.assertEqual(
            months.json(),
            [
                {"month": 8, "entries": 1, "words": 6},
                {"month": 9, "entries": 2, "words": 12},
            ],
        )

    def test_statistics_returns_full_database_aggregates(self):
        response = self.client.get("/api/statistics")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_entries"], 4)
        self.assertEqual(body["total_words"], 24)
        self.assertEqual(body["average_words"], 6)
        self.assertEqual(body["first_date"], "2023-09-17")
        self.assertEqual(body["last_date"], "2024-09-18")
        self.assertEqual(body["most_active_year"], {"year": 2024, "entries": 3, "words": 18})
        self.assertEqual(body["longest_entry"], {"id": 3, "date": "2024-09-17", "entry_type": "diary", "word_count": 8})
        self.assertEqual(body["most_repeated_date"], {"month": 9, "day": 17, "entries": 2})

    def test_on_this_day_groups_entries_by_year(self):
        response = self.client.get("/api/on-this-day", params={"month": 9, "day": 17})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([group["year"] for group in body["groups"]], [2023, 2024])
        self.assertEqual(body["groups"][1]["items"][0]["date"], "2024-09-17")

    def test_on_this_day_rejects_nonexistent_date(self):
        response = self.client.get("/api/on-this-day", params={"month": 2, "day": 30})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "2月没有30日"})

    def test_random_response_is_not_cacheable(self):
        response = self.client.get("/api/random")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(body["total"], 1)
        # 随机页要能直接展示全文，因此响应必须带 content（而不是只有 120 字预览）
        item = body["items"][0]
        content_by_date = {row[0]: row[4] for row in ENTRIES}
        self.assertEqual(item["content"], content_by_date[item["date"]])

    def test_query_validation_uses_fastapi_detail_contract(self):
        response = self.client.get("/api/entries", params={"month": 13, "page": 0})

        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], list)

    def test_database_errors_do_not_leak_sqlite_details(self):
        broken_path = Path(self.temp_dir.name) / "missing.db"
        app.dependency_overrides[get_database] = lambda: Database(broken_path)

        response = self.client.get("/api/entries")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "数据库读取失败"})
        self.assertNotIn(str(broken_path), response.text)

    def test_spa_routes_return_frontend_index(self):
        paths = (
            "/",
            "/browse?year=2024&month=9&q=旅行",
            "/entries/3",
            "/on-this-day?month=9&day=17",
            "/random",
        )

        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('<div id="root"></div>', response.text)

    def test_summary_endpoints_degrade_before_migration(self):
        listing = self.client.get("/api/summaries")
        detail = self.client.get("/api/entries/3/summary")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["items"], [])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "missing")

    def test_spa_fallback_does_not_hide_unknown_api(self):
        response = self.client.get("/api/not-real")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "接口不存在"})


class SummaryEmotionApiTests(unittest.TestCase):
    """摘要 API 的情绪筛选（标签集来自根 .env 的 EMOTION_LABELS）"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "diary.db"
        create_database(self.db_path)
        store = SummaryStore(self.db_path)
        store.migrate()
        settings = {"llm_temperature": .2, "llm_max_tokens": 10, "llm_reasoning_effort": "",
                    "llm_json_mode": False, "content_head_chars": 10, "content_tail_chars": 5,
                    "max_summary_chars": 60, "emotion_labels": list(bs_config.EMOTION_LABELS),
                    "emotion_fallback": bs_config.EMOTION_FALLBACK,
                    "emotion_label_version": bs_config.EMOTION_LABEL_VERSION,
                    "emotion_temperature": 0.0, "emotion_max_tokens": 32}
        payload = algorithm_payload(settings, "model", "prompt")
        self.fingerprint = algorithm_fingerprint(payload)
        store.register_algorithm(self.fingerprint, payload)
        emotion_alg = emotion_payload(settings, "model", "情绪 prompt")
        self.emotion_fingerprint = algorithm_fingerprint(emotion_alg)
        store.register_algorithm(self.emotion_fingerprint, emotion_alg)

        date, entry_type, summary = "2024-09-17", "diary", "旅行与朋友聚会"
        key = entry_key({"date": date, "entry_type": entry_type})
        digest = source_hash("旅行与朋友聚会")
        store.upsert({"date": date, "year": 2024, "month": 9, "day": 17, "entry_type": entry_type,
                      "word_count": 8}, entry_key=key, source_hash_value=digest,
                     algorithm_fingerprint=self.fingerprint,
                     cache_key=cache_key(key, digest, self.fingerprint),
                     status="ok", summary=summary)
        store.upsert_emotion(key, emotion="生气", status="ok", cache_key="emotion-cache-1",
                             algorithm_fingerprint=self.emotion_fingerprint)

        other_date, other_type = "2024-09-18", "diary"
        other_key = entry_key({"date": other_date, "entry_type": other_type})
        other_digest = source_hash("工作记录")
        store.upsert({"date": other_date, "year": 2024, "month": 9, "day": 18,
                      "entry_type": other_type, "word_count": 4},
                     entry_key=other_key, source_hash_value=other_digest,
                     algorithm_fingerprint=self.fingerprint,
                     cache_key=cache_key(other_key, other_digest, self.fingerprint),
                     status="ok", summary="工作记录")     # 这一篇没有情绪（老库形态）

        app.dependency_overrides[get_database] = lambda: Database(self.db_path)
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.temp_dir.cleanup()

    def test_summary_items_expose_emotion_and_status(self):
        body = self.client.get("/api/summaries", params={"status": "all"}).json()
        items = {item["entry_date"]: item for item in body["items"]}
        self.assertEqual(items["2024-09-17"]["emotion"], "生气")
        self.assertEqual(items["2024-09-17"]["emotion_status"], "ok")
        self.assertEqual(items["2024-09-18"]["emotion"], "")
        self.assertEqual(items["2024-09-18"]["emotion_status"], "missing")

    def test_emotion_filter_narrows_the_list(self):
        matched = self.client.get("/api/summaries", params={"status": "all", "emotion": "生气"}).json()
        self.assertEqual(matched["total"], 1)
        self.assertEqual(matched["items"][0]["entry_date"], "2024-09-17")
        empty = self.client.get("/api/summaries", params={"status": "all", "emotion": "悲伤"}).json()
        self.assertEqual((empty["total"], empty["items"]), (0, []))

    def test_unknown_emotion_is_rejected(self):
        response = self.client.get("/api/summaries", params={"emotion": "暴躁"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "emotion 取值不合法：暴躁"})

    def test_blank_emotion_means_no_filter(self):
        """?emotion= 不该被当成"只看没有情绪的"，应与不传时一致"""
        with_blank = self.client.get("/api/summaries", params={"status": "all", "emotion": "  "}).json()
        without = self.client.get("/api/summaries", params={"status": "all"}).json()
        self.assertEqual(with_blank["total"], without["total"])

    def test_emotion_labels_endpoint_lists_full_label_set_with_counts(self):
        body = self.client.get("/api/summaries/emotions").json()
        labels = [item["emotion"] for item in body["items"]]
        self.assertEqual(labels, list(bs_config.EMOTION_LABELS))
        counts = {item["emotion"]: item["count"] for item in body["items"]}
        self.assertEqual(counts["生气"], 1)
        self.assertEqual(counts[bs_config.EMOTION_FALLBACK], 0)

    def test_entry_summary_carries_emotion(self):
        body = self.client.get("/api/entries/3/summary").json()
        self.assertEqual((body["emotion"], body["emotion_status"]), ("生气", "ok"))


class EmptyDatabaseApiTests(unittest.TestCase):
    def test_random_returns_404_for_empty_database(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "empty.db"
            create_database(db_path, entries=[])
            app.dependency_overrides[get_database] = lambda: Database(db_path)
            try:
                with TestClient(app) as client:
                    response = client.get("/api/random")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "暂无日记记录"})
            finally:
                app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()