import sqlite3
import tempfile
import unittest
from pathlib import Path

from summary_database import SummaryRepository, SummaryStore
from summary_fingerprint import algorithm_fingerprint, algorithm_payload, cache_key, entry_key, source_hash


class SummaryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path = Path(self.tmp.name) / "d.db"
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE diary_entries (id INTEGER PRIMARY KEY, date TEXT, year INT, month INT, day INT, content TEXT, file_source TEXT, entry_type TEXT, word_count INT, UNIQUE(date, entry_type))")
            c.execute("INSERT INTO diary_entries VALUES (1,'2024-09-17',2024,9,17,'正文',NULL,'note',2)")
        self.store = SummaryStore(self.path); self.store.migrate()
        settings = {"llm_temperature":.2,"llm_max_tokens":10,"llm_reasoning_effort":"","llm_json_mode":False,"content_head_chars":10,"content_tail_chars":5,"max_summary_chars":60}
        self.payload = algorithm_payload(settings, "model", "prompt")
        self.fp = algorithm_fingerprint(self.payload); self.store.register_algorithm(self.fp, self.payload)
        self.entry = {"date":"2024-09-17","year":2024,"month":9,"day":17,"entry_type":"note","word_count":2}

    def tearDown(self): self.tmp.cleanup()

    def test_migration_is_idempotent_and_upsert_is_cacheable(self):
        self.store.migrate(); key=entry_key(self.entry); sh=source_hash("正文"); ck=cache_key(key,sh,self.fp)
        self.store.upsert(self.entry, entry_key=key, source_hash_value=sh, algorithm_fingerprint=self.fp, cache_key=ck, status="ok", summary="摘要")
        self.assertTrue(self.store.is_cache_hit(key, ck))
        item=SummaryRepository(self.path).for_entry(1)
        self.assertEqual((item["status"], item["summary"], item["model"]), ("ok","摘要","model"))

    def test_failed_is_not_hit_and_source_change_is_stale(self):
        key=entry_key(self.entry); sh=source_hash("正文"); ck=cache_key(key,sh,self.fp)
        self.store.upsert(self.entry, entry_key=key, source_hash_value=sh, algorithm_fingerprint=self.fp, cache_key=ck, status="failed", error="x")
        self.assertFalse(self.store.is_cache_hit(key, ck))
        with sqlite3.connect(self.path) as c: c.execute("UPDATE diary_entries SET content='变化' WHERE id=1")
        self.assertEqual(SummaryRepository(self.path).for_entry(1)["status"], "stale")

    def test_missing_tables_degrade(self):
        other=Path(self.tmp.name)/"plain.db"
        with sqlite3.connect(other) as c:
            c.execute("CREATE TABLE diary_entries (id INTEGER PRIMARY KEY,date TEXT,entry_type TEXT)")
            c.execute("INSERT INTO diary_entries VALUES(1,'2024-01-01','note')")
        repo=SummaryRepository(other)
        self.assertEqual(repo.list(), ([],0)); self.assertEqual(repo.for_entry(1)["status"], "missing")

    def test_new_algorithm_run_marks_matching_scope_stale(self):
        key=entry_key(self.entry);sh=source_hash("正文");ck=cache_key(key,sh,self.fp)
        self.store.upsert(self.entry, entry_key=key, source_hash_value=sh,
                          algorithm_fingerprint=self.fp, cache_key=ck,
                          status="ok", summary="旧摘要")
        new_payload=self.payload|{"model":"new-model"};new_fp=algorithm_fingerprint(new_payload)
        self.store.register_algorithm(new_fp,new_payload)
        self.store.start_run(new_fp,{"years":[2024],"entry_types":["note"]},1)
        item=SummaryRepository(self.path).for_entry(1)
        self.assertEqual(item["status"],"stale");self.assertEqual(item["summary"],"")