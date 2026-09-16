#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 运行期「中途预览」测试

覆盖用户要求：全量跑要几小时，最终 日记总结.md 只在整轮结束后才写，
因此运行期间必须能中途查看已总结的内容（``中途预览.md``）。

覆盖点：预览头部（进度/正在处理/阶段措辞）、正文与最终产物逐行一致、
节流刷新、摘要条数不变时复用正文、写失败静默、``--no-preview`` 关闭、
跑完/中断强制写一次、不干扰 status.py。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

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
from scripts.batch_summary import render  # noqa: E402
from scripts.batch_summary import state as state_mod  # noqa: E402
from scripts.batch_summary import status as status_mod  # noqa: E402

TEMPLATE = "日期：{DATE}\n{CONTENT}"
NOW = datetime(2026, 9, 16, 12, 3, 41)
DEFAULT_SUMMARY = "这一天没有特别的事，照常上班吃饭。"


def make_entry(**overrides):
    entry = {
        "id": 1,
        "date": "2015-01-20",
        "year": 2015,
        "month": 1,
        "day": 20,
        "entry_type": "multi_day",
        "word_count": 12,
        "content": "今天去公园散步，全家都很开心。",
    }
    entry.update(overrides)
    return entry


class FakeClient:
    """按调用序号返回预设响应；未预设的调用一律返回一段普通摘要"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0

    def chat(self, prompt):
        self.call_count += 1
        return self.responses.get(self.call_count, DEFAULT_SUMMARY)


class SlowClient(FakeClient):
    """模拟"真实模型要花几秒"的调用；这里只睡 20ms，让预览的节流窗口能过去"""

    def chat(self, prompt):
        time.sleep(0.02)
        return super().chat(prompt)


def make_record(entry_id=1, entry_date="2015-01-20", text="今天去公园散步，全家都很开心。"):
    return {
        "entry_id": entry_id,
        "entry_date": entry_date,
        "entry_type": "multi_day",
        "word_count": 12,
        "summary": text,
    }


def put_result(state, entry_id, entry_date="2015-01-20", summary="今天去公园散步，全家都很开心。"):
    """往断点状态里塞一条"已处理"记录"""
    state.put(entry_id, {
        "entry_id": entry_id,
        "entry_date": entry_date,
        "entry_type": "multi_day",
        "word_count": 12,
        "content_hash": "h",
        "prompt_sha1": "p1",
        "status": "ok" if summary else "empty",
        "summary": summary,
    })


class PreviewRenderTests(unittest.TestCase):
    """预览文本渲染（纯函数）"""

    def test_header_shows_progress_and_current_entry(self):
        records = [make_record()]
        text = render.render_preview(
            records, processed=412, total=3964,
            current={"date": "2019-06-18", "entry_type": "multi_day", "word_count": 245},
            every=60, now=NOW,
        )
        self.assertIn("# 日记总结（中途预览）", text)
        self.assertIn("> 截至 12:03:41 ｜ 已处理 412 / 3964 篇（10.4%）", text)
        self.assertIn("正在处理 2019-06-18 multi_day 245字", text)
        self.assertIn("每 60 秒自动更新", text)
        self.assertIn("- 0120 今天去公园散步，全家都很开心。", text)

    def test_body_is_identical_to_final_markdown(self):
        """中途预览的正文必须与跑完后的 日记总结.md 逐行一致（同一套渲染）"""
        records = [
            make_record(1, "2015-01-20", "整理旧照片。"),
            make_record(2, "2015-07-10", "去郊外旅游。"),
            make_record(3, "2016-03-05", "换了新工作。"),
        ]
        preview = render.render_preview(records, processed=3, total=3, phase="done", now=NOW)
        final = render.render_markdown(records)
        expected = render.render_sections(records)
        # 两边都是：标题 / 空行 / 说明行(×1 或 ×2) / 空行 / 正文
        self.assertEqual(preview.splitlines()[5:], expected)   # 标题 + 快照行 + 阶段说明
        self.assertEqual(final.splitlines()[4:], expected)     # 标题 + 固定说明
        self.assertIn("- 0120 整理旧照片。", preview)
        self.assertIn("- 0710 去郊外旅游。", preview)
        self.assertIn("- 0305 换了新工作。", preview)

    def test_empty_body_gets_hint(self):
        text = render.render_preview([], processed=0, total=10, every=60, now=NOW)
        self.assertIn("目前还没有摘要", text)
        self.assertNotIn("## ", text)

    def test_phase_wording(self):
        running = render.render_preview([], processed=1, total=2, every=60, now=NOW)
        self.assertIn("运行中的快照", running)
        interrupted = render.render_preview([], processed=1, total=2, phase="interrupted", now=NOW)
        self.assertIn("任务已中断", interrupted)
        done = render.render_preview([], processed=2, total=2, phase="done", now=NOW)
        self.assertIn("任务已完成", done)
        # 没传 every 时不出现"每 N 秒"
        self.assertNotIn("自动更新", render.render_preview([], processed=1, total=2, now=NOW))

    def test_preview_config_defaults(self):
        self.assertEqual(bs_config.PREVIEW_FILE_NAME, "中途预览.md")
        self.assertEqual(bs_config.MARKDOWN_FILE_NAME, "日记总结.md")
        self.assertEqual(bs_config.STATE_FILE_NAME, "summary_state.json")
        self.assertGreater(bs_config.PREVIEW_EVERY_SECONDS, 0)
        self.assertGreater(bs_config.PREVIEW_MIN_SECONDS, 0)


class PreviewWriterTests(unittest.TestCase):
    """节流 / 正文缓存 / 静默失败 / 关闭开关"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = state_mod.SummaryState(path=self.tmp / "state.json", prompt_sha1="p1")
        put_result(self.state, 1)
        self.path = self.tmp / "中途预览.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_file_with_summaries(self):
        writer = bs_main.PreviewWriter(self.path, every=60)
        self.assertTrue(writer.maybe(self.state, processed=1, total=10))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("- 0120 今天去公园散步，全家都很开心。", text)
        self.assertIn("已处理 1 / 10 篇", text)
        self.assertEqual(writer.writes, 1)
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_throttled_within_interval(self):
        writer = bs_main.PreviewWriter(self.path, every=60)
        self.assertTrue(writer.maybe(self.state, processed=1, total=10))
        put_result(self.state, 2, entry_date="2015-02-02", summary="去郊外旅游。")
        self.assertFalse(writer.maybe(self.state, processed=2, total=10))   # 未到间隔 -> 不写
        self.assertEqual(writer.writes, 1)
        self.assertNotIn("去郊外旅游", self.path.read_text(encoding="utf-8"))

    def test_interval_floor_keeps_minimum(self):
        writer = bs_main.PreviewWriter(self.path, every=1, min_seconds=5)
        self.assertEqual(writer.every, 5.0)

    def test_disabled_writer_never_writes(self):
        writer = bs_main.PreviewWriter(self.path, every=60, enabled=False)
        self.assertFalse(writer.enabled)
        self.assertFalse(writer.maybe(self.state, processed=1, total=10))
        self.assertFalse(writer.finish(self.state))
        self.assertFalse(self.path.exists())

    def test_zero_interval_is_disabled(self):
        writer = bs_main.PreviewWriter(self.path, every=0)
        self.assertFalse(writer.enabled)
        self.assertFalse(writer.maybe(self.state, processed=1, total=10))

    def test_no_path_is_disabled(self):
        writer = bs_main.PreviewWriter(None, every=60)
        self.assertFalse(writer.enabled)
        self.assertFalse(writer.maybe(self.state, processed=1, total=10))

    def test_finish_forces_write_after_throttle(self):
        writer = bs_main.PreviewWriter(self.path, every=3600)
        writer.maybe(self.state, processed=1, total=10)
        put_result(self.state, 2, entry_date="2015-02-02", summary="去郊外旅游。")
        writer.maybe(self.state, processed=1, total=10)                     # 被节流挡住
        self.assertTrue(writer.finish(self.state, processed=10, total=10, phase="done"))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("去郊外旅游", text)                                   # 收尾会带上最新内容
        self.assertIn("任务已完成", text)

    def test_interrupted_phase_header(self):
        writer = bs_main.PreviewWriter(self.path, every=60)
        writer.finish(self.state, phase="interrupted")
        self.assertIn("任务已中断", self.path.read_text(encoding="utf-8"))

    def test_unchanged_summaries_reuse_cached_body(self):
        """摘要条数没变时只更新头部，不再重新排版（省开销）"""
        writer = bs_main.PreviewWriter(self.path, every=3600)
        writer.maybe(self.state, processed=1, total=10)          # 第一次必写
        calls = []
        original = bs_main.collect_summaries

        def counting_mock(state):
            calls.append(state)
            return original(state)

        bs_main.collect_summaries = counting_mock
        try:
            # finish() 绕过节流强制刷新，但摘要条数没变 -> 复用上次渲染的正文
            self.assertTrue(writer.finish(self.state, processed=2, total=10, phase="running"))
            self.assertEqual(calls, [])
            self.assertIn("已处理 2 / 10 篇", self.path.read_text(encoding="utf-8"))

            put_result(self.state, 2, entry_date="2015-02-02", summary="去郊外旅游。")
            self.assertTrue(writer.finish(self.state, processed=3, total=10, phase="running"))
            self.assertEqual(len(calls), 1)                      # 有新摘要才重新排版
            self.assertIn("去郊外旅游", self.path.read_text(encoding="utf-8"))
        finally:
            bs_main.collect_summaries = original

    def test_write_failure_is_silent(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        writer = bs_main.PreviewWriter(blocker / "中途预览.md", every=60)
        self.assertFalse(writer.maybe(self.state, processed=1, total=10))   # 不抛异常
        self.assertEqual(writer.writes, 0)


class PreviewPipelineTests(unittest.TestCase):
    """process_entries 挂上 preview 后，中途产物就是"已总结的那部分" """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "中途预览.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, entries, client, preview=None):
        summary_state = state_mod.SummaryState(
            path=self.tmp / "state.json", prompt_sha1="p1", model="fake"
        ).load()
        stats = bs_main.process_entries(
            entries, client, summary_state, TEMPLATE, "p1",
            quiet=True, progress=lambda *_: None, year_label="2015", preview=preview,
        )
        return summary_state, stats

    def test_preview_contains_partial_summaries(self):
        writer = bs_main.PreviewWriter(self.path, every=0.01, min_seconds=0)
        _, stats = self._run(
            [make_entry(id=1)],
            SlowClient({1: "今天去公园散步，全家都很开心。"}),
            preview=writer,
        )
        self.assertEqual(stats["ok"], 1)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# 日记总结（中途预览）", text)
        self.assertIn("- 0120 今天去公园散步，全家都很开心。", text)
        self.assertIn("已处理 1 / 1 篇", text)
        self.assertGreater(writer.writes, 0)

    def test_preview_not_written_when_not_passed(self):
        self._run([make_entry(id=1)], FakeClient())
        self.assertFalse(self.path.exists())

    def test_preview_does_not_write_progress_snapshot(self):
        """中途预览不得干扰 status.py：不写 progress.json、不新建运行目录"""
        writer = bs_main.PreviewWriter(self.path, every=0.01, min_seconds=0)
        self._run([make_entry(id=1)], SlowClient(), preview=writer)
        self.assertEqual(
            sorted(p.name for p in self.tmp.iterdir()), ["state.json", "中途预览.md"]
        )


class PreviewCliTests(unittest.TestCase):
    """CLI 参数与路径接线"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preview_interval_from_cli_env_and_default(self):
        default = type("A", (), {"preview_every": None})()
        self.assertEqual(
            bs_main.preview_interval(default, {}), float(bs_config.PREVIEW_EVERY_SECONDS)
        )
        self.assertEqual(
            bs_main.preview_interval(default, {"preview_every_seconds": 120}), 120.0
        )
        too_fast = type("A", (), {"preview_every": 1.0})()
        self.assertEqual(
            bs_main.preview_interval(too_fast, {}), float(bs_config.PREVIEW_MIN_SECONDS)
        )
        off = type("A", (), {"preview_every": 0})()
        self.assertEqual(bs_main.preview_interval(off, {}), 0.0)

    def test_resolve_paths_includes_preview_and_outputs(self):
        args = type("A", (), {"output_dir": str(self.tmp), "flat_output": False})()
        paths = bs_main.resolve_paths(args)
        self.assertEqual(paths["preview"].parent, paths["dir"])
        self.assertEqual(paths["preview"].name, bs_config.PREVIEW_FILE_NAME)
        self.assertEqual(paths["markdown"].name, bs_config.MARKDOWN_FILE_NAME)
        self.assertEqual(paths["summaries"].name, bs_config.SUMMARIES_FILE_NAME)
        self.assertEqual(paths["pending_md"].name, bs_config.PENDING_MD_NAME)

        flat = bs_main.resolve_paths(args, timestamped=False)
        self.assertEqual(
            flat["preview"].resolve(), (self.tmp / bs_config.PREVIEW_FILE_NAME).resolve()
        )

    def test_parser_has_preview_flags(self):
        parser = bs_main.build_parser()
        args = parser.parse_args(["--all", "--preview-every", "120"])
        self.assertEqual(args.preview_every, 120.0)
        self.assertFalse(args.no_preview)
        self.assertTrue(parser.parse_args(["--all", "--no-preview"]).no_preview)

    def test_status_report_points_at_preview_file(self):
        run_dir = bs_config.new_run_dir(self.tmp, now=datetime(2026, 9, 16, 10, 18, 30))
        (run_dir / "progress.json").write_text(
            '{"phase": "running", "updated_at": "%s"}' % state_mod.now_iso(), encoding="utf-8"
        )
        (run_dir / bs_config.PREVIEW_FILE_NAME).write_text("x", encoding="utf-8")
        report = status_mod.render_report(run_dir, base_dir=self.tmp)
        self.assertIn("中途产物", report)
        self.assertIn("中途预览.md", report)


if __name__ == "__main__":
    unittest.main()
