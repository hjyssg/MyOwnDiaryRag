#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 状态与流水线测试（不需要真实 LLM）

覆盖：断点续跑判定、状态原子写入、损坏/旧版状态容错、失败隔离、
摘要汇总与产物写出、进度快照。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.batch_summary import config as bs_config  # noqa: E402
from scripts.batch_summary import main as bs_main  # noqa: E402
from scripts.batch_summary import render  # noqa: E402
from scripts.batch_summary import state as state_mod  # noqa: E402
from scripts.batch_summary import status as status_mod  # noqa: E402
from scripts.batch_summary.llm import LLMError  # noqa: E402

TEMPLATE = "日期：{DATE}\n{CONTENT}"
SUMMARY_TEXT = "今天去公园散步，全家都很开心。"
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
    """按调用次数返回预设响应；fail_calls 中的调用抛 LLMError"""

    def __init__(self, responses=None, fail_calls=()):
        self.responses = responses or {}
        self.fail_calls = set(fail_calls)
        self.call_count = 0

    def chat(self, prompt):
        self.call_count += 1
        if self.call_count in self.fail_calls:
            raise LLMError("模拟失败")
        return self.responses.get(self.call_count, DEFAULT_SUMMARY)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "state.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_load_roundtrip(self):
        st = state_mod.SummaryState(
            path=self.path, prompt_sha1="abc", model="m", entry_types=["multi_day"]
        )
        st.put(1, {"status": "ok", "content_hash": "h1", "prompt_sha1": "abc",
                   "summary": "整理旧照片。"})
        self.assertTrue(st.save(force=True))

        loaded = state_mod.SummaryState(path=self.path).load()
        self.assertEqual(loaded.get(1)["status"], "ok")
        self.assertEqual(loaded.summary_records()[0]["summary"], "整理旧照片。")
        self.assertEqual(loaded.stats()["ok"], 1)

    def test_should_skip_matrix(self):
        st = state_mod.SummaryState(path=self.path, prompt_sha1="abc")
        st.put(1, {"status": "ok", "content_hash": "h1", "prompt_sha1": "abc"})
        st.put(2, {"status": "failed", "content_hash": "h2", "prompt_sha1": "abc"})
        st.put(3, {"status": "empty", "content_hash": "h3", "prompt_sha1": "abc"})

        self.assertEqual(st.should_skip(1, "h1"), (True, "done"))
        self.assertEqual(st.should_skip(3, "h3"), (True, "done"))
        self.assertFalse(st.should_skip(1, "h1", force=True)[0])
        self.assertEqual(st.should_skip(1, "changed")[1], "content-changed")
        self.assertEqual(st.should_skip(2, "h2")[1], "previous-failed")
        self.assertEqual(st.should_skip(99, "h")[1], "no-record")

    def test_prompt_change_requires_reprocess(self):
        st = state_mod.SummaryState(path=self.path, prompt_sha1="abc")
        st.put(1, {"status": "ok", "content_hash": "h1", "prompt_sha1": "abc"})
        st.save(force=True)
        other = state_mod.SummaryState(path=self.path, prompt_sha1="zzz").load()
        self.assertEqual(other.should_skip(1, "h1")[1], "prompt-changed")

    def test_corrupt_state_file_tolerated(self):
        self.path.write_text("{ 这不是合法 JSON", encoding="utf-8")
        st = state_mod.SummaryState(path=self.path).load()
        self.assertEqual(st.results, {})
        st.put(9, {"status": "ok", "content_hash": "h", "prompt_sha1": ""})
        self.assertTrue(st.save(force=True))  # 可正常覆盖
        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(written["version"], state_mod.STATE_VERSION)
        self.assertEqual(written["results"]["9"]["status"], "ok")

    def test_old_version_state_is_discarded(self):
        """旧版（年度回顾，version=1）的状态文件不能被复用"""
        self.path.write_text(
            json.dumps({"version": 1, "results": {"1": {"status": "ok", "events": []}}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        st = state_mod.SummaryState(path=self.path, prompt_sha1="abc").load()
        self.assertEqual(st.results, {})
        self.assertEqual(st.should_skip(1, "h")[1], "no-record")

    def test_atomic_write_leaves_no_tmp_file(self):
        st = state_mod.SummaryState(path=self.path)
        st.put(1, {"status": "ok"})
        st.save(force=True)
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_summary_records_sorted_and_filtered(self):
        st = state_mod.SummaryState(path=self.path)
        st.put(3, {"entry_id": 3, "entry_date": "2016-02-02", "status": "ok",
                   "summary": "换了新工作。"})
        st.put(1, {"entry_id": 1, "entry_date": "2015-01-20", "status": "ok",
                   "summary": "整理旧照片。"})
        st.put(2, {"entry_id": 2, "entry_date": "2015-02-20", "status": "empty",
                   "summary": ""})
        records = st.summary_records()
        self.assertEqual([r["entry_id"] for r in records], [1, 3])   # 空摘要被过滤
        self.assertEqual(st.summary_count(), 2)
        self.assertFalse(state_mod.has_summary({"summary": "  "}))
        self.assertTrue(state_mod.has_summary({"summary": "有"}))

    def test_summary_records_carry_emotion(self):
        """断点状态里的情绪要透出给渲染层：有标签带【】，没标签保持旧格式"""
        st = state_mod.SummaryState(path=self.path)
        st.put(1, {"entry_id": 1, "entry_date": "2015-01-20", "status": "ok",
                   "summary": "整理旧照片。", "emotion": "平淡", "emotion_status": "ok"})
        st.put(2, {"entry_id": 2, "entry_date": "2015-01-21", "status": "ok",
                   "summary": "被同事甩锅。", "emotion": "", "emotion_status": "failed"})
        records = st.summary_records()
        self.assertEqual([r["emotion"] for r in records], ["平淡", ""])
        self.assertEqual([r["emotion_status"] for r in records], ["ok", "failed"])
        self.assertEqual(st.emotion_count(), 1)
        self.assertIn("- 0120【平淡】整理旧照片。", render.render_sections(records))
        self.assertIn("- 0121 被同事甩锅。", render.render_sections(records))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / bs_config.STATE_FILE_NAME
        self.entries = [
            make_entry(id=1),
            make_entry(id=2, date="2015-01-21"),
            make_entry(id=3, date="2015-01-22"),
        ]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, entries, client, prompt_sha1="p1", progress_file=None):
        summary_state = state_mod.SummaryState(
            path=self.state_path, prompt_sha1=prompt_sha1, model="fake"
        ).load()
        stats = bs_main.process_entries(
            entries, client, summary_state, TEMPLATE, prompt_sha1,
            quiet=True, progress=lambda *_: None,
            progress_file=progress_file, year_label="2015",
        )
        return summary_state, stats

    def test_failure_is_isolated_and_resume_skips_processed(self):
        client = FakeClient({1: SUMMARY_TEXT, 3: "这一天没什么事。"}, fail_calls={2})
        _, stats = self._run(self.entries, client)
        self.assertEqual((stats["ok"], stats["empty"], stats["failed"]), (2, 0, 1))
        self.assertEqual(client.call_count, 3)

        # 第二次：成功的两篇跳过，只重试失败的那篇
        client2 = FakeClient({1: "重试后成功。"})
        _, stats2 = self._run(self.entries, client2)
        self.assertEqual(stats2["skipped"], 2)
        self.assertEqual(client2.call_count, 1)

        # 第三次：全部跳过，不再调用模型
        client3 = FakeClient()
        summary_state, stats3 = self._run(self.entries, client3)
        self.assertEqual(client3.call_count, 0)
        self.assertEqual(stats3["skipped"], 3)
        self.assertTrue(self.state_path.exists())
        final = summary_state.stats()
        self.assertEqual(final["ok"] + final["empty"], 3)

    def test_content_change_triggers_reprocess(self):
        self._run(self.entries[:1], FakeClient())
        client = FakeClient()
        _, stats = self._run([make_entry(id=1, content="内容完全不一样了")], client)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(client.call_count, 1)

    def test_records_and_output_files(self):
        summary_state, _ = self._run(
            [make_entry(id=1), make_entry(id=2, date="2015-01-22")],
            FakeClient({1: SUMMARY_TEXT, 2: "装修房子，忙了一整天。"}),
        )
        records = bs_main.collect_summaries(summary_state)
        self.assertEqual(len(records), 2)
        self.assertIn(f"- 0120 {SUMMARY_TEXT}", render.render_markdown(records))

        paths = {
            "markdown": self.tmp / bs_config.MARKDOWN_FILE_NAME,
            "summaries": self.tmp / bs_config.SUMMARIES_FILE_NAME,
        }
        payload = bs_main.build_summaries_payload(
            summary_state, records, model="fake", prompt_sha1_value="p1",
            entry_types=["multi_day"], years=None, stats={},
        )
        bs_main.write_outputs(paths, payload, records)
        self.assertIn(SUMMARY_TEXT, paths["markdown"].read_text(encoding="utf-8"))
        written = json.loads(paths["summaries"].read_text(encoding="utf-8"))
        self.assertEqual(written["summary_count"], 2)
        self.assertEqual(written["entries"][0]["entry_id"], 1)
        self.assertEqual(written["entries"][0]["summary"], SUMMARY_TEXT)

    def test_blank_model_answer_is_marked_empty(self):
        """模型给出"无"时不能被当成摘要（旧版正是这里产生了假事件）"""
        summary_state, stats = self._run([make_entry(id=1)], FakeClient({1: "无"}))
        self.assertEqual((stats["ok"], stats["empty"]), (0, 1))
        self.assertEqual(summary_state.get(1)["status"], "empty")
        self.assertEqual(summary_state.get(1)["summary"], "")
        self.assertEqual(summary_state.summary_count(), 0)

    def test_empty_content_skips_model(self):
        client = FakeClient()
        summary_state, stats = self._run([make_entry(id=1, content="   ")], client)
        self.assertEqual(client.call_count, 0)
        self.assertEqual(summary_state.get(1)["status"], "empty")
        self.assertEqual(stats["summaries"], 0)

    def test_progress_snapshot_finished(self):
        progress_file = self.tmp / "progress.json"
        self._run(self.entries, FakeClient(), progress_file=progress_file)
        snapshot = json.loads(progress_file.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["phase"], "done")
        self.assertEqual((snapshot["total"], snapshot["index"]), (3, 3))
        self.assertEqual(snapshot["processed"], 3)
        self.assertEqual(snapshot["scope"], "2015")
        self.assertEqual(snapshot["ok"], 3)
        self.assertEqual(snapshot["summaries"], 3)
        self.assertIsNone(snapshot["current_entry"])
        self.assertFalse((self.tmp / "progress.json.tmp").exists())

    def test_progress_snapshot_exposes_current_entry_while_running(self):
        """调用模型期间，快照应能看到"正在处理"的那一篇"""
        progress_file = self.tmp / "progress.json"
        seen = {}

        def fake_chat(prompt):
            seen.update(json.loads(progress_file.read_text(encoding="utf-8")))
            return DEFAULT_SUMMARY

        client = FakeClient()
        client.chat = fake_chat
        self._run(self.entries[:1], client, progress_file=progress_file)
        self.assertEqual(seen["phase"], "running")
        self.assertEqual(seen["current_entry"]["entry_id"], 1)
        self.assertEqual(seen["current_entry"]["date"], "2015-01-20")

    def test_status_report_renders_progress_and_falls_back(self):
        self.assertIn("还没有 progress.json", status_mod.render_report(self.tmp))
        progress = {
            "phase": "running", "scope": "2025", "total": 329, "index": 128,
            "processed": 128, "skipped": 0, "ok": 75, "empty": 53, "failed": 0,
            "summaries": 80, "elapsed_seconds": 1172, "avg_seconds_per_entry": 9.16,
            "last_entry_seconds": 9.2, "eta_seconds": 1842, "entries_per_hour": 393.0,
            "current_entry": {"entry_id": 5, "date": "2025-05-21",
                              "entry_type": "multi_day", "word_count": 310},
            "updated_at": state_mod.now_iso(),
        }
        (self.tmp / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False), encoding="utf-8"
        )
        report = status_mod.render_report(self.tmp)
        self.assertIn("128 / 329", report)
        self.assertIn("运行中", report)
        self.assertIn("2025-05-21", report)
        self.assertIn("有摘要 75", report)
        self.assertIn("预计剩余", report)
        self.assertIn("当前阶段：运行中", report)   # 旧快照 phase="running" 也能正常显示


if __name__ == "__main__":
    unittest.main()
