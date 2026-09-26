#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记导入 - 日期检查单元测试

覆盖用户要求：

* 「2月没有30日」这类**不存在**的日期（内容标记与文件名两种）必须被重点提示；
* 「3月的日记放进 5 月文件」这种**月份错放**必须被重点提示；
* 正常日记仍然照常入库（日期体检不阻止导入）；
* 导入结束产出《日记导入日期检查报告.md》警报报告。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.import_diary_to_db import DEFAULT_REPORT_NAME, DiaryImporter  # noqa: E402


class DateCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "diary"
        (self.root / "2025").mkdir(parents=True)
        self.db = Path(self.tmp.name) / "diary.db"
        self.report = Path(self.tmp.name) / DEFAULT_REPORT_NAME

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_import(self):
        importer = DiaryImporter(self.root, self.db, report_path=self.report)
        self.assertTrue(importer.run_import())
        return importer

    def dates_in_db(self):
        with sqlite3.connect(self.db) as connection:
            return [row[0] for row in connection.execute(
                "SELECT date FROM diary_entries ORDER BY date"
            )]

    def test_invalid_date_in_content_is_flagged(self):
        # 05月合集里混进一条 2月30日（不存在的日期）
        self.write("2025/05月.txt",
                   "0501 周四\n五月第一天的内容。\n\n0230 周日\n不存在的日期示例。\n")
        importer = self.run_import()
        joined = "\n".join(importer.critical_warnings)
        self.assertIn("非法日期", joined)
        self.assertIn("2月没有30日", joined)
        # 合法的那一条照常入库
        self.assertIn("2025-05-01", self.dates_in_db())

    def test_month_misfile_is_flagged(self):
        # 9 月的日记放进了 05月.txt（相差 2 个月以上 → 重点提示）
        self.write("2025/05月.txt",
                   "0501 周四\n五月的内容。\n\n0912 周五\n放错月份的九月内容。\n")
        importer = self.run_import()
        joined = "\n".join(importer.critical_warnings)
        self.assertIn("月份错放", joined)
        self.assertIn("0912", joined)
        self.assertIn("05月.txt", joined)

    def test_adjacent_month_spillover_is_only_a_note(self):
        # 09月.txt 里带一条 0830（相邻月溢出）→ 普通提示，不算重点
        self.write("2025/09月.txt", "0901 周一\n九月初。\n\n0830 周日\n八月末顺带记录。\n")
        importer = self.run_import()
        self.assertEqual(importer.critical_warnings, [])
        self.assertTrue(any("跨月溢出" in w for w in importer.date_notes))

    def test_year_heading_is_not_treated_as_date(self):
        # 线下活动文件里的「2024」是年份小标题，不是 20月24日 → 不应误报
        self.write("2025/2025线下活动.txt", "2025\n\n之前的忘记记录\n")
        importer = self.run_import()
        self.assertEqual(importer.critical_warnings, [])

    def test_invalid_filename_date_is_flagged(self):
        self.write("2025/02_30.txt", "文件名是不存在的 2 月 30 日。\n")
        importer = self.run_import()
        self.assertIn("非法日期·文件名", "\n".join(importer.critical_warnings))

    def test_wrong_year_folder_is_flagged(self):
        self.write("2025/2026_股票日记.txt", "0101\n标题年份与文件夹不符。\n")
        importer = self.run_import()
        self.assertIn("年份错放", "\n".join(importer.critical_warnings))

    def test_default_report_name_is_specific(self):
        # 默认报告文件名要具体，不能是笼统的 report.md
        self.assertNotEqual(DEFAULT_REPORT_NAME, "report.md")
        self.assertIn("日期", DEFAULT_REPORT_NAME)

    def test_clean_import_has_no_critical_and_writes_report(self):
        self.write("2025/05月.txt", "0501 周四\n五月第一天。\n\n0502 周五\n五月第二天。\n")
        importer = self.run_import()

        self.assertEqual(importer.critical_warnings, [])
        self.assertEqual(self.dates_in_db(), ["2025-05-01", "2025-05-02"])

        text = self.report.read_text(encoding="utf-8")
        self.assertIn("日记导入日期检查报告", text)
        self.assertIn("未发现非法日期", text)


if __name__ == "__main__":
    unittest.main()
