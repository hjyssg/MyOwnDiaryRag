import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.batch_summary import main as batch
from scripts.batch_summary.state import SummaryState
from summary_database import SummaryRepository, SummaryStore
from summary_fingerprint import algorithm_fingerprint, algorithm_payload


class Client:
    def __init__(self, fail=False): self.call_count=0; self.fail=fail
    def chat(self, _prompt):
        self.call_count += 1
        if self.fail:
            from scripts.batch_summary.llm import LLMError
            raise LLMError("失败")
        return "整理工作并和朋友吃饭。"


class DatabasePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/"d.db"
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE diary_entries (id INTEGER PRIMARY KEY,date TEXT,year INT,month INT,day INT,content TEXT,file_source TEXT,entry_type TEXT,word_count INT,UNIQUE(date,entry_type))")
            c.execute("INSERT INTO diary_entries VALUES(1,'2024-09-17',2024,9,17,'正文',NULL,'note',2)")
        self.store=SummaryStore(self.path);self.store.migrate()
        self.entry={"id":1,"date":"2024-09-17","year":2024,"month":9,"day":17,"content":"正文","entry_type":"note","word_count":2}
        self.settings={"llm_temperature":.2,"llm_max_tokens":10,"llm_reasoning_effort":"","llm_json_mode":False,"content_head_chars":10,"content_tail_chars":5,"max_summary_chars":60}

    def tearDown(self): self.tmp.cleanup()
    def fp(self,prompt="p"):
        payload=algorithm_payload(self.settings,"model",prompt);value=algorithm_fingerprint(payload);self.store.register_algorithm(value,payload);return value
    def execute_pipeline(self,client,entry=None,fp=None,force=False):
        state=SummaryState(path=Path(self.tmp.name)/"unused.json")
        return batch.process_entries([entry or self.entry],client,state,"{CONTENT}","legacy",quiet=True,progress=lambda _:None,store=self.store,algorithm_fingerprint_value=fp or self.fp(),force=force)

    def test_same_input_reuses_without_model_call(self):
        first=Client();fp=self.fp();self.execute_pipeline(first,fp=fp);second=Client();stats=self.execute_pipeline(second,fp=fp)
        self.assertEqual(first.call_count,1);self.assertEqual(second.call_count,0);self.assertEqual(stats["skipped"],1)

    def test_content_and_algorithm_changes_regenerate(self):
        fp=self.fp();self.execute_pipeline(Client(),fp=fp)
        changed=self.entry|{"content":"正文变化"};client=Client();self.execute_pipeline(client,changed,fp);self.assertEqual(client.call_count,1)
        client=Client();self.execute_pipeline(client,changed,self.fp("new prompt"));self.assertEqual(client.call_count,1)

    def test_failed_retries_and_force_bypasses_cache(self):
        fp=self.fp();self.execute_pipeline(Client(fail=True),fp=fp);retry=Client();self.execute_pipeline(retry,fp=fp);self.assertEqual(retry.call_count,1)
        forced=Client();self.execute_pipeline(forced,fp=fp,force=True);self.assertEqual(forced.call_count,1)

    def test_changed_entry_id_reuses_and_join_returns_new_id(self):
        fp=self.fp();self.execute_pipeline(Client(),fp=fp)
        with sqlite3.connect(self.path) as c:c.execute("UPDATE diary_entries SET id=99 WHERE id=1")
        entry=self.entry|{"id":99};client=Client();self.execute_pipeline(client,entry,fp)
        self.assertEqual(client.call_count,0);self.assertEqual(SummaryRepository(self.path).for_entry(99)["entry_id"],99)