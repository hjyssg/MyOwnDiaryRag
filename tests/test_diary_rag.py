import sqlite3
import unittest

from scripts.diary_rag import answer_question_text


class TestDiaryRagQA(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE diary_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                year INTEGER,
                month INTEGER,
                day INTEGER,
                content TEXT,
                summary TEXT,
                entry_type TEXT
            )
            """
        )

        rows = [
            ("2023-01-05", 2023, 1, 5, "今天在上海吃饭，晚上回家。", None, "single_day"),
            ("2023-03-09", 2023, 3, 9, "晚上去厦门，吃了海鲜。", None, "single_day"),
            ("2023-06-01", 2023, 6, 1, "这周还去了广州出差。", None, "single_day"),
            ("2026-01-01", 2026, 1, 1, "早上滴滴去白云机场，晚上到广州。", None, "single_day"),
        ]
        self.conn.executemany(
            "INSERT INTO diary_entries (date, year, month, day, content, summary, entry_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_where_question_should_return_cities(self):
        ans = answer_question_text(self.conn, "2023年我去了哪里", use_llm=False)
        self.assertIn("2023年", ans)
        self.assertIn("上海", ans)
        self.assertIn("厦门", ans)

    def test_yes_no_question_should_answer_not_go_for_xiamen(self):
        ans = answer_question_text(self.conn, "我今年一月份去了厦门了吗", use_llm=False)
        self.assertIn("没去", ans)

    def test_yes_no_question_should_answer_go_for_guangzhou(self):
        ans = answer_question_text(self.conn, "我今年一月份去了广州了吗", use_llm=False)
        self.assertIn("去了", ans)


if __name__ == "__main__":
    unittest.main()
