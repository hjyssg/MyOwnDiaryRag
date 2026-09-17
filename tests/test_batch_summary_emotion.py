#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 情绪分类测试（不需要真实 LLM）

覆盖：情绪 Prompt 装载与占位符、标签清洗与归一（别名/包裹符号/兜底）、
每次调用的参数覆盖（只回一个词）、调用失败不抛异常、情绪缓存键与摘要缓存键相互独立、
标签集进算法指纹（改标签 → 情绪重算，摘要不受影响）。

运行：

    python -m unittest discover -s tests -p "test_*.py"
"""

import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config as root_config  # noqa: E402
from batch_summary import config as bs_config  # noqa: E402
from batch_summary import emotion as emotion_mod  # noqa: E402
from batch_summary import main as bs_main  # noqa: E402
from batch_summary.llm import LLMError  # noqa: E402
from summary_database import SummaryRepository, SummaryStore, tables_exist  # noqa: E402
from summary_fingerprint import (  # noqa: E402
    EMOTION_CACHE_NAMESPACE,
    algorithm_fingerprint,
    algorithm_payload,
    cache_key,
    emotion_payload,
)

LABELS = list(root_config.DEFAULT_EMOTION_LABELS)
FALLBACK = LABELS[-1]


def make_entry(**overrides):
    entry = {
        "id": 1,
        "date": "2015-01-20",
        "year": 2015,
        "month": 1,
        "day": 20,
        "entry_type": "diary",
        "word_count": 12,
        "content": "又被同事甩锅，气得睡不着。",
    }
    entry.update(overrides)
    return entry


class FakeClient:
    """记录每次调用的参数，返回预设的标签"""

    def __init__(self, answer="生气", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def chat(self, prompt, **overrides):
        self.calls.append((prompt, overrides))
        if self.error is not None:
            raise self.error
        return self.answer


class PromptTests(unittest.TestCase):
    def test_bundled_prompt_has_required_placeholders(self):
        template = emotion_mod.load_prompt_template()
        for token in ("{DATE}", "{CONTENT}", "{LABELS}"):
            self.assertIn(token, template)

    def test_missing_placeholder_is_rejected(self):
        path = Path(__file__).resolve().parent / "_tmp_emotion_prompt.txt"
        path.write_text("日期：{DATE}\n{CONTENT}\n", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                emotion_mod.load_prompt_template(path)
        finally:
            path.unlink(missing_ok=True)

    def test_build_prompt_fills_labels(self):
        template = emotion_mod.load_prompt_template()
        prompt = emotion_mod.build_prompt(template, make_entry(), labels=LABELS)
        self.assertIn("2015-01-20", prompt)
        self.assertIn("又被同事甩锅", prompt)
        self.assertNotIn("{LABELS}", prompt)
        self.assertIn(" / ".join(LABELS), prompt)



class NormalizeTests(unittest.TestCase):
    def test_exact_label_wins(self):
        self.assertEqual(emotion_mod.normalize_emotion("悲伤", labels=LABELS), ("悲伤", "悲伤"))

    def test_alias_is_normalized(self):
        self.assertEqual(emotion_mod.normalize_emotion("开心", labels=LABELS)[0], "快乐")
        self.assertEqual(emotion_mod.normalize_emotion("郁闷", labels=LABELS)[0], "悲伤")

    def test_clean_label_strips_wrapping_and_prefix(self):
        self.assertEqual(emotion_mod.clean_label("情绪：生气"), "生气")
        self.assertEqual(emotion_mod.clean_label("```\n疲惫\n```"), "疲惫")
        self.assertEqual(emotion_mod.clean_label('"期待"'), "期待")
        self.assertEqual(emotion_mod.clean_label("  \n \n"), "")

    def test_substring_match_covers_chatty_answers(self):
        label, note = emotion_mod.normalize_emotion("这篇日记的主导情绪是焦虑。", labels=LABELS)
        self.assertEqual(label, "焦虑")
        self.assertIn("焦虑", note)

    def test_unknown_answer_falls_back_to_last_label(self):
        self.assertEqual(emotion_mod.normalize_emotion("我无法判断", labels=LABELS), (FALLBACK, "我无法判断"))
        self.assertEqual(emotion_mod.normalize_emotion("", labels=LABELS), (FALLBACK, ""))
        self.assertEqual(emotion_mod.normalize_emotion(None, labels=LABELS), (FALLBACK, ""))

    def test_custom_label_set_and_fallback(self):
        labels = ["好", "坏", "未知"]
        self.assertEqual(emotion_mod.normalize_emotion("好", labels=labels), ("好", "好"))
        self.assertEqual(emotion_mod.normalize_emotion("开心", labels=labels)[0], "未知")

    def test_alias_pointing_outside_label_set_is_ignored(self):
        """标签集被 .env 改小后，老别名不该映射出非法标签"""
        labels = ["平淡", "其他"]
        self.assertEqual(emotion_mod.normalize_emotion("难过", labels=labels), ("其他", "难过"))


class ClassifierTests(unittest.TestCase):
    def make_classifier(self, client, **overrides):
        kwargs = {
            "fingerprint": "fp-1",
            "labels": LABELS,
            "fallback": FALLBACK,
            "max_tokens": bs_config.DEFAULT_EMOTION_MAX_TOKENS,
        }
        kwargs.update(overrides)
        return emotion_mod.EmotionClassifier(client, emotion_mod.load_prompt_template(), **kwargs)

    def test_classify_passes_short_output_overrides(self):
        client = FakeClient(answer="生气")
        classifier = self.make_classifier(client)
        outcome = classifier.classify(make_entry())
        self.assertEqual(
            (outcome["emotion"], outcome["status"], outcome["raw"]), ("生气", "ok", "生气")
        )
        prompt, overrides = client.calls[0]
        self.assertEqual(overrides["max_tokens"], bs_config.DEFAULT_EMOTION_MAX_TOKENS)
        self.assertEqual(overrides["temperature"], bs_config.DEFAULT_EMOTION_TEMPERATURE)
        self.assertFalse(overrides["json_mode"])
        self.assertIn("又被同事甩锅", prompt)
        self.assertEqual(classifier.call_count, 1)

    def test_llm_error_becomes_failed_status(self):
        classifier = self.make_classifier(FakeClient(error=LLMError("连接失败")))
        outcome = classifier.classify(make_entry())
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["emotion"], "")
        self.assertIn("连接失败", outcome["error"])

    def test_unexpected_error_does_not_escape(self):
        classifier = self.make_classifier(FakeClient(error=RuntimeError("boom")))
        outcome = classifier.classify(make_entry())
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("RuntimeError", outcome["error"])

    def test_emotion_cache_key_is_separate_from_summary_key(self):
        classifier = self.make_classifier(FakeClient())
        key = classifier.cache_key("v1:2015-01-20:diary", "digest")
        self.assertEqual(
            key,
            cache_key("v1:2015-01-20:diary", "digest", "fp-1",
                      namespace=EMOTION_CACHE_NAMESPACE),
        )
        self.assertNotEqual(key, cache_key("v1:2015-01-20:diary", "digest", "fp-1"))


class EmotionFingerprintTests(unittest.TestCase):
    def settings(self, labels=None):
        return {
            "llm_temperature": .2, "llm_max_tokens": 100, "llm_reasoning_effort": "none",
            "llm_json_mode": False, "content_head_chars": 10, "content_tail_chars": 5,
            "max_summary_chars": 60, "emotion_labels": list(labels or LABELS),
            "emotion_fallback": FALLBACK, "emotion_label_version": "v1",
            "emotion_temperature": 0.0, "emotion_max_tokens": 32,
        }

    def test_label_set_participates_in_fingerprint(self):
        base = emotion_payload(self.settings(), "m", "prompt")
        changed = emotion_payload(self.settings(["快乐", "其他"]), "m", "prompt")
        self.assertNotEqual(algorithm_fingerprint(base), algorithm_fingerprint(changed))

    def test_prompt_and_model_change_fingerprint(self):
        base = emotion_payload(self.settings(), "m", "prompt")
        self.assertNotEqual(
            algorithm_fingerprint(base),
            algorithm_fingerprint(emotion_payload(self.settings(), "m", "other prompt")),
        )
        self.assertNotEqual(
            algorithm_fingerprint(base),
            algorithm_fingerprint(emotion_payload(self.settings(), "m2", "prompt")),
        )

    def test_emotion_fingerprint_differs_from_summary_fingerprint(self):
        settings = self.settings()
        self.assertNotEqual(
            algorithm_fingerprint(emotion_payload(settings, "m", "prompt")),
            algorithm_fingerprint(algorithm_payload(settings, "m", "prompt")),
        )


class EmotionLabelConfigTests(unittest.TestCase):
    def test_split_labels_accepts_mixed_separators_and_dedupes(self):
        self.assertEqual(
            root_config.split_emotion_labels("快乐, 平淡，悲伤、生气; 快乐"),
            ["快乐", "平淡", "悲伤", "生气"],
        )
        self.assertEqual(root_config.split_emotion_labels(""), [])
        self.assertEqual(root_config.split_emotion_labels(None), [])

    def test_batch_config_uses_env_labels_with_working_fallback(self):
        self.assertTrue(bs_config.EMOTION_LABELS)
        self.assertEqual(bs_config.EMOTION_FALLBACK, bs_config.EMOTION_LABELS[-1])

    def test_repository_degrades_without_emotion_column(self):
        """迁移前的旧库：情绪列不存在时 emotion_counts 要返回空字典而不是报错"""
        import sqlite3
        import tempfile
        # Windows 上 SQLite 连接释放有延迟，忽略清理失败（与其它测试的环境问题同源）
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "old.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE entry_summaries (entry_key TEXT PRIMARY KEY, entry_date TEXT, "
                    "entry_type TEXT, year INT, month INT, day INT, word_count INT, source_hash TEXT, "
                    "algorithm_fingerprint TEXT, cache_key TEXT, status TEXT, summary TEXT, "
                    "generated_at TEXT, updated_at TEXT)"
                )
            repository = SummaryRepository(path)
            self.assertEqual(repository.emotion_counts(), {})
            with repository.connect() as connection:
                self.assertTrue(tables_exist(connection))


class SetupEmotionTests(unittest.TestCase):
    """CLI/配置 → 情绪判断器的接线（--no-emotion / EMOTION_ENABLED / --emotion-only）"""

    def settings(self, enabled=True):
        return {
            "llm_temperature": .2, "llm_max_tokens": 100, "llm_reasoning_effort": "none",
            "llm_json_mode": False, "content_head_chars": 10, "content_tail_chars": 5,
            "max_summary_chars": 60, "emotion_enabled": enabled,
            "emotion_labels": list(LABELS), "emotion_fallback": FALLBACK,
            "emotion_label_version": "v1", "emotion_temperature": 0.0, "emotion_max_tokens": 32,
        }

    def args(self, **overrides):
        values = {"no_emotion": False, "emotion_only": False}
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_parser_exposes_emotion_flags(self):
        parser = bs_main.build_parser()
        parsed = parser.parse_args(["--all", "--emotion-only", "--force-emotion"])
        self.assertTrue(parsed.emotion_only and parsed.force_emotion and not parsed.no_emotion)
        self.assertTrue(parser.parse_args(["--all", "--no-emotion"]).no_emotion)

    def test_setup_registers_algorithm_and_enables(self):
        store = SummaryStore.__new__(SummaryStore)
        registered = []
        store.register_algorithm = lambda fp, payload: registered.append((fp, payload))
        settings = self.settings()
        classifier, fingerprint = bs_main.setup_emotion(
            self.args(), settings, FakeClient(), "model", settings, store=store
        )
        self.assertTrue(classifier.enabled)
        self.assertTrue(fingerprint)
        self.assertEqual(classifier.fingerprint, fingerprint)
        self.assertEqual(classifier.labels, list(LABELS))
        self.assertEqual([fp for fp, _ in registered], [fingerprint])
        self.assertEqual(registered[0][1]["labels"], list(LABELS))

    def test_no_emotion_flag_wins(self):
        settings = self.settings()
        classifier, fingerprint = bs_main.setup_emotion(
            self.args(no_emotion=True), settings, FakeClient(), "model", settings
        )
        self.assertFalse(classifier.enabled)
        self.assertEqual(fingerprint, "")

    def test_env_switch_disables_and_emotion_only_forces_back_on(self):
        settings = self.settings(enabled=False)
        disabled, _ = bs_main.setup_emotion(self.args(), settings, FakeClient(), "model", settings)
        self.assertFalse(disabled.enabled)
        forced, fingerprint = bs_main.setup_emotion(
            self.args(emotion_only=True), settings, FakeClient(), "model", settings
        )
        self.assertTrue(forced.enabled)
        self.assertTrue(fingerprint)

    def test_missing_prompt_file_disables_emotion(self):
        settings = self.settings()
        missing = Path(__file__).resolve().parent / "_not_exists_prompt.txt"
        with mock.patch.object(bs_config, "EMOTION_PROMPT_FILE", missing):
            classifier, fingerprint = bs_main.setup_emotion(
                self.args(), settings, FakeClient(), "model", settings
            )
        self.assertFalse(classifier.enabled)
        self.assertEqual(fingerprint, "")


class SafeSnippetTests(unittest.TestCase):
    """日志/终端里不允许落入整句（小模型偶尔会复述日记正文）"""

    def test_short_answer_is_kept_for_diagnosis(self):
        self.assertEqual(emotion_mod.safe_snippet("开心"), "开心")
        self.assertEqual(emotion_mod.safe_snippet("  期待  "), "期待")
        self.assertEqual(emotion_mod.safe_snippet(""), "（空）")
        self.assertEqual(emotion_mod.safe_snippet(None), "（空）")

    def test_sentence_is_replaced_by_length_only(self):
        sentence = "今天天气不错，我去公园散步，心情很好。" * 3
        snippet = emotion_mod.safe_snippet(sentence)
        self.assertNotIn("公园", snippet)
        self.assertIn(f"{len(' '.join(sentence.split()))} 字", snippet)

    def test_classifier_warning_does_not_log_diary_like_text(self):
        classifier = emotion_mod.EmotionClassifier(
            FakeClient(answer="今天被同事甩锅，气得睡不着，真想把这段原文吐出来。"),
            emotion_mod.load_prompt_template(), fingerprint="fp", labels=LABELS, fallback=FALLBACK,
        )
        with self.assertLogs("batch_summary", level="WARNING") as captured:
            outcome = classifier.classify(make_entry())
        self.assertEqual(outcome["emotion"], FALLBACK)
        logged = "\n".join(captured.output)
        self.assertNotIn("甩锅", logged)          # 正文没有进日志
        self.assertIn("内容已省略", logged)


if __name__ == "__main__":
    unittest.main()

