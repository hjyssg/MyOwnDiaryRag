#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时进度：心跳打印 + 进度快照 + 人类可读状态块

设计目标：**程序自己在运行期间持续输出可读进度**，不需要另开终端，
也不需要用 ``ps``/``grep``/``tail`` 之类命令去猜任务状态。

三个东西：

* :func:`build_progress_snapshot` —— 进度快照（纯函数）。同一份数据同时用于
  写 ``progress.json`` 与打印，保证"文件里看到的"和"控制台看到的"完全一致。
* :func:`format_blocks` —— 把快照渲染成带 ``[HH:MM:SS]`` 前缀的中文状态块，
  主程序心跳与 ``status.py`` 看板共用（两处格式永不漂移）。
* :class:`ProgressReporter` —— 带后台心跳线程的进度记录器：

  - 每 ``interval`` 秒打印一次状态块（这就是"心跳"，证明任务还活着）；
  - 同时把最新状态块覆盖写到 ``运行状态.txt``（零命令查看：直接打开文件即可）；
  - 每处理一篇就原子更新 ``progress.json``（供 ``status.py`` 读取）；
  - 所有打印共用一把锁，心跳块不会插进逐篇输出中间；
  - :meth:`ProgressReporter.attach_logger` 把日志（含重试警告）变成"最近日志"行。
"""

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from scripts.batch_summary import config as bs_config

logger = logging.getLogger("scripts.batch_summary")

# 阶段 -> 中文名（让人一眼知道"现在在干什么"）
PHASE_LABELS = {
    "starting": "启动中",
    "loading": "读取日记",
    "calling_model": "调用模型",
    "merging": "汇总生成总结",
    "saving": "保存结果",
    "done": "已完成",
    "running": "运行中",            # 兼容旧版 progress.json 里的 phase 取值
}
BAR_WIDTH = 30
_MIN_INTERVAL = 0.01               # 心跳最小间隔（防止把终端刷爆）
_DIGITS_ONLY = re.compile(r"^[\d,\-、\s]+$")
_STATS_KEYS = ("ok", "empty", "failed", "skipped", "summaries",
               "emotions", "emotion_empty", "emotion_failed", "emotion_skipped")


def phase_label(phase: Optional[str]) -> str:
    """阶段中文名（未知阶段原样返回）"""
    return PHASE_LABELS.get(str(phase or ""), str(phase or "") or "运行中")


def stamp(now=None) -> str:
    """``[HH:MM:SS]`` 前缀"""
    return f"[{(now or datetime.now()):%H:%M:%S}]"


def human_duration(seconds) -> str:
    """秒 -> 人类可读时长（1h02m / 3m05s / 12s）"""
    seconds = max(int(seconds or 0), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def progress_bar(index: int, total: int, width: int = BAR_WIDTH) -> str:
    """文本进度条（total<=0 时为全空）"""
    if total <= 0:
        return "[" + "." * width + "]"
    filled = int(width * min(index, total) / total)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def scope_text(scope: Optional[str]) -> str:
    """范围标签美化：``2025`` -> ``2025 年``，``2015、2016`` -> ``2015、2016 年``"""
    text = str(scope or "").strip()
    if not text:
        return ""
    if _DIGITS_ONLY.match(text):
        return f"{text} 年"
    return text
# ---------------- 进度快照 ----------------

def build_progress_snapshot(
    *,
    phase: str,
    total: int,
    index: int,
    stats: Dict,
    started: float,
    current: Optional[Dict] = None,
    entry_elapsed: Optional[float] = None,
    year_label: str = "",
    phase_note: str = "",
    last_log: str = "",
    days_done: int = 0,
    days_total: int = 0,
    wait_seconds: Optional[float] = None,
) -> Dict:
    """当前进度快照（``progress.json`` 与状态块共用同一份数据）"""
    done = stats["ok"] + stats["empty"] + stats["failed"]
    elapsed = max(time.monotonic() - started, 0.0)
    avg = elapsed / done if done else 0.0
    remaining = max(total - index, 0)
    current_entry = None
    if current:
        current_entry = {
            "entry_id": current.get("id"),
            "date": str(current.get("date") or ""),
            "entry_type": current.get("entry_type"),
            "word_count": current.get("word_count"),
        }
    return {
        "phase": phase,                 # starting/loading/calling_model/merging/saving/done
        "phase_label": phase_label(phase),
        "phase_note": phase_note,
        "scope": year_label,
        "total": total,
        "index": index,
        "processed": done,
        "skipped": stats["skipped"],
        "ok": stats["ok"],
        "empty": stats["empty"],
        "failed": stats["failed"],
        "summaries": stats["summaries"],
        "emotions": int(stats.get("emotions", 0) or 0),
        "emotion_failed": int(stats.get("emotion_failed", 0) or 0),
        "emotion_skipped": int(stats.get("emotion_skipped", 0) or 0),
        "days_done": int(days_done or 0),
        "days_total": int(days_total or 0),
        "elapsed_seconds": round(elapsed, 1),
        "avg_seconds_per_entry": round(avg, 2),
        "last_entry_seconds": round(entry_elapsed, 2) if entry_elapsed else None,
        "eta_seconds": round(avg * remaining, 1),
        "entries_per_hour": round(done / elapsed * 3600, 1) if elapsed > 0 else 0.0,
        "current_entry": current_entry,
        "wait_seconds": round(wait_seconds, 1) if wait_seconds else None,
        "last_log": last_log,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------- 状态块渲染（主程序与 status.py 共用） ----------------

def format_blocks(snapshot: Optional[Dict], *, now=None) -> str:
    """把进度快照渲染成"人类可读状态块"（每行都带 ``[HH:MM:SS]`` 前缀）"""
    snapshot = snapshot or {}
    prefix = stamp(now)
    phase = str(snapshot.get("phase") or "running")
    finished = phase == "done"
    total = int(snapshot.get("total") or 0)
    index = int(snapshot.get("index") or 0)
    days_done = int(snapshot.get("days_done") or 0)
    days_total = int(snapshot.get("days_total") or 0)
    ok = int(snapshot.get("ok") or 0)
    empty = int(snapshot.get("empty") or 0)
    failed = int(snapshot.get("failed") or 0)
    skipped = int(snapshot.get("skipped") or 0)

    scope = scope_text(snapshot.get("scope"))
    lines = [f"{prefix} {scope}日记批量总结任务{'已完成 ✅' if finished else '运行中'}"]

    if total > 0:
        percent = index / total * 100
        if days_total:
            day_part = f" ｜ 覆盖 {days_done} / {days_total} 天"
        elif days_done:
            day_part = f" ｜ 覆盖 {days_done} 天"
        else:
            day_part = ""
        lines.append(f"{prefix} 已处理：{index} / {total} 篇（{percent:.1f}%）{day_part}")
    else:
        lines.append(f"{prefix} 已处理：正在统计总量…")

    phase_text = phase_label(phase)
    if snapshot.get("phase_note"):
        phase_text += f"（{snapshot['phase_note']}）"
    lines.append(f"{prefix} 当前阶段：{phase_text}")

    current = snapshot.get("current_entry")
    if current and not finished:
        text = (
            f"{current.get('date')} {current.get('entry_type')} {current.get('word_count')}字"
        )
        if snapshot.get("wait_seconds"):
            text += f"（已等待 {human_duration(snapshot['wait_seconds'])}）"
        lines.append(f"{prefix} 正在处理：{text}")

    lines.append(f"{prefix} 最近日志：{snapshot.get('last_log') or '（暂无）'}")
    result_line = (
        f"{prefix} 结果：有摘要 {ok} ｜ 空摘要 {empty} ｜ 失败 {failed} ｜ 跳过(断点) {skipped}"
    )
    emotions = int(snapshot.get("emotions") or 0)
    emotion_failed = int(snapshot.get("emotion_failed") or 0)
    if emotions or emotion_failed:
        result_line += f" ｜ 情绪 {emotions}（失败 {emotion_failed}）"
    lines.append(result_line)

    avg = float(snapshot.get("avg_seconds_per_entry") or 0.0)
    rate = float(snapshot.get("entries_per_hour") or 0.0)
    speed_parts = [
        f"{prefix} 速度：{avg:.1f} 秒/篇（{rate:.0f} 条/h）",
        f"已用 {human_duration(snapshot.get('elapsed_seconds'))}",
    ]
    eta = snapshot.get("eta_seconds") or 0
    if not finished and eta:
        finish = (now or datetime.now()) + timedelta(seconds=float(eta))
        speed_parts.append(f"预计剩余约 {human_duration(eta)}（预计 {finish:%H:%M:%S} 完成）")
    lines.append(" ｜ ".join(speed_parts))

    if total > 0:
        lines.append(f"{prefix} 进度：{progress_bar(index, total)} {index / total * 100:.1f}%")

    for key in ("notice", "hint"):
        if snapshot.get(key):
            lines.append(f"{prefix} 提示：{snapshot[key]}")
    return "\n".join(lines)


# ---------------- 落盘 ----------------

def write_text_atomic(path, text: str) -> bool:
    """原子写文本（失败不影响主流程）"""
    if not path:
        return False
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        return True
    except OSError as exc:
        logger.debug("文本写入失败：%s（%s）", path, exc)
        return False


def write_progress_file(path, snapshot: Dict) -> bool:
    """原子写出进度快照（``status.py`` 读它；也可自己打开看）"""
    return write_text_atomic(path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")


# ---------------- 心跳记录器 ----------------

class _LogHandler(logging.Handler):
    """把最近一条日志（含重试警告）喂给状态块的"最近日志"行"""

    MAX_CHARS = 90

    def __init__(self, reporter: "ProgressReporter", level=logging.INFO):
        super().__init__(level)
        self._reporter = reporter

    def emit(self, record):  # logging.Handler 接口
        try:
            text = record.getMessage()
            if record.levelno >= logging.ERROR:
                text = f"[错误] {text}"
            elif record.levelno >= logging.WARNING:
                text = f"[警告] {text}"
            if len(text) > self.MAX_CHARS:
                text = text[: self.MAX_CHARS - 1] + "…"    # 状态块一行别太长
            self._reporter.note(text)
        except Exception:  # 记录日志永远不能影响主流程
            pass


class ProgressReporter:
    """运行期进度记录器：控制台心跳 + ``progress.json`` + ``运行状态.txt``

    典型用法（主程序里）::

        reporter = ProgressReporter(scope="2025 年", interval=30,
                                    progress_file=paths["progress"],
                                    status_file=paths["status"])
        reporter.start()                      # 立刻打一块，之后每 interval 秒再打
        reporter.set_phase("loading", "正在读取日记")
        reporter.set_total(len(entries), days_total=328)
        reporter.update(index, stats=stats, current=entry)
        reporter.set_phase("done")
        reporter.stop()
    """

    def __init__(
        self,
        *,
        scope: str = "",
        total: int = 0,
        days_total: int = 0,
        phase: str = "starting",
        phase_note: str = "",
        interval: Optional[float] = None,
        stream=None,
        enabled: bool = True,
        progress_file=None,
        status_file=None,
    ):
        self._lock = threading.RLock()
        self._stream = stream
        self._interval = max(
            float(interval if interval is not None else bs_config.HEARTBEAT_SECONDS),
            _MIN_INTERVAL,
        )
        self._enabled = bool(enabled)
        self._progress_file = Path(progress_file) if progress_file else None
        self._status_file = Path(status_file) if status_file else None
        self._scope = scope
        self._total = int(total or 0)
        self._days_total = int(days_total or 0)
        self._days_done = set()
        self._phase = phase
        self._phase_note = phase_note
        self._index = 0
        self._stats = {key: 0 for key in _STATS_KEYS}
        self._current = None
        self._current_started = None
        self._last_entry_seconds = None
        self._last_log = ""
        self._started = time.monotonic()
        self._stop_event = threading.Event()
        self._thread = None
        self._log_handler = None
        self._log_logger = None

    # -- 只读属性（测试与 status.py 用） --
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- 状态块 / 快照 --
    def snapshot(self) -> Dict:
        """当前进度快照（与写入 ``progress.json`` 的内容完全一致）"""
        with self._lock:
            wait = None
            if self._current is not None and self._current_started is not None:
                wait = max(time.monotonic() - self._current_started, 0.0)
            return build_progress_snapshot(
                phase=self._phase,
                total=self._total,
                index=self._index,
                stats=self._stats,
                started=self._started,
                current=self._current,
                entry_elapsed=self._last_entry_seconds,
                year_label=self._scope,
                phase_note=self._phase_note,
                last_log=self._last_log,
                days_done=len(self._days_done),
                days_total=self._days_total,
                wait_seconds=wait,
            )

    def text(self, *, now=None) -> str:
        """当前状态块文本"""
        return format_blocks(self.snapshot(), now=now)

    def print_block(self):
        """立刻打印一块状态（``enabled=False``/``--quiet`` 时不打印）"""
        if not self._enabled:
            return
        with self._lock:
            self._write(format_blocks(self.snapshot()))

    # -- 主线程更新接口 --
    def set_phase(self, phase: str, note: str = ""):
        """切换阶段（有变化时立刻补打一块，让人马上看到"进入下一步了"）"""
        with self._lock:
            changed = (phase != self._phase) or ((note or "") != self._phase_note)
            self._phase = phase
            self._phase_note = note or ""
            self._write_files()
            if changed:
                self.print_block()

    def set_total(self, total: int, days_total: Optional[int] = None):
        """设置总篇数（可选总天数）"""
        with self._lock:
            self._total = max(int(total or 0), 0)
            if days_total is not None:
                self._days_total = max(int(days_total or 0), 0)
            self._write_files()

    def update(
        self,
        index: Optional[int] = None,
        *,
        stats: Optional[Dict] = None,
        current: Optional[Dict] = None,
        entry_elapsed: Optional[float] = None,
        note: Optional[str] = None,
    ):
        """记录"处理到第几篇/这一篇是谁/累计结果"，并刷新落盘文件"""
        with self._lock:
            if index is not None:
                self._index = int(index)
            if stats:
                for key in _STATS_KEYS:
                    if key in stats:
                        self._stats[key] = int(stats[key] or 0)
            if current is not None:
                self._current = current
                self._current_started = time.monotonic()
                date_text = str(current.get("date") or "")
                if date_text:
                    self._days_done.add(date_text)      # 覆盖天数按日期去重
            if entry_elapsed is not None:
                self._last_entry_seconds = entry_elapsed
            if note:
                self._last_log = str(note)
            self._write_files()

    def note(self, text: str):
        """更新"最近日志"这一行"""
        with self._lock:
            self._last_log = str(text or "").strip()
            self._write_files()

    def clear_current(self):
        """清掉"正在处理"信息（收尾时用，避免状态块显示过期条目）"""
        with self._lock:
            self._current = None
            self._current_started = None
            self._last_entry_seconds = None
            self._write_files()

    def emit(self, text: str):
        """线程安全打印一行普通进度（与心跳块共用锁，不会互相插行）"""
        if not self._enabled:
            return
        with self._lock:
            self._write(str(text))
# -- 日志钩子 --
    def attach_logger(self, target_logger, level=logging.INFO):
        """把日志接到"最近日志"行；返回 handler（便于测试）"""
        handler = _LogHandler(self, level)
        target_logger.addHandler(handler)
        self._log_handler = handler
        self._log_logger = target_logger
        return handler

    def detach_logger(self):
        """摘掉日志钩子（``stop()`` 会自动调用）"""
        if self._log_handler is not None and self._log_logger is not None:
            self._log_logger.removeHandler(self._log_handler)
        self._log_handler = None
        self._log_logger = None

    # -- 心跳线程 --
    def start(self):
        """启动后台心跳并立刻打一块（``enabled=False`` 时什么都不做）"""
        with self._lock:
            if not self._enabled or self.running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop, name="batch-summary-heartbeat", daemon=True
            )
            self._thread.start()
            self.print_block()

    def stop(self, timeout: float = 2.0):
        """停止心跳（立即返回，不留后台线程）"""
        with self._lock:
            self._stop_event.set()
            thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self.detach_logger()

    # -- 内部 --
    def _loop(self):
        while not self._stop_event.wait(self._interval):
            self.print_block()

    def _write_files(self) -> Dict:
        """刷新 ``progress.json`` 与 ``运行状态.txt``（同一份快照）"""
        snapshot = self.snapshot()
        if self._progress_file:
            write_progress_file(self._progress_file, snapshot)
        if self._status_file:
            write_text_atomic(self._status_file, format_blocks(snapshot) + "\n")
        return snapshot

    def _write(self, text: str):
        stream = self._stream if self._stream is not None else sys.stdout
        try:
            print(text, file=stream, flush=True)
        except OSError:
            pass


__all__: List[str] = [
    "PHASE_LABELS",
    "ProgressReporter",
    "build_progress_snapshot",
    "format_blocks",
    "human_duration",
    "phase_label",
    "progress_bar",
    "scope_text",
    "write_progress_file",
    "write_text_atomic",
]