#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI 契约测试。

运行：python -m unittest tests.test_web_api -v
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from database import Database
from webapp.app import app
from webapp.dependencies import get_database


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
    ("2023-09-17", 2023, 9, 17, "旧年旅行记录", "2023.txt", "single_day", 6),
    ("2024-08-01", 2024, 8, 1, "普通八月日记", "2024-08.txt", "note", 6),
    ("2024-09-17", 2024, 9, 17, "旅行与朋友聚会", "2024-09.txt", "single_day", 8),
    ("2024-09-18", 2024, 9, 18, "工作记录", "2024-09.txt", "single_day", 4),
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
        self.temp_dir = tempfile.TemporaryDirectory()
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
                "entry_type": "single_day",
                "q": "  旅行  ",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["query"], "旅行")
        self.assertEqual(body["items"][0]["date"], "2024-09-17")

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
        self.assertEqual(response.json()["total"], 1)

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


class EmptyDatabaseApiTests(unittest.TestCase):
    def test_random_returns_404_for_empty_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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