#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记总结 - 实时进度（心跳 / 状态块 / 运行目录）测试

覆盖用户要求：程序自己持续打印人类可读进度、阶段中文名、覆盖天数、
日志变成"最近日志"、心跳线程可干净退出、status.py 复用同一格式。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

import io
import json
import logging
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.batch_summary import config as bs_config  # noqa: E402
from scripts.batch_summary import main as bs_main  # noqa: E402
from scripts.batch_summary import progress as progress_mod  # noqa: E402
from scripts.batch_summary import state as state_mod  # noqa: E402
from scripts.batch_summary import status as status_mod  # noqa: E402
from scripts.batch_summary.llm import LLMError  # noqa: E402

TEMPLATE = "日期：{DATE}\n{CONTENT}"
NOW = datetime(2026, 9, 16, 10, 12, 0)
DEFAULT_SUMMARY = "这一天没有特别的事，照常上班吃饭。"
SUMMARY_TEXT = "今天去公园散步，全家都很开心。"


def make_snapshot(**overrides):
    snapshot = {
        "phase": "calling_model",
        "phase_label": progress_mod.phase_label("calling_model"),
        "phase_note": "等待本地模型返回（一次一篇）",
        "scope": "2025 年",
        "total": 328,
        "index": 140,
        "processed": 140,
        "skipped": 0,
        "ok": 86,
        "empty": 54,
        "failed": 0,
        "summaries": 120,
        "days_done": 139,
        "days_total": 328,
        "elapsed_seconds": 900,
        "avg_seconds_per_entry": 6.4,
        "last_entry_seconds": 6.1,
        "eta_seconds": 1200,
        "entries_per_hour": 560.0,
        "current_entry": {"entry_id": 5, "date": "2025-06-18",
                          "entry_type": "multi_day", "word_count": 245},
        "wait_seconds": 12.0,
        "last_log": "正在处理 2025-06-18 multi_day 245字（等待模型响应）",
        "updated_at": state_mod.now_iso(),
    }
    snapshot.update(overrides)
    return snapshot


class FormatTests(unittest.TestCase):
    """状态块渲染（主程序心跳与 status.py 共用）"""

    def test_phase_labels_are_chinese(self):
        self.assertEqual(progress_mod.phase_label("loading"), "读取日记")
        self.assertEqual(progress_mod.phase_label("calling_model"), "调用模型")
        self.assertEqual(progress_mod.phase_label("merging"), "汇总生成总结")
        self.assertEqual(progress_mod.phase_label("saving"), "保存结果")
        self.assertEqual(progress_mod.phase_label("done"), "已完成")

    def test_block_contains_required_lines(self):
        text = progress_mod.format_blocks(make_snapshot(), now=NOW)
        lines = text.splitlines()
        self.assertTrue(all(line.startswith("[10:12:00]") for line in lines))
        self.assertIn("[10:12:00] 2025 年日记批量总结任务运行中", lines[0])
        self.assertIn("已处理：140 / 328 篇（42.7%）", text)
        self.assertIn("覆盖 139 / 328 天", text)
        self.assertIn("当前阶段：调用模型（等待本地模型返回（一次一篇））", text)
        self.assertIn("正在处理：2025-06-18 multi_day 245字（已等待 12s）", text)
        self.assertIn("最近日志：正在处理 2025-06-18", text)
        self.assertIn("结果：有摘要 86 ｜ 空摘要 54 ｜ 失败 0 ｜ 跳过(断点) 0", text)
        self.assertIn("预计剩余约", text)
        self.assertIn("进度：[############", text)

    def test_finished_block_hides_current_entry(self):
        text = progress_mod.format_blocks(make_snapshot(phase="done", wait_seconds=None), now=NOW)
        self.assertIn("2025 年日记批量总结任务已完成 ✅", text)
        self.assertNotIn("正在处理：", text)
        self.assertNotIn("预计剩余", text)
class ReporterTests(unittest.TestCase):
    """心跳线程 / 落盘 / 日志钩子"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stream = io.StringIO()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_reporter(self, **overrides):
        kwargs = dict(
            scope="2025 年", interval=0.05, stream=self.stream, enabled=True,
            progress_file=self.tmp / "progress.json",
            status_file=self.tmp / "运行状态.txt",
        )
        kwargs.update(overrides)
        return progress_mod.ProgressReporter(**kwargs)

    def test_heartbeat_prints_and_stops_cleanly(self):
        reporter = self.make_reporter()
        reporter.start()
        self.assertTrue(reporter.running)
        self.assertIn("日记批量总结任务运行中", self.stream.getvalue())    # 启动立刻打一块
        reporter.set_total(2, days_total=2)
        reporter.update(1, current={"id": 1, "date": "2025-01-01",
                                    "entry_type": "multi_day", "word_count": 10})
        time.sleep(0.25)
        self.assertGreaterEqual(self.stream.getvalue().count("日记批量总结任务运行中"), 2)
        reporter.stop()
        self.assertFalse(reporter.running)
        after_stop = len(self.stream.getvalue())
        time.sleep(0.2)
        self.assertEqual(len(self.stream.getvalue()), after_stop)      # 停止后不再打印

    def test_progress_files_written_on_update(self):
        reporter = self.make_reporter(enabled=False)      # --quiet 时文件仍要写
        reporter.set_total(2, days_total=2)
        reporter.update(1, stats={"ok": 1, "empty": 0, "failed": 0, "skipped": 0, "summaries": 3},
                        current={"id": 1, "date": "2025-01-01",
                                 "entry_type": "multi_day", "word_count": 10})
        snapshot = json.loads((self.tmp / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual((snapshot["total"], snapshot["index"]), (2, 1))
        self.assertEqual(snapshot["ok"], 1)
        self.assertEqual(snapshot["days_done"], 1)
        status_text = (self.tmp / "运行状态.txt").read_text(encoding="utf-8")
        self.assertIn("已处理：1 / 2 篇", status_text)
        self.assertFalse((self.tmp / "progress.json.tmp").exists())

    def test_days_counted_by_distinct_dates(self):
        reporter = self.make_reporter(enabled=False)
        for index, date in enumerate(["2025-01-01", "2025-01-01", "2025-01-02"], 1):
            reporter.update(index, current={"id": index, "date": date})
        self.assertEqual(reporter.snapshot()["days_done"], 2)

    def test_clear_current_removes_stale_entry(self):
        reporter = self.make_reporter(enabled=True)
        reporter.update(1, current={"id": 1, "date": "2025-01-01"})
        reporter.clear_current()
        snapshot = reporter.snapshot()
        self.assertIsNone(snapshot["current_entry"])
        self.assertIsNone(snapshot["wait_seconds"])

    def test_quiet_reporter_prints_nothing(self):
        reporter = self.make_reporter(enabled=False)
        reporter.start()
        reporter.emit("不应该出现")
        self.assertEqual(self.stream.getvalue(), "")
        self.assertFalse(reporter.running)

    def test_logger_becomes_last_log_line(self):
        reporter = self.make_reporter(enabled=False)
        logger = logging.getLogger("tests.batch_summary.progress")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        reporter.attach_logger(logger)
        try:
            logger.warning("调用失败（第 1/3 次）：连接失败；2.0s 后重试")
        finally:
            reporter.detach_logger()
        self.assertIn("[警告] 调用失败", reporter.snapshot()["last_log"])
        self.assertIn("调用失败", reporter.text(now=NOW))

    def test_default_interval_from_config(self):
        reporter = progress_mod.ProgressReporter(stream=self.stream, enabled=False)
        self.assertEqual(reporter.interval, float(bs_config.HEARTBEAT_SECONDS))

    def test_unknown_scope_and_empty_total_are_readable(self):
        text = progress_mod.format_blocks(
            make_snapshot(scope="", total=0, index=0, current_entry=None), now=NOW
        )
        self.assertIn("日记批量总结任务运行中", text)
        self.assertIn("已处理：正在统计总量…", text)


class FakeClient:
    """最小假模型：按调用次数返回预设摘要，未预设的返回一段普通摘要"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0

    def chat(self, prompt):
        self.call_count += 1
        return self.responses.get(self.call_count, DEFAULT_SUMMARY)


def make_entry(**overrides):
    entry = {
        "id": 1, "date": "2015-01-20", "year": 2015, "month": 1, "day": 20,
        "entry_type": "multi_day", "word_count": 12,
        "content": "今天去公园散步，全家都很开心。",
    }
    entry.update(overrides)
    return entry


class ProcessEntriesReporterTests(unittest.TestCase):
    """process_entries 接入 reporter 后：阶段、快照、逐篇输出都要正确"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stream = io.StringIO()
        self.reporter = progress_mod.ProgressReporter(
            scope="2015 年", interval=3600, stream=self.stream, enabled=True,
            progress_file=self.tmp / "progress.json",
            status_file=self.tmp / "运行状态.txt",
        )

    def tearDown(self):
        self.reporter.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_and_status_file_after_processing(self):
        entries = [
            make_entry(id=1, date="2015-01-20"),
            make_entry(id=2, date="2015-01-21", content="今天很普通。"),
        ]
        summary_state = state_mod.SummaryState(path=self.tmp / "state.json", prompt_sha1="p")
        stats = bs_main.process_entries(
            entries,
            FakeClient({1: SUMMARY_TEXT, 2: "无"}),
            summary_state, TEMPLATE, "p",
            quiet=False, reporter=self.reporter,
        )
        self.assertEqual((stats["ok"], stats["empty"], stats["failed"]), (1, 1, 0))

        snapshot = json.loads((self.tmp / "progress.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["phase"], "done")
        self.assertEqual((snapshot["total"], snapshot["index"]), (2, 2))
        self.assertEqual(snapshot["days_done"], 2)
        self.assertEqual(snapshot["scope"], "2015 年")
        self.assertIsNone(snapshot["current_entry"])
        self.assertIn("处理结束", snapshot["last_log"])

        status_text = (self.tmp / "运行状态.txt").read_text(encoding="utf-8")
        self.assertIn("2015 年日记批量总结任务已完成 ✅", status_text)
        self.assertIn("覆盖 2 天", status_text)
        # 逐篇一行输出仍在（与心跳同锁，不会互相插行）
        self.assertIn("[1/2] 2015-01-20", self.stream.getvalue())
        self.assertIn("调用模型", self.stream.getvalue())

    def test_skip_records_are_counted_in_days(self):
        entry = make_entry(id=1, date="2015-01-20")
        summary_state = state_mod.SummaryState(path=self.tmp / "state.json", prompt_sha1="p")
        summary_state.put(1, {
            "status": "ok", "content_hash": state_mod.content_hash(entry["content"]),
            "prompt_sha1": "p", "summary": SUMMARY_TEXT,
            "entry_date": entry["date"], "entry_id": 1,
        })
        client = FakeClient()
        stats = bs_main.process_entries(
            [entry], client, summary_state, TEMPLATE, "p", reporter=self.reporter,
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(client.call_count, 0)                      # 跳过不调用模型
        self.assertEqual(self.reporter.snapshot()["days_done"], 1)

    def test_failed_entry_is_reported(self):
        class BoomClient(FakeClient):
            def chat(self, prompt):
                self.call_count += 1
                raise LLMError("模拟失败")

        summary_state = state_mod.SummaryState(path=self.tmp / "state.json", prompt_sha1="p")
        stats = bs_main.process_entries(
            [make_entry(id=1)], BoomClient(), summary_state, TEMPLATE, "p",
            reporter=self.reporter,
        )
        self.assertEqual(stats["failed"], 1)
        snapshot = self.reporter.snapshot()
        self.assertEqual(snapshot["failed"], 1)
        self.assertIn("失败", snapshot["last_log"])


class RunDirTests(unittest.TestCase):
    """每次运行一个 YYMMDDHHMMSS 子目录"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_run_dir_uses_timestamp_name(self):
        run_dir = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 18, 30))
        self.assertEqual(run_dir.name, "260916101830")
        self.assertTrue(run_dir.is_dir())

    def test_same_second_gets_suffix(self):
        first = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 18, 30))
        second = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 18, 30))
        self.assertEqual(second.name, "260916101830-2")
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_list_run_dirs_newest_first(self):
        for stamp in ("260916101830", "260916204500", "260917090000"):
            bs_config.new_run_dir(self.tmp, now=datetime.strptime(stamp, "%y%m%d%H%M%S"))
        (self.tmp / "prompt_samples").mkdir()          # 非运行目录应被忽略
        names = [d.name for d in bs_config.list_run_dirs(self.tmp)]
        self.assertEqual(names, ["260917090000", "260916204500", "260916101830"])

    def test_resolve_paths_splits_state_and_results(self):
        args = type("A", (), {"output_dir": str(self.tmp), "flat_output": False})()
        paths = bs_main.resolve_paths(args)
        self.assertEqual(
            paths["state"].resolve(),
            (self.tmp / "summary_state.json").resolve(),
        )  # 断点跨运行共享
        self.assertNotEqual(paths["dir"], self.tmp)                        # 产物进时间戳子目录
        self.assertEqual(paths["markdown"].parent, paths["dir"])
        self.assertEqual(paths["status"].parent, paths["dir"])
        self.assertTrue(paths["status"].name.endswith(".txt"))

        flat = bs_main.resolve_paths(args, timestamped=False)
        self.assertEqual(flat["dir"].resolve(), self.tmp.resolve())
        self.assertEqual(
            flat["markdown"].resolve(),
            (self.tmp / "日记总结.md").resolve(),
        )

    def test_scope_label_and_heartbeat_interval(self):
        self.assertEqual(bs_main.scope_label([2025]), "2025 年")
        self.assertEqual(bs_main.scope_label([2015, 2016]), "2015 年、2016 年")
        self.assertEqual(bs_main.scope_label(None), "全部年份")
        fast = type("A", (), {"heartbeat": 1.0})()
        self.assertEqual(
            bs_main.heartbeat_interval(fast, {}), float(bs_config.HEARTBEAT_MIN_SECONDS)
        )
        slow = type("A", (), {"heartbeat": 60.0})()
        self.assertEqual(bs_main.heartbeat_interval(slow, {}), 60.0)
        default = type("A", (), {"heartbeat": None})()
        self.assertEqual(bs_main.heartbeat_interval(default, {"heartbeat_seconds": 45}), 45.0)
        # .env 配置过小也会被下限托住，避免刷屏
        tiny = type("A", (), {"heartbeat": None})()
        self.assertEqual(
            bs_main.heartbeat_interval(tiny, {"heartbeat_seconds": 0.1}),
            float(bs_config.HEARTBEAT_MIN_SECONDS),
        )


class StatusFileTests(unittest.TestCase):
    """status.py：自动找最近一次运行 + 复用状态块格式"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_find_run_dir_prefers_latest_with_progress(self):
        old = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 0, 0))
        new = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 11, 0, 0))
        (old / "progress.json").write_text("{}", encoding="utf-8")
        self.assertEqual(status_mod.find_run_dir(self.tmp), old)   # 更新的没快照 -> 用有快照的
        (new / "progress.json").write_text("{}", encoding="utf-8")
        self.assertEqual(status_mod.find_run_dir(self.tmp), new)

    def test_render_report_uses_progress_format(self):
        run_dir = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 0, 0))
        (run_dir / "progress.json").write_text(
            json.dumps(make_snapshot(phase="done", wait_seconds=None), ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / bs_config.STATUS_FILE_NAME).write_text("x", encoding="utf-8")
        report = status_mod.render_report(run_dir, base_dir=self.tmp)
        self.assertIn("2025 年日记批量总结任务已完成 ✅", report)
        self.assertIn("已处理：140 / 328 篇", report)
        self.assertIn("运行目录  :", report)
        self.assertIn("状态文件  :", report)

    def test_render_report_falls_back_without_progress(self):
        report = status_mod.render_report(self.tmp, base_dir=self.tmp)
        self.assertIn("还没有 progress.json", report)
        self.assertIn("python scripts/batch_summary/main.py --all", report)

    def test_format_run_list(self):
        bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 0, 0))
        text = status_mod.format_run_list(self.tmp)
        self.assertIn("260916100000", text)
        self.assertIn("历史运行目录", text)
        self.assertIn("还没有带时间戳的运行目录", status_mod.format_run_list(self.tmp / "nope"))


if __name__ == "__main__":
    unittest.main()