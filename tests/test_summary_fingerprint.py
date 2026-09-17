import unittest

from summary_fingerprint import *


class FingerprintTests(unittest.TestCase):
    def settings(self):
        return {"llm_temperature": .2, "llm_max_tokens": 100, "llm_reasoning_effort": "none",
                "llm_json_mode": False, "content_head_chars": 10, "content_tail_chars": 5,
                "max_summary_chars": 60, "llm_timeout": 1, "heartbeat_seconds": 2}

    def test_stable_keys_and_hashes(self):
        entry = {"id": 1, "date": "2024-09-17", "entry_type": "note"}
        self.assertEqual(entry_key(entry), "v1:2024-09-17:note")
        self.assertEqual(entry_key(entry), entry_key(entry | {"id": 99}))
        self.assertNotEqual(source_hash("a"), source_hash("a "))

    def test_algorithm_covers_semantic_settings_only(self):
        one = algorithm_payload(self.settings(), "m", "prompt")
        reordered = dict(reversed(list(one.items())))
        self.assertEqual(algorithm_fingerprint(one), algorithm_fingerprint(reordered))
        for key in ("temperature", "max_tokens", "reasoning_effort", "json_mode",
                    "content_head_chars", "content_tail_chars", "max_summary_chars"):
            changed = dict(one); changed[key] = str(changed[key]) + "x"
            self.assertNotEqual(algorithm_fingerprint(one), algorithm_fingerprint(changed))
        changed_settings = self.settings() | {"llm_timeout": 999, "heartbeat_seconds": 999}
        self.assertEqual(one, algorithm_payload(changed_settings, "m", "prompt"))

    def test_cache_key_changes_for_each_component(self):
        base = cache_key("e", "s", "a")
        self.assertNotEqual(base, cache_key("x", "s", "a"))
        self.assertNotEqual(base, cache_key("e", "x", "a"))
        self.assertNotEqual(base, cache_key("e", "s", "x"))