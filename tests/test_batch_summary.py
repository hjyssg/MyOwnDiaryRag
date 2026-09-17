#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 单元测试（不需要真实 LLM）

覆盖：LLM 本地地址守卫、思考开关、Prompt 装载、摘要清洗、Markdown 渲染。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from batch_summary import config as bs_config  # noqa: E402
from batch_summary import render, summary  # noqa: E402
from batch_summary.llm import (  # noqa: E402
    LLMClient,
    LLMError,
    assert_local,
    build_chat_payload,
    is_embedding_model,
    normalize_reasoning_effort,
)

TEMPLATE = "日期：{DATE} 类型：{ENTRY_TYPE}\n{CONTENT}"


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


def make_record(entry_id=1, entry_date="2015-01-20", text="今天去公园散步，全家都很开心。", **overrides):
    record = {
        "entry_id": entry_id,
        "entry_date": entry_date,
        "entry_type": "multi_day",
        "word_count": 12,
        "summary": text,
    }
    record.update(overrides)
    return record


class LLMGuardTests(unittest.TestCase):
    def test_local_address_allowed(self):
        self.assertEqual(assert_local("http://127.0.0.1:1234/v1"), "127.0.0.1")
        self.assertEqual(assert_local("http://localhost:1234/v1"), "localhost")

    def test_remote_address_refused(self):
        with self.assertRaises(LLMError):
            assert_local("https://api.openai.com/v1")
        # 显式允许时才放行
        self.assertEqual(assert_local("https://api.openai.com/v1", allow_remote=True), "api.openai.com")

    def test_embedding_detection(self):
        self.assertTrue(is_embedding_model("text-embedding-nomic-embed-text-v1.5"))
        self.assertFalse(is_embedding_model("qwen3-8b-instruct"))


class ReasoningEffortTests(unittest.TestCase):
    """推理模型思考开关

    实测 qwen3.5-9b：思考会先吃掉整个 max_tokens 预算，使 message.content 为空
    （finish_reason=length），因此需要 reasoning_effort 与足够的默认预算。
    摘要比旧版的"事件标题"长得多，默认预算也要更宽松。
    """

    def test_normalize_values(self):
        self.assertEqual(normalize_reasoning_effort(None), "")
        self.assertEqual(normalize_reasoning_effort(""), "")
        self.assertEqual(normalize_reasoning_effort("   "), "")
        self.assertEqual(normalize_reasoning_effort(" NONE "), "none")
        self.assertEqual(normalize_reasoning_effort("High"), "high")

    def test_normalize_rejects_unknown_value(self):
        with self.assertRaises(LLMError):
            normalize_reasoning_effort("always")

    def test_payload_omits_reasoning_effort_by_default(self):
        payload = build_chat_payload("hi", model="m", temperature=0.2, max_tokens=4096)
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertFalse(payload["stream"])

    def test_payload_includes_reasoning_effort_and_json_mode(self):
        payload = build_chat_payload(
            "hi", model="m", temperature=0.2, max_tokens=4096,
            json_mode=True, reasoning_effort="none",
        )
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_payload_rejects_bad_reasoning_effort(self):
        with self.assertRaises(LLMError):
            build_chat_payload(
                "hi", model="m", temperature=0.2, max_tokens=4096,
                reasoning_effort="always",
            )

    def test_defaults_leave_room_for_long_summaries(self):
        self.assertGreaterEqual(bs_config.DEFAULT_LLM_MAX_TOKENS, 4096)
        self.assertGreaterEqual(bs_config.DEFAULT_LLM_TIMEOUT, 120)
        self.assertGreaterEqual(bs_config.MAX_SUMMARY_CHARS, 40)

    def test_empty_response_error_explains_truncated_thinking(self):
        client = LLMClient.__new__(LLMClient)   # 绕过 __init__，避免依赖 .env
        client.max_tokens = 4096
        text = client._empty_response_error(
            {"finish_reason": "length"},
            {"reasoning_content": "思考" * 10},
            {"usage": {"completion_tokens_details": {"reasoning_tokens": 4096}}},
        )
        self.assertIn("模型返回内容为空", text)
        self.assertIn("reasoning_tokens=4096", text)
        self.assertIn("max_tokens=4096", text)
        self.assertIn("LLM_REASONING_EFFORT=none", text)


class PromptTests(unittest.TestCase):
    def test_build_prompt_replaces_placeholders(self):
        prompt = summary.build_prompt(TEMPLATE, make_entry())
        self.assertIn("2015-01-20", prompt)
        self.assertIn("今天去公园散步", prompt)
        self.assertNotIn("{CONTENT}", prompt)

    def test_truncate_long_content(self):
        text = summary.truncate_content("甲" * 8000)
        self.assertIn("中间省略", text)
        self.assertLess(len(text), 8000)
        self.assertLessEqual(
            len(text), bs_config.CONTENT_HEAD_CHARS + bs_config.CONTENT_TAIL_CHARS + 20
        )

    def test_short_content_untouched(self):
        body = "今天去了郊外。" * 10
        self.assertEqual(summary.truncate_content(body), body)

    def test_prompt_file_has_placeholders(self):
        template = summary.load_prompt_template()
        self.assertIn("{CONTENT}", template)
        self.assertIn("{DATE}", template)
        # 新 Prompt 明确要求"不要判断重要性"
        self.assertIn("重要", template)

    def test_prompt_asks_for_short_one_line_summaries(self):
        """针对实测问题：摘要过长、复述日期、用"作者"称呼、写元评论"""
        template = summary.load_prompt_template()
        self.assertIn("20~40 字", template)
        self.assertIn("50 字", template)
        self.assertIn("不要重复日期", template)
        self.assertIn('不要用"作者"来称呼自己', template)
        self.assertIn("完整反映了原文", template)      # 作为禁止示例出现
        self.assertIn("【示例", template)              # few-shot 示例是压短的关键

    def test_prompt_fingerprint_changes_with_text(self):
        self.assertNotEqual(summary.prompt_sha1("a"), summary.prompt_sha1("b"))
        self.assertEqual(len(summary.prompt_sha1_from_file()), 12)


class SummaryCleaningTests(unittest.TestCase):
    """模型输出 -> 一行摘要（格式化完全由 Python 负责，模型不做排版）"""

    def test_plain_text_kept(self):
        self.assertEqual(
            summary.clean_summary("今天去公园散步，全家都很开心。"),
            "今天去公园散步，全家都很开心。",
        )

    def test_fenced_code_block_unwrapped(self):
        raw = "```\n今天去公园散步，全家都很开心。\n```"
        self.assertEqual(summary.clean_summary(raw), "今天去公园散步，全家都很开心。")

    def test_label_prefix_removed(self):
        self.assertEqual(summary.clean_summary("摘要：今天去郊外旅游。"), "今天去郊外旅游。")
        self.assertEqual(summary.clean_summary("Summary: went to Xiamen."), "went to Xiamen.")

    def test_list_and_heading_prefixes_removed(self):
        self.assertEqual(summary.clean_summary("- 今天去郊外旅游。"), "今天去郊外旅游。")
        self.assertEqual(summary.clean_summary("1. 今天去郊外旅游。"), "今天去郊外旅游。")
        self.assertEqual(summary.clean_summary("## 今天去郊外旅游。"), "今天去郊外旅游。")

    def test_multiline_collapsed_to_single_line(self):
        raw = "今天去郊外旅游。\n\n晚上吃了面条。"
        self.assertEqual(summary.clean_summary(raw), "今天去郊外旅游。 晚上吃了面条。")

    def test_wrapping_quotes_stripped(self):
        self.assertEqual(summary.clean_summary('“今天去郊外旅游。”'), "今天去郊外旅游。")

    def test_blank_outputs(self):
        for raw in (None, "", "   \n  ", "```\n\n```"):
            with self.subTest(raw=raw):
                self.assertEqual(summary.clean_summary(raw), "")
                self.assertEqual(summary.summarize_from_response(raw, make_entry()), "")

    def test_reject_words_are_treated_as_no_summary(self):
        """模型常见的空答案不能被当成摘要（旧版正是这一条产生了大量假结果）"""
        for raw in ("无", "无。", "没有", "暂无", "none", "N/A", "！！！"):
            with self.subTest(raw=raw):
                self.assertTrue(summary.is_blank_summary(summary.clean_summary(raw)))
                self.assertEqual(summary.summarize_from_response(raw, make_entry()), "")

    def test_normal_summary_is_not_blank(self):
        self.assertFalse(summary.is_blank_summary("今天去郊外旅游，吃了面条。"))

    def test_long_summary_truncated(self):
        raw = "甲" * (bs_config.MAX_SUMMARY_CHARS + 200)
        cleaned = summary.clean_summary(raw)
        self.assertLessEqual(len(cleaned), bs_config.MAX_SUMMARY_CHARS + 1)
        self.assertTrue(cleaned.endswith("…"))

    def test_truncation_prefers_sentence_end(self):
        # 句读要落在上限的后半段内才会被采用（构造成长度依赖 MAX_SUMMARY_CHARS 的文本）
        raw = "好" * (bs_config.MAX_SUMMARY_CHARS // 2 + 5) + "。" + "坏" * 300
        cleaned = summary.summarize_from_response(raw, make_entry())
        self.assertTrue(cleaned.endswith("。"))
        self.assertLessEqual(len(cleaned), bs_config.MAX_SUMMARY_CHARS)

    def test_summarize_from_response_cleans_and_returns_text(self):
        self.assertEqual(
            summary.summarize_from_response("```\n摘要：今天去郊外旅游。\n```", make_entry()),
            "今天去郊外旅游。",
        )

    def test_leading_date_prefix_dropped(self):
        """行首已经有 MMDD 标签，摘要里再写一遍日期纯属浪费字数"""
        cases = {
            "2020 年 2 月 8 日下午，我去公园散步。": "我去公园散步。",
            "2020-02-08 我去公园散步。": "我去公园散步。",
            "2 月 8 日，我去公园散步。": "我去公园散步。",
            "这一天，我去公园散步。": "我去公园散步。",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(summary.clean_summary(raw), expected)

    def test_first_person_rewrite_only_at_sentence_start(self):
        """句首的"作者/笔者"改回"我"；被修饰的（这本书的作者）不动"""
        self.assertEqual(
            summary.clean_summary("作者与朋友去了公园。随后，作者教他背单词。"),
            "我与朋友去了公园。随后，我教他背单词。",
        )
        self.assertEqual(
            summary.clean_summary("看完了《山城纪事》，该书的作者是美国人。"),
            "看完了《山城纪事》，该书的作者是美国人。",
        )

    def test_meta_tail_sentence_dropped(self):
        """实测模型爱写"整篇日记主要记录了…""内容简洁且完整反映了原文"来凑字数"""
        self.assertEqual(
            summary.clean_summary("今天去看电影，很开心。整篇日记主要记录了观影经历及最终的情绪状态。"),
            "今天去看电影，很开心。",
        )
        self.assertEqual(
            summary.clean_summary("和朋友跑了五公里。内容简洁且完整反映了原文所记载的日常片段。"),
            "和朋友跑了五公里。",
        )
        # 正常内容不受影响
        self.assertEqual(
            summary.clean_summary("和朋友看了两部电影。观影结束后心情很爽快。"),
            "和朋友看了两部电影。观影结束后心情很爽快。",
        )

    def test_short_cap_keeps_first_sentence(self):
        """上限只有 60 字：宁可只留第一句，也不要半句 + 省略号"""
        raw = (
            "和朋友一同完成了 5 公里的跑步活动。"
            "关于这次跑步的路线、配速以及当天沿途的天气和遇到的人，还有自己整体的感受，这里就再多补充几句说明。"
        )
        cleaned = summary.clean_summary(raw)
        self.assertEqual(cleaned, "和朋友一同完成了 5 公里的跑步活动。")
        self.assertLessEqual(len(cleaned), bs_config.MAX_SUMMARY_CHARS)


class RenderTests(unittest.TestCase):
    def test_markdown_layout(self):
        records = [
            make_record(1, "2015-01-20", "周末去公园散步。"),
            make_record(2, "2015-07-10", "去郊外玩了三天。"),
            make_record(3, "2016-03-05", "换了新工作。"),
        ]
        expected = "\n".join([
            "# 日记总结", "",
            render.HEADER_NOTE, "",
            "## 2015年", "",
            "- 0120 周末去公园散步。",
            "- 0710 去郊外玩了三天。", "",
            "## 2016年", "",
            "- 0305 换了新工作。",
        ]) + "\n"
        self.assertEqual(render.render_markdown(records), expected)

    def test_same_day_entries_each_get_a_line(self):
        records = [
            make_record(1, "2015-01-01", "新年回顾：去年换了工作。"),
            make_record(2, "2015-01-01", "元旦和朋友吃饭。"),
        ]
        lines = render.render_sections(records)
        self.assertIn("- 0101 新年回顾：去年换了工作。", lines)
        self.assertIn("- 0101 元旦和朋友吃饭。", lines)

    def test_records_without_summary_are_skipped(self):
        records = [make_record(1, "2015-01-20", ""), make_record(2, "2015-01-21", "   ")]
        self.assertEqual(render.render_sections(records), [])
        self.assertEqual(
            render.render_markdown(records), "# 日记总结\n\n" + render.HEADER_NOTE + "\n"
        )

    def test_markdown_shows_emotion_label(self):
        """有情绪判断的行：日期后面紧跟【标签】（预览与最终产物共用同一套渲染）"""
        records = [
            make_record(1, "2015-01-20", "周末去公园散步。", emotion="快乐"),
            make_record(2, "2015-01-21", "被同事甩锅。", emotion="生气", emotion_status="ok"),
            make_record(3, "2015-01-22", "照常上班。"),
        ]
        lines = render.render_sections(records)
        self.assertIn("- 0120【快乐】周末去公园散步。", lines)
        self.assertIn("- 0121【生气】被同事甩锅。", lines)
        self.assertIn("- 0122 照常上班。", lines)              # 没判断情绪 -> 保持旧格式
        markdown = render.render_markdown(records)
        self.assertIn("- 0120【快乐】周末去公园散步。", markdown)
        self.assertEqual(sum(1 for line in markdown.splitlines() if line.startswith("- ")), 3)

    def test_blank_or_missing_emotion_keeps_old_format(self):
        """--no-emotion / 判断失败 / 空正文都拿不到标签，行格式与旧版逐字一致"""
        records = [
            make_record(1, "2015-01-20", "周末去公园散步。", emotion=""),
            make_record(2, "2015-01-20", "周末去公园散步。", emotion="   "),
            make_record(3, "2015-01-20", "周末去公园散步。",
                        emotion=None, emotion_status="failed"),
        ]
        for record in records:
            with self.subTest(record=record):
                self.assertEqual(render.format_emotion_label(record), "")
                self.assertIn("- 0120 周末去公园散步。", render.render_sections([record]))

    def test_date_labels_and_years(self):
        self.assertEqual(render.format_date_label({"entry_date": "2015-01-20"}), "0120")
        self.assertEqual(render.format_date_label({"entry_date": "2015-03"}), "03月")
        self.assertEqual(render.format_date_label({"entry_date": ""}), render.UNKNOWN_LABEL)
        self.assertEqual(render.year_of({"entry_date": "2015-01-20"}), 2015)
        self.assertEqual(render.year_of({"entry_date": "", "year": 2016}), 2016)

    def test_summarize_years_counts_per_year(self):
        records = [
            make_record(1, "2015-01-20"),
            make_record(2, "2015-02-20"),
            make_record(3, "2016-01-20"),
        ]
        self.assertEqual(render.summarize_years(records), {2015: 2, 2016: 1})


if __name__ == "__main__":
    unittest.main()
