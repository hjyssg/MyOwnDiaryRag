#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""断点续跑状态与日志

* 状态文件 ``output/summary_state.json``：记录每篇日记的处理结果
  （内容哈希 + 摘要 + 状态），已成功处理且内容未变的条目不再调用模型；
* 原子写入：先写 ``*.tmp`` 再 ``os.replace``，中断不会损坏状态文件；
* 日志：同时输出到控制台与 ``output/batch_summary.log``。

与旧版（年度日记回顾）的区别：``results[id]`` 里的 ``events`` 列表换成了
``summary`` 字符串，``STATE_VERSION`` 升到 2；旧状态文件不会被复用（任务变了）。
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.batch_summary import config as bs_config

STATE_VERSION = 2
LOGGER_NAME = "scripts.batch_summary"


def content_hash(text: str) -> str:
    """正文指纹（用于判断日记内容是否变化）"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def has_summary(record: Dict) -> bool:
    """记录里是否有可用摘要"""
    return bool(str((record or {}).get("summary") or "").strip())


class SummaryState:
    """处理结果 + 断点状态"""

    def __init__(
        self,
        path: Optional[Path] = None,
        prompt_sha1: str = "",
        model: str = "",
        entry_types=None,
    ):
        self.path = Path(path) if path else bs_config.STATE_FILE
        self.prompt_sha1 = prompt_sha1
        self.model = model
        self.entry_types = list(entry_types or [])
        self.results: Dict[str, dict] = {}
        self.created_at = now_iso()
        self._dirty = 0
        self.loaded_from_disk = False

    # ---------------- 读写 ----------------

    def load(self) -> "SummaryState":
        """读取状态文件；文件不存在或损坏时从零开始（不会中断任务）"""
        if not self.path.exists():
            return self
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logging.getLogger(LOGGER_NAME).warning(
                "状态文件无法读取，将从零开始：%s（%s）", self.path, exc
            )
            return self
        if int(payload.get("version") or 0) != STATE_VERSION:
            logging.getLogger(LOGGER_NAME).warning(
                "状态文件版本不是 %d（旧版年度回顾的结果），将从零开始：%s",
                STATE_VERSION, self.path,
            )
            return self
        self.results = {str(k): v for k, v in (payload.get("results") or {}).items()}
        self.created_at = payload.get("created_at") or self.created_at
        self.loaded_from_disk = True
        return self

    def save(self, force: bool = False) -> bool:
        """原子写入状态文件"""
        if not force and self._dirty == 0 and self.loaded_from_disk:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(self.to_payload(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, self.path)
        self._dirty = 0
        self.loaded_from_disk = True
        return True

    def save_if_needed(self, every: Optional[int] = None) -> bool:
        step = int(every or bs_config.STATE_SAVE_EVERY)
        if self._dirty >= max(1, step):
            return self.save(force=True)
        return False

    # ---------------- 条目访问 ----------------

    def get(self, entry_id) -> Optional[dict]:
        return self.results.get(str(entry_id))

    def put(self, entry_id, record: Dict):
        self.results[str(entry_id)] = record
        self._dirty += 1

    def should_skip(self, entry_id, content_hash_value: str, force: bool = False) -> Tuple[bool, str]:
        """判断某篇是否可以跳过（不调用模型）"""
        if force:
            return False, "force"
        record = self.get(entry_id)
        if not record:
            return False, "no-record"
        if record.get("status") not in ("ok", "empty"):
            return False, f"previous-{record.get('status')}"
        if record.get("content_hash") != content_hash_value:
            return False, "content-changed"
        if self.prompt_sha1 and record.get("prompt_sha1") and record["prompt_sha1"] != self.prompt_sha1:
            return False, "prompt-changed"
        return True, "done"

    def stats(self) -> Dict[str, int]:
        counts = {"ok": 0, "empty": 0, "failed": 0}
        for record in self.results.values():
            status = record.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def summary_count(self) -> int:
        """已产出摘要的条目数（中途预览用它判断"有没有新内容"）"""
        return sum(1 for record in self.results.values() if has_summary(record))

    def summary_records(self) -> List[Dict]:
        """所有条目的摘要记录（带 entry_* 元信息），按 (日期, id) 升序"""
        records: List[Dict] = []
        for record in sorted(
            self.results.values(),
            key=lambda r: (str(r.get("entry_date") or ""), int(r.get("entry_id") or 0)),
        ):
            summary = str(record.get("summary") or "").strip()
            if not summary:
                continue
            records.append({
                "entry_id": record.get("entry_id"),
                "entry_date": str(record.get("entry_date") or ""),
                "entry_type": record.get("entry_type"),
                "word_count": record.get("word_count"),
                "summary": summary,
            })
        return records

    def to_payload(self) -> Dict:
        return {
            "version": STATE_VERSION,
            "created_at": self.created_at,
            "updated_at": now_iso(),
            "model": self.model,
            "prompt_sha1": self.prompt_sha1,
            "entry_types": self.entry_types,
            "stats": self.stats(),
            "results": self.results,
        }


# ---------------- 日志 ----------------

def setup_logging(log_file: Optional[Path] = None, quiet: bool = False, level=logging.INFO) -> Path:
    """配置日志（文件 + 控制台），返回日志文件路径"""
    target = Path(log_file) if log_file else bs_config.LOG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(target, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if not quiet:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
    return target
