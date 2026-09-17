import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.batch_summary import config as bs_config
from scripts.batch_summary import main as batch
from scripts.batch_summary import render
from summary_database import SummaryRepository, SummaryStore
from summary_fingerprint import algorithm_fingerprint, algorithm_payload, emotion_payload


class Client:
    def __init__(self, fail=False): self.call_count=0; self.fail=fail
    def chat(self, _prompt, **_overrides):
        self.call_count += 1
        if self.fail:
            from scripts.batch_summary.llm import LLMError
            raise LLMError("失败")
        return "整理工作并和朋友吃饭。"


class DatabasePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True);self.path=Path(self.tmp.name)/"d.db"
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
        state=batch.SummaryView()
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

    def test_blank_model_answer_is_marked_empty(self):
        """模型回"无"不能被当成摘要（旧版正是这里产生了假事件）"""
        class BlankClient(Client):
            def chat(self, _prompt, **_overrides):
                self.call_count += 1
                return "无"

        self.execute_pipeline(BlankClient(), fp=self.fp())
        records = SummaryRepository(self.path).all_records()
        self.assertEqual((records[0]["status"], records[0]["summary"]), ("empty", ""))

    def test_changed_entry_id_reuses_and_join_returns_new_id(self):
        fp=self.fp();self.execute_pipeline(Client(),fp=fp)
        with sqlite3.connect(self.path) as c:c.execute("UPDATE diary_entries SET id=99 WHERE id=1")
        entry=self.entry|{"id":99};client=Client();self.execute_pipeline(client,entry,fp)
        self.assertEqual(client.call_count,0);self.assertEqual(SummaryRepository(self.path).for_entry(99)["entry_id"],99)


# ---------------- 情绪：第二次调用 + 独立缓存通道 ----------------

_EMOTION_TEMPLATE = None


def emotion_template():
    global _EMOTION_TEMPLATE
    if _EMOTION_TEMPLATE is None:
        from scripts.batch_summary import emotion as emotion_mod
        _EMOTION_TEMPLATE = emotion_mod.load_prompt_template()
    return _EMOTION_TEMPLATE


class EmotionClient:
    """摘要 Prompt 回一段摘要、情绪 Prompt 回一个标签；fail_kind 指定哪一类失败"""

    def __init__(self, label="生气", fail_kind=None):
        self.label = label
        self.fail_kind = fail_kind
        self.call_count = 0
        self.kinds = []

    def chat(self, prompt, **_overrides):
        kind = "emotion" if "标签" in prompt[:400] else "summary"
        self.kinds.append(kind)
        self.call_count += 1
        if self.fail_kind == kind:
            from scripts.batch_summary.llm import LLMError
            raise LLMError(f"模拟{kind}失败")
        return self.label if kind == "emotion" else "整理工作并和朋友吃饭。"


class EmotionPipelineTests(unittest.TestCase):
    """摘要与情绪两条缓存通道互不干扰（情绪需要 store 才启用）"""

    def setUp(self):
        # Windows 上 SQLite 连接释放有延迟，忽略临时目录清理失败（与其它测试的环境问题同源）
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / "d.db"
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE diary_entries (id INTEGER PRIMARY KEY,date TEXT,year INT,month INT,"
                "day INT,content TEXT,file_source TEXT,entry_type TEXT,word_count INT,"
                "UNIQUE(date,entry_type))"
            )
            connection.executemany(
                "INSERT INTO diary_entries VALUES(?,?,?,?,?,?,?,?,?)",
                [(1, "2024-09-17", 2024, 9, 17, "今天被同事甩锅，气得睡不着。", None, "note", 20),
                 (2, "2024-09-18", 2024, 9, 18, "上班、开会、买菜，和平时一样。", None, "note", 16)],
            )
        self.store = SummaryStore(self.path)
        self.store.migrate()
        self.settings = {
            "llm_temperature": .2, "llm_max_tokens": 10, "llm_reasoning_effort": "",
            "llm_json_mode": False, "content_head_chars": 100, "content_tail_chars": 50,
            "max_summary_chars": 60, "emotion_labels": list(bs_config.EMOTION_LABELS),
            "emotion_fallback": bs_config.EMOTION_FALLBACK,
            "emotion_label_version": bs_config.EMOTION_LABEL_VERSION,
            "emotion_temperature": 0.0, "emotion_max_tokens": 32,
        }
        self.entries = [
            {"id": 1, "date": "2024-09-17", "year": 2024, "month": 9, "day": 17,
             "content": "今天被同事甩锅，气得睡不着。", "entry_type": "note", "word_count": 20},
            {"id": 2, "date": "2024-09-18", "year": 2024, "month": 9, "day": 18,
             "content": "上班、开会、买菜，和平时一样。", "entry_type": "note", "word_count": 16},
        ]

    def tearDown(self):
        self.store = None
        self.tmp.cleanup()

    def fingerprints(self):
        payload = algorithm_payload(self.settings, "model", "prompt")
        summary_fp = algorithm_fingerprint(payload)
        self.store.register_algorithm(summary_fp, payload)
        emotion_alg = emotion_payload(self.settings, "model", emotion_template())
        emotion_fp = algorithm_fingerprint(emotion_alg)
        self.store.register_algorithm(emotion_fp, emotion_alg)
        return summary_fp, emotion_fp

    def classifier(self, client, emotion_fp, enabled=True):
        from scripts.batch_summary import emotion as emotion_mod
        return emotion_mod.EmotionClassifier(
            client, emotion_template(), fingerprint=emotion_fp, max_tokens=32, enabled=enabled,
        )

    def execute(self, client, *, classifier=None, entries=None, **kwargs):
        summary_fp, _ = self.fingerprints()
        state = batch.SummaryView()
        return batch.process_entries(
            entries or self.entries, client, state, "{CONTENT}", "legacy", quiet=True,
            progress=lambda _: None, store=self.store, algorithm_fingerprint_value=summary_fp,
            emotion_classifier=classifier, **kwargs,
        )

    def test_emotion_runs_after_summary_and_is_persisted(self):
        _, emotion_fp = self.fingerprints()
        client = EmotionClient(label="生气")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp))
        self.assertEqual(stats["calls"], 4)                    # 2 摘要 + 2 情绪
        self.assertEqual((stats["ok"], stats["emotions"]), (2, 2))
        self.assertEqual(self.emotions(),
                         {"2024-09-17": ("生气", "ok"), "2024-09-18": ("生气", "ok")})

    def test_second_run_reuses_both_channels(self):
        _, emotion_fp = self.fingerprints()
        first = EmotionClient()
        self.execute(first, classifier=self.classifier(first, emotion_fp))
        second = EmotionClient()
        stats = self.execute(second, classifier=self.classifier(second, emotion_fp))
        self.assertEqual(second.call_count, 0)
        self.assertEqual((stats["skipped"], stats["emotion_skipped"]), (2, 2))

    def test_missing_emotion_is_backfilled_without_summary_call(self):
        _, emotion_fp = self.fingerprints()
        first = EmotionClient()
        self.execute(first, classifier=self.classifier(first, emotion_fp))
        with closing(sqlite3.connect(self.path)) as connection, connection:   # 只有摘要没有情绪
            connection.execute("UPDATE entry_summaries SET emotion='', emotion_status=NULL, "
                               "emotion_cache_key=NULL, emotion_algorithm_fingerprint=NULL")
        client = EmotionClient(label="悲伤")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp))
        self.assertEqual((client.call_count, client.kinds), (2, ["emotion", "emotion"]))
        self.assertEqual(stats["emotions"], 2)
        self.assertEqual(self.emotions()["2024-09-17"][0], "悲伤")

    def test_emotion_only_reuses_summaries(self):
        _, emotion_fp = self.fingerprints()
        first = EmotionClient()
        self.execute(first, classifier=self.classifier(first, emotion_fp))
        before = {row["entry_date"]: row["summary"]
                  for row in SummaryRepository(self.path).all_records()}
        client = EmotionClient(label="平淡")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp),
                         emotion_only=True, force_emotion=True)
        self.assertEqual((client.call_count, client.kinds), (2, ["emotion", "emotion"]))
        self.assertEqual(stats["emotions"], 2)
        after = {row["entry_date"]: row["summary"]
                 for row in SummaryRepository(self.path).all_records()}
        self.assertEqual(before, after)

    def test_force_emotion_recomputes_but_force_still_skips_summary(self):
        _, emotion_fp = self.fingerprints()
        first = EmotionClient()
        self.execute(first, classifier=self.classifier(first, emotion_fp))
        client = EmotionClient(label="疲惫")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp), force_emotion=True)
        self.assertEqual((client.call_count, client.kinds), (2, ["emotion", "emotion"]))
        self.assertEqual(self.emotions()["2024-09-17"][0], "疲惫")
        self.assertEqual(stats["emotions"], 2)

    def test_emotion_failure_keeps_summary(self):
        _, emotion_fp = self.fingerprints()
        client = EmotionClient(fail_kind="emotion")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp))
        self.assertEqual((stats["ok"], stats["failed"]), (2, 0))
        self.assertEqual((stats["emotions"], stats["emotion_failed"]), (0, 2))
        self.assertEqual(self.emotions(),
                         {"2024-09-17": ("", "failed"), "2024-09-18": ("", "failed")})

    def test_summary_failure_skips_emotion_call(self):
        _, emotion_fp = self.fingerprints()
        client = EmotionClient(fail_kind="summary")
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp))
        self.assertEqual(client.kinds, ["summary", "summary"])
        self.assertEqual(stats["failed"], 2)
        self.assertEqual(stats["emotions"], 0)
        self.assertEqual(self.emotions()["2024-09-17"][1], "missing")

    def test_empty_content_records_emotion_empty_without_call(self):
        _, emotion_fp = self.fingerprints()
        blank = [dict(self.entries[0], content="   ")]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE diary_entries SET content='   ' WHERE id=1")
        client = EmotionClient()
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp), entries=blank)
        self.assertEqual(client.call_count, 0)
        self.assertEqual((stats["empty"], stats["emotion_empty"]), (1, 1))
        self.assertEqual(self.emotions()["2024-09-17"], ("", "empty"))
        again = EmotionClient()
        stats = self.execute(again, classifier=self.classifier(again, emotion_fp), entries=blank)
        self.assertEqual((again.call_count, stats["skipped"]), (0, 1))

    def test_disabled_classifier_skips_emotion_entirely(self):
        _, emotion_fp = self.fingerprints()
        client = EmotionClient()
        stats = self.execute(client, classifier=self.classifier(client, emotion_fp, enabled=False))
        self.assertEqual((client.call_count, stats["emotions"]), (2, 0))
        self.assertEqual(self.emotions()["2024-09-17"][1], "missing")

    def test_markdown_and_preview_carry_emotion_labels(self):
        """DB 记录（status=ok）渲染出的每行带【标签】，预览重排指纹能感知情绪变化"""
        _, emotion_fp = self.fingerprints()
        client = EmotionClient(label="生气")
        self.execute(client, classifier=self.classifier(client, emotion_fp))

        records = SummaryRepository(self.path).all_records()
        self.assertIn("- 0917【生气】整理工作并和朋友吃饭。", render.render_sections(records))
        self.assertIn("- 0917【生气】整理工作并和朋友吃饭。", render.render_markdown(records))

        view = batch.SummaryView(records)
        self.assertEqual(view.emotion_count(), 2)
        self.assertEqual(batch.body_signature(view), (2, 2))
        # 情绪被清掉后指纹变化：--emotion-only 补情绪时中途预览才会重排
        view.put(1, dict(view.get(1), emotion="", emotion_status="missing"))
        self.assertEqual(batch.body_signature(view), (2, 1))

    def emotions(self):
        return {row["entry_date"]: (row["emotion"], row["emotion_status"])
                for row in SummaryRepository(self.path).all_records()}
