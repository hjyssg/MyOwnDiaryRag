#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 入口脚本

用本地 LM Studio 模型逐篇阅读 SQLite 中的日记，为**每一篇**写一段摘要，
生成按年份排列的 Markdown 目录。全程本地运行，数据库只读，原始日记不修改。

本功能刻意不让本地模型做判断：模型只负责"把这篇日记写成一段摘要"，
既不筛"重要/不重要"，也不负责日期或标题——因此每一篇都会产出摘要。

常用命令：

    python scripts/batch_summary/main.py --models             # 确认 LM Studio 实际模型名
    python scripts/batch_summary/main.py --test --samples 10  # 抽样试跑（不写状态/输出文件）
    python scripts/batch_summary/main.py --all                # 全量（可 Ctrl+C，重跑自动续跑）
    python scripts/batch_summary/main.py --years 2015-2019    # 分年跑
    python scripts/batch_summary/main.py --rebuild-md         # 不调模型，用已有摘要重出 Markdown

产物（每次运行放在 scripts/batch_summary/output/YYMMDDHHMMSS/ 子目录里，历史互不覆盖）：

    日记总结.md           最终目录：每篇日记一行摘要（整轮跑完才写）
    中途预览.md           运行期间的"截至当前"目录（默认每 60 秒刷新，随时可打开）
    summaries.json        结构化中间结果（每篇一条摘要记录）
    progress.json         实时进度快照（status.py 读它）
    运行状态.txt          最新状态块（双击即可查看，不需要任何命令）
    待复核_未产出摘要.*   调用失败或模型给出空答案的日记原文清单
    batch_summary.log     处理日志

断点续跑状态固定在 scripts/batch_summary/output/summary_state.json（跨运行共享，重跑即续跑）。

运行期间终端会**自己**持续打印人类可读进度（默认每 30 秒一块，可 --heartbeat 调整）：
不需要另开终端看进度，也不需要用 ps/grep/tail 之类的命令去猜任务状态。
"""

import argparse
import io
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# 项目根目录加入 sys.path（保证 `python scripts/batch_summary/main.py` 也能绝对导入包）
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.batch_summary import config as bs_config  # noqa: E402
from scripts.batch_summary import (  # noqa: E402
    dal,
    progress as progress_mod,
    render,
    state as state_mod,
    summary,
)
from scripts.batch_summary.llm import (  # noqa: E402
    LLMClient,
    LLMError,
    list_models,
    pick_chat_model,
)

logger = logging.getLogger("scripts.batch_summary")

EXIT_OK, EXIT_ERROR, EXIT_NO_MODEL = 0, 1, 2


def fix_windows_console():
    """Windows 控制台 UTF-8 输出修复（与项目其它脚本保持一致）"""
    if sys.platform != "win32":
        return
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        if isinstance(stream, io.TextIOWrapper) and (stream.encoding or "").lower() == "utf-8":
            continue
        setattr(
            sys,
            stream_name,
            io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/batch_summary/main.py",
        description="日记批量总结：用本地 LLM 为 SQLite 里的每一篇日记写一段摘要，生成按年份排列的目录。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--models", action="store_true", help="列出 LM Studio 可见模型后退出（确认模型名）")
    mode.add_argument("--test", action="store_true", help="抽样试跑，只打印结果，不写状态与输出文件")
    mode.add_argument("--all", action="store_true", help="全量生成（可中断续跑）")
    mode.add_argument("--rebuild-md", action="store_true", help="不调用模型，仅用已有摘要重出 Markdown")

    parser.add_argument("--samples", type=int, default=10, help="--test 抽样条数（默认 10）")
    parser.add_argument("--year", type=int, help="只处理某一年，如 --year 2015")
    parser.add_argument("--years", help="年份范围或列表，如 2015-2019 或 2015,2017")
    parser.add_argument(
        "--types",
        help="限定条目类型，逗号分隔（默认：%s）" % ",".join(bs_config.DEFAULT_ENTRY_TYPES),
    )
    parser.add_argument("--include-stock", action="store_true", help="把 stock_diary（620 条日常炒股流水）也纳入总结")
    parser.add_argument("--limit", type=int, help="最多处理多少条（调试用）")
    parser.add_argument("--force", action="store_true", help="忽略断点状态，全部重新总结")
    parser.add_argument(
        "--output-dir",
        help="输出根目录（默认 scripts/batch_summary/output）；产物放在其下的 YYMMDDHHMMSS 子目录里",
    )
    parser.add_argument(
        "--flat-output",
        action="store_true",
        help="不建时间戳子目录，直接把产物写到输出根目录（旧行为）",
    )
    parser.add_argument(
        "--heartbeat",
        type=float,
        metavar="SECONDS",
        help="运行期间每隔多少秒打印一次状态块（默认 %d 秒，最小 %d 秒）"
             % (bs_config.HEARTBEAT_SECONDS, bs_config.HEARTBEAT_MIN_SECONDS),
    )
    parser.add_argument(
        "--no-heartbeat",
        action="store_true",
        help="关闭运行期状态块（只保留每篇一行输出）",
    )
    parser.add_argument(
        "--preview-every",
        type=float,
        metavar="SECONDS",
        help="运行期间每隔多少秒刷新一次「中途预览.md」（默认 %d 秒；0 = 关闭）"
             % bs_config.PREVIEW_EVERY_SECONDS,
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="不生成运行期的「中途预览.md」（只保留跑完后的最终产物）",
    )
    parser.add_argument("--base-url", help="覆盖 LM Studio 地址（仍强制本机地址）")
    parser.add_argument("--model", help="覆盖模型名（默认读取 .env 的 LLM_MODEL，留空则自动发现）")
    parser.add_argument(
        "--reasoning-effort",
        help="覆盖思考强度：none=关闭思考（推理模型推荐，快很多）/low/medium/high；"
             "留空=不发送该参数（默认读 .env 的 LLM_REASONING_EFFORT）",
    )
    parser.add_argument("--quiet", action="store_true", help="减少控制台输出（日志仍写入文件）")
    return parser


def build_run_paths(base_dir: Path, run_dir: Path) -> Dict[str, Path]:
    """本次运行的产物路径

    结果类文件放 ``run_dir``（每次运行一个 YYMMDDHHMMSS 子目录，历史互不覆盖）；
    断点续跑状态放 ``base_dir``（跨运行共享，重跑才能续跑）。
    """
    return {
        "base_dir": base_dir,
        "dir": run_dir,
        "state": base_dir / bs_config.STATE_FILE_NAME,
        "summaries": run_dir / bs_config.SUMMARIES_FILE_NAME,    # 结构化中间结果
        "markdown": run_dir / bs_config.MARKDOWN_FILE_NAME,      # 最终产物：日记总结.md
        "log": run_dir / bs_config.LOG_FILE_NAME,
        "progress": run_dir / "progress.json",                  # 实时进度快照（status.py 用）
        "status": run_dir / bs_config.STATUS_FILE_NAME,          # 最新状态块（打开即可看）
        "preview": run_dir / bs_config.PREVIEW_FILE_NAME,        # 运行期"截至当前"的目录（节流刷新）
        "pending_md": run_dir / bs_config.PENDING_MD_NAME,       # 未产出摘要的日记（含原文）
        "pending_json": run_dir / bs_config.PENDING_JSON_NAME,
    }


def resolve_paths(args, timestamped: bool = True) -> Dict[str, Path]:
    """解析输出路径

    * 默认：``<输出根目录>/YYMMDDHHMMSS/``（每次运行一个子目录，历史互不覆盖）
    * ``--flat-output``：不建子目录，直接写输出根目录（旧行为）
    * ``timestamped=False``（--models/--test 之类不写产物的动作）：只用根目录
    """
    base_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir else bs_config.OUTPUT_DIR
    )
    base_dir = bs_config.ensure_output_dir(base_dir)
    if not timestamped or getattr(args, "flat_output", False):
        return build_run_paths(base_dir, base_dir)
    return build_run_paths(base_dir, bs_config.new_run_dir(base_dir))


def scope_label(years: Optional[Sequence[int]]) -> str:
    """状态块里显示的范围标签：2025年 / 2015年、2016年 / 全部年份"""
    if not years:
        return "全部年份"
    if len(years) == 1:
        return f"{years[0]} 年"
    return "、".join(f"{year} 年" for year in years)


def heartbeat_interval(args, settings) -> float:
    """心跳间隔（CLI > .env > 默认；不低于下限，防止把终端刷爆）"""
    value = getattr(args, "heartbeat", None)
    if value is None:
        value = settings.get("heartbeat_seconds", bs_config.HEARTBEAT_SECONDS)
    return max(float(value), float(bs_config.HEARTBEAT_MIN_SECONDS))


def preview_interval(args, settings) -> float:
    """中途预览刷新间隔（CLI > .env > 默认；0 = 关闭；正数时不低于下限）"""
    value = getattr(args, "preview_every", None)
    if value is None:
        value = settings.get("preview_every_seconds", bs_config.PREVIEW_EVERY_SECONDS)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = float(bs_config.PREVIEW_EVERY_SECONDS)
    if seconds <= 0:
        return 0.0
    return max(seconds, float(bs_config.PREVIEW_MIN_SECONDS))


def build_reporter(
    args,
    settings,
    paths: Optional[Dict[str, Path]],
    years,
    *,
    phase: str = "starting",
    phase_note: str = "",
) -> progress_mod.ProgressReporter:
    """构造运行期进度记录器（控制台心跳 + progress.json + 运行状态.txt）"""
    paths = paths or {}
    return progress_mod.ProgressReporter(
        scope=scope_label(years),
        phase=phase,
        phase_note=phase_note,
        interval=heartbeat_interval(args, settings),
        enabled=not getattr(args, "quiet", False) and not getattr(args, "no_heartbeat", False),
        progress_file=paths.get("progress"),
        status_file=paths.get("status"),
    )


def parse_years(args) -> Optional[List[int]]:
    """把 --year / --years 解析成年份列表（None 表示全部）"""
    if args.year:
        return [int(args.year)]
    if not args.years:
        return None
    years: List[int] = []
    for chunk in str(args.years).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                raise SystemExit(f"[错误] 年份范围格式不正确：{chunk}")
            if start > end:
                start, end = end, start
            years.extend(range(start, end + 1))
        else:
            try:
                years.append(int(chunk))
            except ValueError:
                raise SystemExit(f"[错误] 年份格式不正确：{chunk}")
    return sorted(set(years)) or None


def resolve_entry_types(args) -> List[str]:
    """解析要处理的条目类型（默认排除 stock_diary）"""
    if args.types:
        types = [t.strip() for t in str(args.types).split(",") if t.strip()]
        unknown = [t for t in types if t not in bs_config.ALL_ENTRY_TYPES]
        if unknown:
            raise SystemExit(
                f"[错误] 未知的 entry_type：{unknown}；可选：{list(bs_config.ALL_ENTRY_TYPES)}"
            )
        return types
    types = list(bs_config.DEFAULT_ENTRY_TYPES)
    if args.include_stock and "stock_diary" not in types:
        types.append("stock_diary")
    return types


# ---------------- 数据准备 ----------------

def load_entries(args, settings, entry_types: Sequence[str]) -> List[Dict]:
    """通过共享只读 DAL（webapp/database.py）取出日记"""
    years = parse_years(args)
    reader = dal.DiaryReader(settings["db_path"])
    entries = reader.entries(years=years, entry_types=entry_types)
    if args.limit:
        entries = entries[: max(0, int(args.limit))]
    return entries


def pick_samples(entries: List[Dict], count: int, rng: random.Random) -> List[Dict]:
    """按年份轮转抽样，尽量覆盖不同年份"""
    if count >= len(entries):
        return list(entries)
    buckets: Dict[int, List[Dict]] = {}
    for entry in entries:
        buckets.setdefault(int(entry.get("year") or 0), []).append(entry)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    samples: List[Dict] = []
    year_keys = sorted(buckets)
    index = 0
    while len(samples) < count:
        progressed = False
        for year in year_keys:
            bucket = buckets[year]
            if index < len(bucket) and len(samples) < count:
                samples.append(bucket[index])
                progressed = True
        if not progressed:
            break
        index += 1
    return samples


def build_client(args) -> LLMClient:
    """构造本地模型客户端（非本机地址会直接抛错）"""
    try:
        return LLMClient(
            base_url=args.base_url,
            model=args.model,
            reasoning_effort=getattr(args, "reasoning_effort", None),
        )
    except LLMError as exc:
        raise SystemExit(
            f"[错误] {exc}\n（本功能只允许调用本机 LM Studio，请确认服务已启动）"
        )


def load_template():
    """读取 Prompt 模板与其指纹"""
    template = summary.load_prompt_template()
    return template, summary.prompt_sha1(template)


# ---------------- 进度快照（实现见 progress.py，主程序与 status.py 共用） ----------------

#: 进度快照（`progress.json` 与状态块共用同一份数据）
build_progress_snapshot = progress_mod.build_progress_snapshot
#: 原子写出进度快照
write_progress_file = progress_mod.write_progress_file


# ---------------- 中途预览（运行期间可随时打开） ----------------

class PreviewWriter:
    """运行期"中途预览"：节流重写 ``<运行目录>/中途预览.md``

    全量跑要几小时，而最终 ``日记总结.md`` 只在整轮结束后写一次；本类把
    **内存里已有的断点状态**渲染成"截至当前"的摘要目录，让用户中途就能看到结果。

    设计要点（都是为了让预览"只用眼睛看，不影响任务"）：

    * 只读内存状态：不读盘、不调模型、**不写 progress.json、不新建运行目录**，
      因此不会干扰 ``status.py`` 对"最近一次运行"的判断；
    * 节流：距上次写入不足 ``every`` 秒就直接跳过；
    * 正文缓存：摘要条数没变化时沿用上次渲染的正文（省掉一次重排），只更新头部进度；
    * 任何异常都吞掉（写文件失败绝不算任务失败）；``enabled=False`` 时完全不碰文件。

    典型用法（``main.py`` 里）::

        preview = PreviewWriter(paths["preview"], every=60)
        preview.maybe(summary_state, processed=index, total=total)   # 每篇调用，内部节流
        preview.finish(summary_state, phase="done")                  # 收尾强制写一次
    """

    def __init__(self, path=None, *, every: float = 60, min_seconds: float = 5, enabled: bool = True):
        self.path = Path(path) if path else None
        self.every = float(every or 0.0)
        if self.every > 0:
            self.every = max(self.every, float(min_seconds or 0.0))
        self.enabled = bool(enabled) and self.path is not None and self.every > 0
        self.writes = 0                                    # 实际写了几次（测试用）
        self._last_write: Optional[float] = None
        self._last_summaries = -1                          # 上次渲染正文时的摘要条数
        self._body: Optional[List[str]] = None
        self._processed = 0
        self._total = 0

    # -- 主接口 --
    def maybe(self, summary_state, *, processed=0, total=0, current=None, phase="running") -> bool:
        """到点才刷新（未到间隔 / 已写过且摘要条数无变化 -> 不写）"""
        self._processed, self._total = int(processed or 0), int(total or 0)
        if not self.enabled:
            return False
        now = time.monotonic()
        if self._last_write is not None and (now - self._last_write) < self.every:
            return False
        return self._write(summary_state, current=current, phase=phase)

    def finish(self, summary_state, *, processed=None, total=None, phase="done", current=None) -> bool:
        """收尾强制写一次（任务完成 / Ctrl+C 中断时调用）"""
        if processed is not None:
            self._processed = int(processed or 0)
        if total is not None:
            self._total = int(total or 0)
        if not self.enabled:
            return False
        return self._write(summary_state, current=current, phase=phase)

    # -- 内部 --
    def _write(self, summary_state, *, current=None, phase="running") -> bool:
        try:
            summary_count = summary_state.summary_count()
            if self._body is None or summary_count != self._last_summaries:
                records = collect_summaries(summary_state)     # 与最终产物同一套渲染逻辑
                self._body = render.render_sections(records)
                self._last_summaries = summary_count
            text = render.compose_preview(
                render.preview_header(
                    processed=self._processed, total=self._total,
                    current=current, phase=phase, every=self.every,
                ),
                self._body,
            )
        except Exception as exc:                            # 预览永远不能拖垮主流程
            logger.debug("中途预览渲染失败：%s", exc)
            return False
        if progress_mod.write_text_atomic(self.path, text):
            self._last_write = time.monotonic()
            self.writes += 1
            return True
        return False


# ---------------- 核心处理 ----------------

def process_entries(
    entries: List[Dict],
    client,
    summary_state: state_mod.SummaryState,
    template: str,
    prompt_sha1_value: str,
    *,
    force: bool = False,
    quiet: bool = False,
    progress=None,
    progress_file=None,
    year_label: str = "",
    reporter: Optional["progress_mod.ProgressReporter"] = None,
    preview: Optional["PreviewWriter"] = None,
) -> Dict:
    """逐篇调用模型写摘要并写入状态；已处理且内容未变的条目不再调用模型

    单篇失败只记录并继续（连续失败达到阈值才停止），Ctrl+C 由调用方处理。

    进度输出：

    * 传了 ``reporter`` → 由 :class:`~scripts.batch_summary.progress.ProgressReporter`
      统一负责心跳状态块、``progress.json`` 与 ``运行状态.txt``；
    * 没传（旧调用方式 / 单测）→ 退回 ``progress`` 回调 + ``progress_file``。

    中途查看结果：传了 ``preview`` → 期间节流刷新 ``中途预览.md``（不调模型、
    不写 progress.json），随时打开就能看到"截至当前"的摘要目录。

    ``status`` 口径：``ok`` = 产出摘要；``empty`` = 空正文或模型给出空答案；
    ``failed`` = 调用失败。此口径与统计数字、状态文件保持一致。
    """
    total = len(entries)
    stats = {"total": total, "ok": 0, "empty": 0, "failed": 0, "skipped": 0, "summaries": 0}
    if reporter is not None:
        emit = reporter.emit                     # 与心跳共用锁，输出不会互相插行
        reporter.set_total(total)
    elif progress is not None:
        emit = progress
    else:
        emit = lambda text: print(text, flush=True)   # noqa: E731
    consecutive_failures = 0
    started = time.monotonic()

    def snapshot(phase: str, index: int, current=None, entry_elapsed=None, note=None):
        """刷新进度（reporter 负责落盘；否则退回旧的 progress.json 写法）"""
        if reporter is not None:
            if phase == "done":
                reporter.update(index, stats=stats, note=note)
                reporter.set_phase("done")
                reporter.clear_current()
            else:
                reporter.update(
                    index, stats=stats, current=current,
                    entry_elapsed=entry_elapsed, note=note,
                )
            return
        write_progress_file(
            progress_file,
            build_progress_snapshot(
                phase=phase, total=total, index=index, stats=stats,
                started=started, current=current, entry_elapsed=entry_elapsed,
                year_label=year_label,
            ),
        )

    def preview_tick(index, current=None):
        """刷新中途预览（节流 + 失败静默；没传 preview 时什么都不做）"""
        if preview is None:
            return
        preview.maybe(summary_state, processed=index, total=total, current=current)

    if reporter is not None:
        reporter.set_phase("calling_model", "等待本地模型返回")
    snapshot("running", 0)

    for index, entry in enumerate(entries, 1):
        entry_id = entry.get("id")
        content = entry.get("content") or ""
        digest = state_mod.content_hash(content)
        skip, reason = summary_state.should_skip(entry_id, digest, force=force)
        if skip:
            stats["skipped"] += 1
            record = summary_state.get(entry_id) or {}
            if state_mod.has_summary(record):
                stats["summaries"] += 1
            snapshot(
                "running", index, entry,
                note=f"跳过已处理：{entry.get('date')}（断点续跑，不调用模型）",
            )
            preview_tick(index)
            continue

        status, error, summary_text = "ok", None, ""
        entry_started = time.monotonic()
        if not content.strip():
            status = "empty"          # 空正文：不调用模型
            entry_elapsed = 0.0
        else:
            if not quiet:
                emit(
                    f"[{index}/{total}] 处理中 {entry.get('date')} {entry.get('entry_type')} "
                    f"{entry.get('word_count')}字 …"
                )
            snapshot(
                "running", index, entry,
                note=f"正在处理 {entry.get('date')} {entry.get('entry_type')} "
                     f"{entry.get('word_count')}字（等待模型响应）",
            )
            preview_tick(index, entry)
            try:
                raw = client.chat(summary.build_prompt(template, entry))
                summary_text = summary.summarize_from_response(raw, entry, logger_=logger)
            except LLMError as exc:
                status, error = "failed", str(exc)
            except Exception as exc:  # 任何意外都不应中断整轮任务
                status, error = "failed", f"{type(exc).__name__}: {exc}"
            entry_elapsed = time.monotonic() - entry_started

        if status != "failed" and not summary_text.strip():
            status = "empty"          # 空正文，或模型给出了空答案

        if status == "failed":
            consecutive_failures += 1
            stats["failed"] += 1
            logger.error("处理失败 entry_id=%s date=%s：%s", entry_id, entry.get("date"), error)
        else:
            consecutive_failures = 0
            stats[status] += 1
            if summary_text.strip():
                stats["summaries"] += 1

        summary_state.put(entry_id, {
            "entry_id": entry_id,
            "entry_date": str(entry.get("date") or ""),
            "entry_type": entry.get("entry_type"),
            "word_count": entry.get("word_count"),
            "content_hash": digest,
            "prompt_sha1": prompt_sha1_value,
            "status": status,
            "error": error,
            "processed_at": state_mod.now_iso(),
            "summary": summary_text,
        })
        summary_state.save_if_needed()

        elapsed = time.monotonic() - started
        done = stats["ok"] + stats["empty"] + stats["failed"]
        avg = elapsed / done if done else 0.0
        rate = done / elapsed * 3600 if elapsed > 0 else 0.0
        eta = avg * max(total - index, 0)

        detail = (
            f"{len(summary_text)}字摘要" if status == "ok"
            else ("空摘要" if status == "empty" else f"失败({error})")
        )
        if not quiet:
            emit(
                f"[{index}/{total}] {entry.get('date')} {entry.get('entry_type')} "
                f"{entry.get('word_count')}字 → {detail} | 本篇 {entry_elapsed:.1f}s | "
                f"平均 {avg:.1f}s/篇 | 已用 {elapsed / 60:.0f}m | 剩余 ~{eta / 60:.0f}m | "
                f"有摘要:{stats['ok']} 空摘要:{stats['empty']} 失败:{stats['failed']} "
                f"跳过:{stats['skipped']} | {rate:.0f}条/h"
            )
        snapshot(
            "running", index, entry, entry_elapsed,
            note=f"{entry.get('date')} → {detail} ｜ 有摘要 {stats['ok']} ｜ 空摘要 "
                 f"{stats['empty']} ｜ 失败 {stats['failed']} ｜ 跳过 {stats['skipped']}",
        )
        preview_tick(index)

        if consecutive_failures >= bs_config.MAX_CONSECUTIVE_FAILURES:
            logger.error(
                "连续失败 %d 次，停止本轮任务；进度已保存，可直接重跑续跑", consecutive_failures
            )
            break

    stats["elapsed_seconds"] = round(time.monotonic() - started, 1)
    stats["calls"] = int(getattr(client, "call_count", 0))
    summary_state.save(force=True)
    snapshot(
        "done", total,
        note=f"处理结束：有摘要 {stats['ok']} ｜ 空摘要 {stats['empty']} ｜ 失败 {stats['failed']} "
             f"｜ 跳过 {stats['skipped']}",
    )
    return stats


# ---------------- 汇总输出 ----------------

def collect_summaries(summary_state: state_mod.SummaryState) -> List[Dict]:
    """取出状态里所有已产出的摘要（按日期排序，不调用模型）"""
    return summary_state.summary_records()


def collect_pending(summary_state, settings) -> List[Dict]:
    """收集"没有产出摘要"的条目原文，供人工复核

    判定依据：``status == "failed"``（调用失败）或记录里没有可用摘要
    （空正文、模型给出空答案）。全程只读数据库。
    """
    records = [
        record for record in sorted(
            summary_state.results.values(),
            key=lambda r: (str(r.get("entry_date") or ""), int(r.get("entry_id") or 0)),
        )
        if record.get("status") == "failed" or not state_mod.has_summary(record)
    ]
    if not records:
        return []

    reader = dal.DiaryReader(settings["db_path"])
    items: List[Dict] = []
    for record in records:
        entry = reader.entry(record.get("entry_id")) or {}
        status = record.get("status")
        if status != "failed" and not state_mod.has_summary(record):
            status = "empty"      # 没有摘要但不是失败 -> 一律按"空摘要"呈现
        items.append({
            "entry_id": record.get("entry_id"),
            "entry_date": str(record.get("entry_date") or entry.get("date") or ""),
            "entry_type": record.get("entry_type") or entry.get("entry_type"),
            "word_count": record.get("word_count") or entry.get("word_count") or 0,
            "status": status,
            "error": record.get("error"),
            "file_source": entry.get("file_source"),
            "content": entry.get("content") or "",
        })
    return items


def write_pending_outputs(paths: Dict[str, Path], items: List[Dict]) -> Dict[str, Path]:
    """写出"待复核"清单（Markdown 供人读，JSON 供后续加工）"""
    paths["pending_md"].write_text(render.render_pending_markdown(items), encoding="utf-8")
    paths["pending_json"].write_text(
        json.dumps(
            {"generated_at": state_mod.now_iso(), "count": len(items), "items": items},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return paths


def build_summaries_payload(
    summary_state,
    records: List[Dict],
    *,
    model: str,
    prompt_sha1_value: str,
    entry_types: Sequence[str],
    years: Optional[Sequence[int]],
    stats: Optional[Dict] = None,
) -> Dict:
    """结构化中间结果（每篇日记一条摘要记录，便于以后重新生成 Markdown）"""
    keys = ("entry_id", "entry_date", "entry_type", "word_count", "status", "summary")
    entries = [
        {k: record.get(k) for k in keys}
        for record in sorted(
            summary_state.results.values(),
            key=lambda r: (str(r.get("entry_date") or ""), int(r.get("entry_id") or 0)),
        )
    ]
    return {
        "version": 2,
        "generated_at": state_mod.now_iso(),
        "model": model,
        "prompt_sha1": prompt_sha1_value,
        "entry_types": list(entry_types),
        "years": list(years) if years else None,
        "stats": stats or {},
        "state_stats": summary_state.stats(),
        "summary_count": len(records),
        "entries": entries,
    }


def write_outputs(paths: Dict[str, Path], payload: Dict, records: List[Dict]) -> Dict[str, Path]:
    """写出 Markdown 与 JSON（Markdown 完全由 Python 生成）"""
    markdown = render.render_markdown(records)
    paths["summaries"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["markdown"].write_text(markdown, encoding="utf-8")
    return paths


def print_summary(records: List[Dict], summary_state, stats: Optional[Dict] = None):
    years = render.summarize_years(records)
    print("")
    print("=" * 60)
    if stats:
        print(
            f"处理: {stats.get('ok', 0)} 篇有摘要 | {stats.get('empty', 0)} 篇空摘要 | "
            f"{stats.get('failed', 0)} 篇失败 | {stats.get('skipped', 0)} 篇跳过(断点) | "
            f"模型调用 {stats.get('calls', 0)} 次 | 用时 {stats.get('elapsed_seconds', 0)}s"
        )
    print(f"摘要条数: {len(records)}；覆盖年份: {len(years)}")
    for year, count in years.items():
        print(f"  {year}年: {count} 条")


def dump_preview(entry: Dict, raw: str, summary_text: str):
    """--test 用：打印原文片段、模型原始输出与清洗后的摘要"""
    print("-" * 60)
    print(
        f"日期: {entry.get('date')} | 类型: {entry.get('entry_type')} | "
        f"{entry.get('word_count')}字"
    )
    preview = " ".join((entry.get("content") or "").split())[:120]
    print(f"原文前 120 字: {preview}")
    print("模型原始输出:")
    print((raw or "").strip()[:600])
    print("清洗后的摘要:")
    if summary_text:
        print(f"  {summary_text}（{len(summary_text)}字）")
    else:
        print("  （无摘要：模型给出了空答案）")


# ---------------- 子命令 ----------------

def cmd_models(args, settings) -> int:
    """--models：确认 LM Studio 实际模型名（不猜模型名）"""
    base = (args.base_url or settings["llm_base_url"]).rstrip("/")
    print(f"LM Studio 地址: {base}")
    try:
        models = list_models(base, 10.0)
    except LLMError as exc:
        print(f"[错误] {exc}")
        print("请确认 LM Studio 已启动，并在 Developer/Server 页开启本地服务。")
        return EXIT_ERROR

    if not models:
        print("未发现任何模型。请先在 LM Studio 中加载 Qwen3.5-9B。")
        return EXIT_NO_MODEL

    print(f"共发现 {len(models)} 个模型：")
    for model in models:
        state = f" | state={model['state']}" if model.get("state") else ""
        print(f"  - {model['id']}  (type={model['type']}{state})")

    picked = pick_chat_model(models)
    print("")
    if picked:
        print(f"[OK] 可用的对话模型：{picked}")
        print(f"建议在项目根目录 .env 中写入：LLM_MODEL={picked}")
        return EXIT_OK
    print("[错误] 没有可用的对话模型（只看到 embedding 模型）。")
    print("请在 LM Studio 中加载 Qwen3.5-9B 后重新运行 --models。")
    return EXIT_NO_MODEL


def cmd_test(args, settings, paths: Dict[str, Path]) -> int:
    """--test：抽样试跑（只打印，不写状态与输出文件）

    同样带心跳状态块：抽样也常有"一篇要等几十秒"的情况，能看出卡在哪一篇。
    """
    entry_types = resolve_entry_types(args)
    years = parse_years(args)
    reporter = build_reporter(
        args, settings, None, years,
        phase="loading", phase_note="数据库只读，不会改动日记",
    )   # 只打印，不写任何进度文件
    reporter.start()
    try:
        entries = load_entries(args, settings, entry_types)
        if not entries:
            print("[错误] 没有符合条件的日记（请检查 --year / --years / --types / --limit）")
            return EXIT_ERROR
        reporter.set_total(
            len(entries),
            days_total=len({str(e.get("date") or "") for e in entries if e.get("date")}),
        )
        return _run_test_samples(args, settings, entries, reporter)
    finally:
        reporter.stop()


def _run_test_samples(args, settings, entries: List[Dict], reporter) -> int:
    """--test 的抽样逻辑（拆出来便于在 reporter 生命周期内执行）"""
    template, prompt_sha1_value = load_template()
    client = build_client(args)
    try:
        model = client.resolve_model()
    except LLMError as exc:
        print(f"[错误] {exc}")
        return EXIT_NO_MODEL

    samples = pick_samples(entries, max(1, int(args.samples)), random.Random(bs_config.RANDOM_SEED))
    print(
        f"模型: {model} | 地址: {client.base_url} | "
        f"思考: {client.reasoning_effort or '模型默认'} | Prompt 指纹: {prompt_sha1_value}"
    )
    print(f"符合条件 {len(entries)} 篇，抽样 {len(samples)} 篇（仅打印，不写状态/输出文件）")

    reporter.set_phase("calling_model", "抽样调用模型")
    for index, entry in enumerate(samples, 1):
        reporter.update(index, current=entry, note=f"抽样 {index}/{len(samples)}：{entry.get('date')}")
        print("")
        print(f"=== [{index}/{len(samples)}] {entry.get('date')} {entry.get('entry_type')} ===")
        try:
            raw = client.chat(summary.build_prompt(template, entry))
        except LLMError as exc:
            print(f"[错误] 调用失败：{exc}")
            reporter.note(f"[错误] 抽样 {entry.get('date')} 调用失败：{exc}")
            continue
        dump_preview(entry, raw, summary.summarize_from_response(raw, entry, logger_=logger))
        reporter.note(f"抽样完成 {index}/{len(samples)}：{entry.get('date')}")

    reporter.set_phase("done", "抽样完成")
    print("")
    print("抽样完成。满意后运行全量：python scripts/batch_summary/main.py --all")
    return EXIT_OK


# ---------------- 子命令：全量 / 重建 ----------------

def cmd_all(args, settings, paths: Dict[str, Path]) -> int:
    """--all：全量提取（支持 Ctrl+C 断点续跑；运行期间持续打印人类可读进度）"""
    entry_types = resolve_entry_types(args)
    years = parse_years(args)
    try:
        state_mod.setup_logging(paths["log"], quiet=args.quiet)
    except OSError as exc:
        print(f"[错误] 无法写入日志文件：{exc}")
        return EXIT_ERROR

    reporter = build_reporter(
        args, settings, paths, years,
        phase="loading", phase_note="数据库只读，不会改动日记",
    )
    reporter.attach_logger(logger)                 # 日志（含重试警告）→ 状态块的"最近日志"
    reporter.start()                               # 立刻打一块，之后每 N 秒再打
    print(f"本次运行目录: {paths['dir']}")
    try:
        entries = load_entries(args, settings, entry_types)
        if not entries:
            print("[错误] 没有符合条件的日记（请检查 --year / --years / --types / --limit）")
            return EXIT_ERROR

        template, prompt_sha1_value = load_template()
        client = build_client(args)
        try:
            model = client.resolve_model()
        except LLMError as exc:
            print(f"[错误] {exc}")
            return EXIT_NO_MODEL

        logger.info(
            "开始批量总结 | 模型=%s | 地址=%s | 思考=%s | Prompt指纹=%s | 类型=%s | 年份=%s | 条数=%d",
            model, client.base_url, client.reasoning_effort or "模型默认",
            prompt_sha1_value, ",".join(entry_types), years or "全部", len(entries),
        )

        days_total = len({str(e.get("date") or "") for e in entries if e.get("date")})
        reporter.set_total(len(entries), days_total=days_total)

        summary_state = state_mod.SummaryState(
            path=paths["state"],
            prompt_sha1=prompt_sha1_value,
            model=model,
            entry_types=entry_types,
        ).load()
        previous = summary_state.stats()
        print(
            f"待处理 {len(entries)} 篇（覆盖 {days_total} 天）| 已有状态: 有摘要 {previous.get('ok', 0)} / "
            f"空摘要 {previous.get('empty', 0)} / 失败 {previous.get('failed', 0)}"
        )
        print("可随时 Ctrl+C 中断：下次重跑同一命令会自动续跑，已处理的条目不会再调用模型")
        print(
            f"运行期间每 {reporter.interval:.0f} 秒自动打印一次状态；"
            f"也可随时打开 {paths['status']} 查看"
        )
        preview = PreviewWriter(
            paths.get("preview"),
            every=preview_interval(args, settings),
            min_seconds=bs_config.PREVIEW_MIN_SECONDS,
            enabled=not getattr(args, "no_preview", False),
        )
        if preview.enabled:
            print(
                f"中途想看已总结的内容：随时打开 {paths['preview']}"
                f"（每 {preview.every:.0f} 秒自动更新，无需等跑完）"
            )
        print()

        try:
            stats = process_entries(
                entries, client, summary_state, template, prompt_sha1_value,
                force=args.force, quiet=args.quiet,
                year_label=",".join(str(y) for y in years) if years else "全部",
                reporter=reporter, preview=preview,
            )
        except KeyboardInterrupt:
            summary_state.save(force=True)
            reporter.stop()
            preview.finish(summary_state, phase="interrupted")
            print("\n\n[中断] 进度已保存：重跑同一命令即可续跑，也可先用 --rebuild-md 查看已有结果。")
            if preview.enabled:
                print(f"[中断] 已总结的内容见：{paths['preview']}")
            return EXIT_OK

        reporter.set_phase("merging", "汇总生成目录，不调用模型")
        records = collect_summaries(summary_state)

        reporter.set_phase("saving", "写 Markdown / JSON / 待复核清单")
        payload = build_summaries_payload(
            summary_state, records,
            model=model, prompt_sha1_value=prompt_sha1_value,
            entry_types=entry_types, years=years, stats=stats,
        )
        write_outputs(paths, payload, records)
        pending = collect_pending(summary_state, settings)
        write_pending_outputs(paths, pending)

        print_summary(records, summary_state, stats)
        preview.finish(summary_state, processed=len(entries), total=len(entries), phase="done")
        reporter.set_phase("done")
        print(f"本次运行目录: {paths['dir']}")
        print(f"已生成: {paths['markdown']}")
        if preview.enabled:
            print(f"中途预览（含运行期快照）: {paths['preview']}")
        print(f"待复核(未产出摘要) {len(pending)} 篇 → {paths['pending_md']}")
        print(f"状态快照: {paths['status']} | 进度: {paths['progress']}")
        print(f"断点状态(跨运行共享): {paths['state']} | 日志: {paths['log']}")
        return EXIT_OK
    finally:
        reporter.stop()


def cmd_rebuild(args, settings, paths: Dict[str, Path]) -> int:
    """--rebuild-md：不调用模型，用已有摘要重新生成 Markdown 与 JSON"""
    years = parse_years(args)
    try:
        state_mod.setup_logging(paths["log"], quiet=args.quiet)
    except OSError as exc:
        print(f"[错误] 无法写入日志文件：{exc}")
        return EXIT_ERROR

    reporter = build_reporter(
        args, settings, paths, years,
        phase="loading", phase_note="读取断点状态，不调用模型",
    )
    reporter.attach_logger(logger)
    reporter.start()
    print(f"本次运行目录: {paths['dir']}")
    try:
        summary_state = state_mod.SummaryState(path=paths["state"]).load()
        if not summary_state.results:
            print(f"[错误] 未找到处理结果：{paths['state']}")
            print("请先运行：python scripts/batch_summary/main.py --all")
            return EXIT_ERROR

        reporter.set_total(len(summary_state.results))
        state_stats = summary_state.stats()
        reporter.update(
            len(summary_state.results),
            stats={
                "ok": state_stats.get("ok", 0),
                "empty": state_stats.get("empty", 0),
                "failed": state_stats.get("failed", 0),
                "skipped": 0,
                "summaries": len(summary_state.summary_records()),
            },
            note=f"读入已有结果 {len(summary_state.results)} 篇（不调用模型）",
        )
        reporter.set_phase("merging", "汇总生成目录，不调用模型")
        records = collect_summaries(summary_state)

        reporter.set_phase("saving", "写 Markdown / JSON / 待复核清单")
        payload = build_summaries_payload(
            summary_state, records,
            model=summary_state.model, prompt_sha1_value=summary_state.prompt_sha1,
            entry_types=summary_state.entry_types, years=years,
            stats={"source": "rebuild-md"},
        )
        write_outputs(paths, payload, records)
        pending = collect_pending(summary_state, settings)
        write_pending_outputs(paths, pending)

        print_summary(records, summary_state)
        reporter.set_phase("done")
        print(f"已重新生成: {paths['markdown']}（本次未调用模型）")
        print(f"待复核(未产出摘要) {len(pending)} 篇 → {paths['pending_md']}")
        print(f"状态快照: {paths['status']} | 进度: {paths['progress']}")
        return EXIT_OK
    finally:
        reporter.stop()


# ---------------- 入口 ----------------

def main(argv=None) -> int:
    fix_windows_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not (args.models or args.test or args.all or args.rebuild_md):
        parser.print_help()
        print("\n请选择一个动作：--models / --test / --all / --rebuild-md")
        return EXIT_ERROR

    # --models / --test 不写产物，就不建时间戳子目录（--test 结束时也不会留下空目录）
    paths = resolve_paths(args, timestamped=not (args.models or args.test))
    try:
        settings = bs_config.get_settings()
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return EXIT_ERROR

    if args.models:
        return cmd_models(args, settings)
    if args.test:
        return cmd_test(args, settings, paths)
    if args.all:
        return cmd_all(args, settings, paths)
    return cmd_rebuild(args, settings, paths)


if __name__ == "__main__":
    sys.exit(main())