#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 入口脚本

用本地 LM Studio 模型逐篇阅读 SQLite 中的日记，为**每一篇**写一段摘要，
生成一份「中途预览.md」。全程本地运行，数据库只读，原始日记不修改。

本功能刻意不让本地模型做判断：模型只负责"把这篇日记写成一段摘要"，
既不筛"重要/不重要"，也不负责日期或标题——因此每一篇都会产出摘要。

常用命令：

    python batch_summary/main.py --models             # 确认 LM Studio 实际模型名
    python batch_summary/main.py --test --samples 10  # 抽样试跑（不写任何文件）
    python batch_summary/main.py --all                # 全量（可 Ctrl+C，重跑自动续跑）
    python batch_summary/main.py --years 2015-2019    # 分年跑
    python batch_summary/main.py --rebuild-md         # 不调模型，用已有摘要重写预览

产物：**只有一个文件** —— 中途预览.md，写在项目根目录的 output/ 里（每次运行覆盖）

    output/中途预览.md
        运行期间：每 N 秒刷新一次的"截至当前"目录（随时可打开）
        跑完/中断：同一个文件被重写为最终版（标题变成 # 日记总结，并标记生成日期）

除此之外不再生成任何中间文件（无 summaries.json / progress.json / 运行状态.txt /
待复核清单 / 日志文件）。断点续跑状态在 SQLite（entry_summaries 表），跨运行共享。

运行期间终端会**自己**持续打印人类可读进度（默认每 30 秒一块，可 --heartbeat 调整）：
不需要另开终端看进度，也不需要用 ps/grep/tail 之类的命令去猜任务状态。
"""

import argparse
import io
import logging
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# 项目根目录加入 sys.path（保证 `python batch_summary/main.py` 也能绝对导入包）
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from batch_summary import config as bs_config  # noqa: E402
from batch_summary import (  # noqa: E402
    dal,
    emotion as emotion_mod,
    progress as progress_mod,
    render,
    state as state_mod,
    summary,
)
from batch_summary.llm import (  # noqa: E402
    LLMClient,
    LLMError,
    list_models,
    pick_chat_model,
)
from summary_database import SummaryRepository, SummaryStore  # noqa: E402
from summary_fingerprint import (  # noqa: E402
    algorithm_fingerprint,
    algorithm_payload,
    cache_key as make_cache_key,
    emotion_payload,
    entry_key as make_entry_key,
    source_hash,
)

logger = logging.getLogger("batch_summary")

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
        prog="python batch_summary/main.py",
        description="日记批量总结：用本地 LLM 为 SQLite 里的每一篇日记写一段摘要，生成按年份排列的目录。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--models", action="store_true", help="列出 LM Studio 可见模型后退出（确认模型名）")
    mode.add_argument("--test", action="store_true", help="抽样试跑，只打印结果，不写状态与输出文件")
    mode.add_argument("--all", action="store_true", help="全量生成（可中断续跑）")
    mode.add_argument("--rebuild-md", action="store_true", help="不调用模型，仅用已有摘要重写「中途预览.md」")
    mode.add_argument("--reset-summaries", action="store_true", help="只清空摘要相关表，不修改原始日记")

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
        "--no-emotion",
        action="store_true",
        help="不做情绪判断（只写摘要；等价于 .env 里 EMOTION_ENABLED=0）",
    )
    parser.add_argument(
        "--emotion-only",
        action="store_true",
        help="只补情绪：摘要一律复用已有结果，只为缺情绪/情绪过期的篇目各发一次调用",
    )
    parser.add_argument(
        "--force-emotion",
        action="store_true",
        help="忽略情绪缓存，重新判断情绪（摘要仍按原有缓存规则）",
    )
    parser.add_argument(
        "--output-dir",
        help="输出根目录（默认：项目根目录下的 output/）；「中途预览.md」直接写在这里",
    )
    parser.add_argument(
        "--flat-output",
        action="store_true",
        help="不建时间戳子目录，直接把「中途预览.md」写到输出根目录（旧行为）",
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
        help="不写任何文件（连「中途预览.md」也不生成，只打印进度）",
    )
    parser.add_argument("--base-url", help="覆盖 LM Studio 地址（仍强制本机地址）")
    parser.add_argument("--model", help="覆盖模型名（默认读取 .env 的 LLM_MODEL，留空则自动发现）")
    parser.add_argument(
        "--reasoning-effort",
        help="覆盖思考强度：none=关闭思考（推理模型推荐，快很多）/low/medium/high；"
             "留空=不发送该参数（默认读 .env 的 LLM_REASONING_EFFORT）",
    )
    parser.add_argument("--quiet", action="store_true", help="减少控制台输出（不打印心跳状态块）")
    return parser


def build_run_paths(base_dir: Path, run_dir: Path) -> Dict[str, Path]:
    """本次运行的产物路径

    只有一个产物：``run_dir/中途预览.md``（每次运行一个 YYMMDDHHMMSS 子目录，
    历史互不覆盖）；断点续跑状态在 SQLite 的 ``entry_summaries`` 表里，跨运行共享。
    """
    return {
        "base_dir": base_dir,
        "dir": run_dir,
        "preview": run_dir / bs_config.PREVIEW_FILE_NAME,   # 唯一产物：运行期=快照，跑完=最终版
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
    years,
    *,
    phase: str = "starting",
    phase_note: str = "",
) -> progress_mod.ProgressReporter:
    """构造运行期进度记录器（只打印心跳状态块，不写任何文件）"""
    return progress_mod.ProgressReporter(
        scope=scope_label(years),
        phase=phase,
        phase_note=phase_note,
        interval=heartbeat_interval(args, settings),
        enabled=not getattr(args, "quiet", False) and not getattr(args, "no_heartbeat", False),
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


# 旧类型 -> 现类型：single_day / multi_day 已合并为普通日记 diary
LEGACY_ENTRY_TYPE_ALIASES = {"single_day": "diary", "multi_day": "diary"}


def resolve_entry_types(args) -> List[str]:
    """解析要处理的条目类型（默认排除 stock_diary；兼容旧的 single_day / multi_day）"""
    if args.types:
        types: List[str] = []
        for chunk in str(args.types).split(","):
            name = LEGACY_ENTRY_TYPE_ALIASES.get(chunk.strip(), chunk.strip())
            if name and name not in types:
                types.append(name)
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
    """通过共享只读 DAL（根目录 database.py）取出日记"""
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


def client_fingerprint_settings(settings, client) -> Dict:
    """把"实际使用的客户端参数"并入配置

    算法指纹要记录**真正发出去的参数**（可能被 --model / --reasoning-effort 覆盖过），
    而不是 .env 里原本的意图值。
    """
    merged = dict(settings)
    merged.update({
        "llm_temperature": client.temperature,
        "llm_max_tokens": client.max_tokens,
        "llm_json_mode": client.json_mode,
        "llm_reasoning_effort": client.reasoning_effort,
    })
    return merged


def load_emotion_template() -> str:
    """读取情绪 Prompt 模板（文件缺失/占位符不全时返回空串 → 情绪环节自动关闭）"""
    try:
        return emotion_mod.load_prompt_template()
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("情绪 Prompt 不可用，本次关闭情绪判断：%s", exc)
        return ""


def setup_emotion(args, settings, client, model, fingerprint_settings, store=None):
    """准备情绪判断器，返回 ``(classifier, fingerprint)``

    * ``enabled=False``（``--no-emotion`` / ``EMOTION_ENABLED=0`` / Prompt 文件缺失）时，
      主流程完全不做情绪判断；
    * 情绪算法指纹与摘要指纹彼此独立：它只影响情绪缓存，不会让已有摘要失效；
    * 传了 ``store`` 才把情绪算法登记进 ``summary_algorithms``（审计用）。
    """
    template = "" if getattr(args, "no_emotion", False) else load_emotion_template()
    enabled = bool(template) and (
        bool(settings.get("emotion_enabled", True)) or bool(getattr(args, "emotion_only", False))
    )
    fingerprint = ""
    if enabled:
        payload = emotion_payload(fingerprint_settings, model, template)
        fingerprint = algorithm_fingerprint(payload)
        if store is not None:
            store.register_algorithm(fingerprint, payload)
    classifier = emotion_mod.EmotionClassifier(
        client, template, fingerprint=fingerprint,
        labels=settings.get("emotion_labels"), fallback=settings.get("emotion_fallback"),
        max_tokens=settings.get("emotion_max_tokens"), enabled=enabled,
    )
    return classifier, fingerprint


# ---------------- 中途预览（运行期间可随时打开） ----------------

def body_signature(summary_state) -> Tuple[int, int]:
    """中途预览正文的"要不要重排"指纹：``(摘要条数, 情绪条数)``

    摘要条数足以覆盖正常运行（每篇摘要与情绪一起产出）；``--emotion-only``
    只补情绪、摘要条数不变，只能靠情绪条数触发重排，否则预览里的 ``【标签】``
    永远不会出现。老的状态对象没有 ``emotion_count`` 时按 0 处理。
    """
    counter = getattr(summary_state, "emotion_count", None)
    emotion_count = int(counter()) if callable(counter) else 0
    return int(summary_state.summary_count()), emotion_count


class PreviewWriter:
    """运行期"中途预览"：节流重写 ``<运行目录>/中途预览.md``

    全量跑要几小时，而最终版只在整轮结束后才写一次；本类把**内存里已有的结果**
    渲染成"截至当前"的摘要目录，让用户中途就能看到结果，跑完再重写为最终版。

    设计要点（都是为了让预览"只用眼睛看，不影响任务"）：

    * 只读内存状态：不读盘、不调模型、除本文件外不写任何东西；
    * 节流：距上次写入不足 ``every`` 秒就直接跳过；
    * 正文缓存：``(摘要条数, 情绪条数)`` 没变化时沿用上次渲染的正文（省掉一次重排），
      只更新头部进度；
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
        self._last_signature: Optional[Tuple[int, int]] = None   # 上次渲染正文时的指纹
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
        """写一次预览；``phase="done"`` 时写最终版（标题变成 # 日记总结）"""
        try:
            if phase == "done":
                text = render.render_markdown(collect_summaries(summary_state))
            else:
                signature = body_signature(summary_state)
                if self._body is None or signature != self._last_signature:
                    records = collect_summaries(summary_state)     # 与最终产物同一套渲染逻辑
                    self._body = render.render_sections(records)
                    self._last_signature = signature
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
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(text, encoding="utf-8")
        except OSError as exc:                              # 写不进去也不算任务失败
            logger.debug("中途预览写入失败：%s（%s）", self.path, exc)
            return False
        self._last_write = time.monotonic()
        self.writes += 1
        return True


class SummaryView:
    """SQLite 摘要的轻量内存视图（进度与预览渲染共用）"""

    def __init__(self, records=None):
        self.results = {str(record.get("entry_id")): dict(record) for record in (records or [])}

    def get(self, entry_id):
        return self.results.get(str(entry_id))

    def put(self, entry_id, record):
        self.results[str(entry_id)] = record

    def summary_count(self):
        return sum(state_mod.has_summary(record) for record in self.results.values())

    def emotion_count(self):
        """已有情绪标签的条目数（中途预览据此判断"情绪有没有新增"）"""
        return sum(
            1 for record in self.results.values()
            if str(record.get("emotion") or "").strip()
        )

    def summary_records(self):
        """已产出摘要的记录（DB 视图里的 ``emotion`` / ``emotion_status`` 会一并透出）"""
        records = [record for record in self.results.values() if state_mod.has_summary(record)]
        return sorted(records, key=lambda r: (str(r.get("entry_date") or ""), int(r.get("entry_id") or 0)))

    def stats(self):
        return {name: sum(record.get("status") == name for record in self.results.values())
                for name in ("ok", "empty", "failed")}


# ---------------- 核心处理 ----------------

def process_entries(
    entries: List[Dict],
    client,
    summary_state: SummaryView,
    template: str,
    prompt_sha1_value: str,
    *,
    force: bool = False,
    quiet: bool = False,
    progress=None,
    year_label: str = "",
    reporter: Optional["progress_mod.ProgressReporter"] = None,
    preview: Optional["PreviewWriter"] = None,
    store: SummaryStore,
    algorithm_fingerprint_value: str = "",
    run_id: Optional[int] = None,
    emotion_classifier: Optional["emotion_mod.EmotionClassifier"] = None,
    emotion_only: bool = False,
    force_emotion: bool = False,
) -> Dict:
    """逐篇调用模型写摘要并写入 SQLite；已处理且内容未变的条目不再调用模型

    单篇失败只记录并继续（连续失败达到阈值才停止），Ctrl+C 由调用方处理。
    摘要与情绪的缓存判定都在 SQLite（``store`` 是必填参数）：

    * 摘要命中且情绪也在：本篇不调用模型，计入 ``skipped``；
    * 摘要命中但情绪缺失/过期：只发一次情绪调用（``--emotion-only`` 就是这种模式）；
    * ``--force-emotion``：忽略情绪缓存重算（摘要仍按原有缓存规则）。

    进度输出：传了 ``reporter`` → 由 :class:`~batch_summary.progress.ProgressReporter`
    统一打印心跳状态块（**只打印、不落盘**）；否则退回 ``progress`` 回调。
    中途查看结果：传了 ``preview`` → 期间节流刷新「中途预览.md」（不调模型）。

    ``status`` 口径：``ok`` = 产出摘要；``empty`` = 空正文或模型给出空答案；
    ``failed`` = 调用失败。情绪同理：``emotions`` = 有标签；``emotion_empty`` = 空正文；
    ``emotion_failed`` = 调用失败。
    """
    total = len(entries)
    stats = {"total": total, "ok": 0, "empty": 0, "failed": 0, "skipped": 0, "summaries": 0,
             "emotions": 0, "emotion_empty": 0, "emotion_failed": 0, "emotion_skipped": 0}
    if reporter is not None:
        emit = reporter.emit                     # 与心跳共用锁，输出不会互相插行
        reporter.set_total(total)
    elif progress is not None:
        emit = progress
    else:
        emit = lambda text: print(text, flush=True)   # noqa: E731
    consecutive_failures = 0
    completed = True
    started = time.monotonic()

    def snapshot(phase: str, index: int, current=None, entry_elapsed=None, note=None):
        """刷新进度（只打印心跳状态块，不落盘）"""
        if reporter is None:
            return
        if phase == "done":
            reporter.update(index, stats=stats, note=note)
            reporter.set_phase("done")
            reporter.clear_current()
        else:
            reporter.update(
                index, stats=stats, current=current,
                entry_elapsed=entry_elapsed, note=note,
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
        digest = source_hash(content)
        stable_key = make_entry_key(entry)
        current_cache_key = make_cache_key(stable_key, digest, algorithm_fingerprint_value)
        summary_skip = not force and store.is_cache_hit(stable_key, current_cache_key)

        # -- 情绪：与摘要各自独立的缓存通道（摘要命中也要把缺的情绪补上）--
        emotion_active = bool(emotion_classifier and emotion_classifier.enabled)
        emotion_key = ""
        do_emotion = False
        if emotion_active:
            emotion_key = emotion_classifier.cache_key(stable_key, digest)
            do_emotion = force_emotion or not store.emotion_cache_hit(stable_key, emotion_key)
        if emotion_only:
            summary_skip = True        # --emotion-only：摘要一律复用，不重新生成

        if summary_skip and not do_emotion:
            stats["skipped"] += 1
            record = summary_state.get(entry_id) or {}
            if state_mod.has_summary(record):
                stats["summaries"] += 1
            if emotion_active:
                stats["emotion_skipped"] += 1
            snapshot(
                "running", index, entry,
                note=f"跳过已处理：{entry.get('date')}（断点续跑，不调用模型）",
            )
            preview_tick(index)
            continue

        status, error, summary_text = "ok", None, ""
        entry_started = time.monotonic()
        entry_elapsed = 0.0
        summary_processed = not summary_skip     # 本篇的摘要状态由本次确定（含空正文）
        summary_generated = False                # 是否真的调用了摘要模型
        if not summary_skip and not content.strip():
            status = "empty"                     # 空正文：不调用模型
        elif summary_skip:
            record = summary_state.get(entry_id) or {}
            status = str(record.get("status") or "ok")
            summary_text = str(record.get("summary") or "")
            error = record.get("error")
        else:
            summary_generated = True
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

        if summary_generated and status != "failed" and not summary_text.strip():
            status = "empty"          # 模型给出了空答案

        if summary_processed:
            if status == "failed":
                consecutive_failures += 1
                stats["failed"] += 1
                logger.error("处理失败 entry_id=%s date=%s：%s", entry_id, entry.get("date"), error)
            else:
                consecutive_failures = 0
                stats[status] += 1
                if summary_text.strip():
                    stats["summaries"] += 1

        record = {
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
            "emotion": "",
            "emotion_status": None,
        }
        record_tracked = True
        if summary_skip:
            previous = summary_state.get(entry_id)
            if previous is not None:
                record = previous             # 复用缓存：保留原记录（含已有情绪）
            else:
                record_tracked = False        # 无摘要记录：只在库里补情绪，不进内存视图
        else:
            summary_state.put(entry_id, record)
        if not summary_skip:
            store.upsert(
                entry, entry_key=stable_key, source_hash_value=digest,
                algorithm_fingerprint=algorithm_fingerprint_value,
                cache_key=current_cache_key, status=status, summary=summary_text,
                error=(error or "")[:500] or None,
            )
            if run_id is not None:
                store.update_run(
                    run_id, processed=index,
                    generated=stats["ok"] + stats["empty"], reused=stats["skipped"],
                    failed=stats["failed"],
                )

        # -- 情绪判断：摘要之后的第二次（很短）调用，缓存与摘要彼此独立 --
        if do_emotion and summary_generated and status == "failed":
            do_emotion = False                # 模型调用失败时不放大失败次数，重跑时一起重试
            logger.info("摘要调用失败，本篇跳过情绪判断 entry_id=%s", entry_id)
        emotion_label, emotion_status, emotion_error = "", None, None
        if do_emotion:
            if not content.strip():
                emotion_status = "empty"      # 空正文：没有情绪可判断
            else:
                outcome = emotion_classifier.classify(entry)
                emotion_label = outcome["emotion"]
                emotion_status = outcome["status"]
                emotion_error = outcome["error"]
                if emotion_status == "ok":
                    stats["emotions"] += 1
                else:
                    stats["emotion_failed"] += 1
                    logger.warning("情绪判断失败 entry_id=%s date=%s：%s",
                                   entry_id, entry.get("date"), emotion_error)
            if emotion_status == "empty":
                stats["emotion_empty"] += 1
            written = store.upsert_emotion(
                stable_key, emotion=emotion_label, status=emotion_status,
                cache_key=emotion_key, algorithm_fingerprint=emotion_classifier.fingerprint,
                error=emotion_error,
            )
            if not written:
                logger.warning("情绪未写入（该篇还没有摘要记录，请先跑 --all）entry_id=%s", entry_id)
            record["emotion"] = emotion_label
            record["emotion_status"] = emotion_status
            if record_tracked:
                summary_state.put(entry_id, record)     # 让预览/日志看到情绪

        elapsed = time.monotonic() - started
        done = stats["ok"] + stats["empty"] + stats["failed"]
        avg = elapsed / done if done else 0.0
        rate = done / elapsed * 3600 if elapsed > 0 else 0.0
        eta = avg * max(total - index, 0)

        detail = (
            f"{len(summary_text)}字摘要" if status == "ok"
            else ("空摘要" if status == "empty" else f"失败({error})")
        )
        if summary_skip:
            detail = f"摘要复用（{detail}）"
        emotion_detail = ""
        if do_emotion and emotion_status:
            emotion_detail = f" 情绪:{emotion_label or '无'}"
            if emotion_status != "ok":
                emotion_detail += f"({emotion_status})"
        counters = (
            f"有摘要:{stats['ok']} 空摘要:{stats['empty']} 失败:{stats['failed']} "
            f"跳过:{stats['skipped']}"
        )
        if emotion_active:
            counters += (
                f" 情绪:{stats['emotions']} 情绪失败:{stats['emotion_failed']} "
                f"情绪跳过:{stats['emotion_skipped']}"
            )
        if not quiet:
            emit(
                f"[{index}/{total}] {entry.get('date')} {entry.get('entry_type')} "
                f"{entry.get('word_count')}字 → {detail}{emotion_detail} | 本篇 {entry_elapsed:.1f}s | "
                f"平均 {avg:.1f}s/篇 | 已用 {elapsed / 60:.0f}m | 剩余 ~{eta / 60:.0f}m | "
                f"{counters} | {rate:.0f}条/h"
            )
        snapshot(
            "running", index, entry, entry_elapsed,
            note=f"{entry.get('date')} → {detail}{emotion_detail} ｜ 有摘要 {stats['ok']} ｜ 空摘要 "
                 f"{stats['empty']} ｜ 失败 {stats['failed']} ｜ 跳过 {stats['skipped']}",
        )
        preview_tick(index)

        if consecutive_failures >= bs_config.MAX_CONSECUTIVE_FAILURES:
            logger.error(
                "连续失败 %d 次，停止本轮任务；进度已保存，可直接重跑续跑", consecutive_failures
            )
            completed = False
            break

    stats["elapsed_seconds"] = round(time.monotonic() - started, 1)
    stats["calls"] = int(getattr(client, "call_count", 0))
    stats["completed"] = completed
    if emotion_classifier is not None:
        stats["emotion_calls"] = int(getattr(emotion_classifier, "call_count", 0))
    snapshot(
        "done", total,
        note=f"处理结束：有摘要 {stats['ok']} ｜ 空摘要 {stats['empty']} ｜ 失败 {stats['failed']} "
             f"｜ 跳过 {stats['skipped']}"
             + (f" ｜ 情绪 {stats['emotions']}（失败 {stats['emotion_failed']}）"
                if emotion_classifier is not None else ""),
    )
    return stats


# ---------------- 汇总输出 ----------------

def collect_summaries(summary_state: SummaryView) -> List[Dict]:
    """取出状态里所有已产出的摘要（按日期排序，不调用模型）"""
    return summary_state.summary_records()


def print_summary(records: List[Dict], stats: Optional[Dict] = None):
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


def dump_preview(entry: Dict, raw: str, summary_text: str, emotion: Optional[Dict] = None):
    """--test 用：打印原文片段、模型原始输出、清洗后的摘要与情绪判断"""
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
    if emotion is not None:
        label = emotion.get("emotion") or "（无标签）"
        print(f"情绪判断: {label}（status={emotion.get('status')}）")
        # 用 safe_snippet：模型若复述正文，超过 20 字就只打印长度，不把正文打到终端
        print(f"  情绪原始输出: {emotion_mod.safe_snippet(emotion.get('raw'))}")


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
        args, settings, years,
        phase="loading", phase_note="数据库只读，不会改动日记",
    )   # 只打印，不写任何文件
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
    fingerprint_settings = client_fingerprint_settings(settings, client)
    emotion_classifier, _ = setup_emotion(args, settings, client, model, fingerprint_settings)
    print(
        f"模型: {model} | 地址: {client.base_url} | "
        f"思考: {client.reasoning_effort or '模型默认'} | Prompt 指纹: {prompt_sha1_value}"
    )
    if emotion_classifier.enabled:
        print(
            f"情绪判断: 开启（标签 {'、'.join(settings.get('emotion_labels') or [])}，"
            f"每篇额外一次调用）"
        )
    else:
        print("情绪判断: 关闭（--no-emotion 或 .env 的 EMOTION_ENABLED=0）")
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
        outcome = None
        if emotion_classifier.enabled and (entry.get("content") or "").strip():
            outcome = emotion_classifier.classify(entry)
        dump_preview(entry, raw, summary.summarize_from_response(raw, entry, logger_=logger), outcome)
        reporter.note(f"抽样完成 {index}/{len(samples)}：{entry.get('date')}")

    reporter.set_phase("done", "抽样完成")
    print("")
    print("抽样完成。满意后运行全量：python batch_summary/main.py --all")
    return EXIT_OK


# ---------------- 子命令：全量 / 重建 ----------------

def cmd_all(args, settings, paths: Dict[str, Path]) -> int:
    """--all：全量提取（支持 Ctrl+C 断点续跑；运行期间持续打印人类可读进度）"""
    entry_types = resolve_entry_types(args)
    years = parse_years(args)
    state_mod.setup_logging(quiet=args.quiet)

    reporter = build_reporter(
        args, settings, years,
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

        fingerprint_settings = client_fingerprint_settings(settings, client)
        algorithm = algorithm_payload(fingerprint_settings, model, template)
        algorithm_fp = algorithm_fingerprint(algorithm)
        store = SummaryStore(settings["db_path"])
        store.migrate()
        store.register_algorithm(algorithm_fp, algorithm)
        emotion_classifier, emotion_fp = setup_emotion(
            args, settings, client, model, fingerprint_settings, store=store,
        )
        scope = {"years": years, "entry_types": entry_types, "limit": args.limit,
                 "emotion_only": bool(args.emotion_only)}
        run_id = store.start_run(
            algorithm_fp, scope, len(entries),
            emotion_fingerprint=emotion_fp if emotion_classifier.enabled else None,
        )

        logger.info(
            "开始批量总结 | 模型=%s | 地址=%s | 思考=%s | Prompt指纹=%s | 情绪=%s | 类型=%s | 年份=%s | 条数=%d",
            model, client.base_url, client.reasoning_effort or "模型默认",
            prompt_sha1_value,
            ",".join(settings.get("emotion_labels") or []) if emotion_classifier.enabled else "关闭",
            ",".join(entry_types), years or "全部", len(entries),
        )

        days_total = len({str(e.get("date") or "") for e in entries if e.get("date")})
        reporter.set_total(len(entries), days_total=days_total)

        previous_records = SummaryRepository(settings["db_path"]).all_records()
        summary_state = SummaryView(previous_records)
        previous = {name: sum(r.get("status") == name for r in previous_records)
                    for name in ("ok", "empty", "failed")}
        print(
            f"待处理 {len(entries)} 篇（覆盖 {days_total} 天）| 已有状态: 有摘要 {previous.get('ok', 0)} / "
            f"空摘要 {previous.get('empty', 0)} / 失败 {previous.get('failed', 0)}"
        )
        print("可随时 Ctrl+C 中断：下次重跑同一命令会自动续跑，已处理的条目不会再调用模型")
        if emotion_classifier.enabled:
            print(
                f"情绪判断：每篇额外一次调用（只回一个词）｜标签 "
                f"{'、'.join(settings.get('emotion_labels') or [])}"
                f"{'（复用缓存，仅补缺失）' if args.emotion_only else ''}"
            )
        else:
            print("情绪判断：已关闭（--no-emotion 或 .env 的 EMOTION_ENABLED=0）")
        print(f"运行期间每 {reporter.interval:.0f} 秒自动打印一次状态块（只打印，不写文件）")
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
                store=store, algorithm_fingerprint_value=algorithm_fp, run_id=run_id,
                emotion_classifier=emotion_classifier,
                emotion_only=args.emotion_only, force_emotion=args.force_emotion,
            )
        except KeyboardInterrupt:
            store.update_run(run_id, status="interrupted")
            reporter.stop()
            preview.finish(summary_state, phase="interrupted")
            print("\n\n[中断] 进度已保存：重跑同一命令即可续跑，也可先用 --rebuild-md 查看已有结果。")
            if preview.enabled:
                print(f"[中断] 已总结的内容见：{paths['preview']}")
            return EXIT_OK

        reporter.set_phase("merging", "汇总生成目录，不调用模型")
        if stats["completed"] and not args.limit:
            store.delete_orphans(
                [make_entry_key(entry) for entry in entries],
                years=years, entry_types=entry_types,
            )
        repository = SummaryRepository(settings["db_path"])
        database_records = repository.all_records()
        records = [record for record in database_records if record.get("status") == "ok"]

        reporter.set_phase("saving", "写「中途预览.md」（不调用模型）")

        print_summary(records, stats)
        preview.finish(summary_state, processed=len(entries), total=len(entries), phase="done")
        final_run_status = "completed" if stats["completed"] else "failed"
        store.update_run(run_id, status=final_run_status, processed=len(entries),
                         generated=stats["ok"] + stats["empty"], reused=stats["skipped"],
                         failed=stats["failed"])
        reporter.set_phase("done")
        if preview.enabled:
            print(f"已写出: {paths['preview']}（含本次全部结果）")
        else:
            print("本次未写文件（--no-preview）：结果都在 SQLite 里，可用 --rebuild-md 重写")
        print(f"摘要主存储: {settings['db_path']}")
        return EXIT_OK
    finally:
        reporter.stop()


def cmd_rebuild(args, settings, paths: Dict[str, Path]) -> int:
    """--rebuild-md：不调用模型，用 SQLite 里已有的摘要重写「中途预览.md」"""
    state_mod.setup_logging(quiet=args.quiet)
    reporter = build_reporter(
        args, settings, [],
        phase="loading", phase_note="读取 SQLite 摘要，不调用模型",
    )
    reporter.attach_logger(logger)
    reporter.start()
    print(f"本次运行目录: {paths['dir']}")
    try:
        repository = SummaryRepository(settings["db_path"])
        database_records = repository.all_records()
        if not database_records:
            print(f"[错误] 数据库中未找到摘要：{settings['db_path']}")
            print("请先运行：python batch_summary/main.py --all")
            return EXIT_ERROR

        records = [record for record in database_records if record.get("status") == "ok"]
        state_stats = {name: sum(r.get("status") == name for r in database_records)
                       for name in ("ok", "empty", "failed")}
        reporter.set_total(len(records))
        reporter.update(
            len(records),
            stats={
                "ok": state_stats.get("ok", 0),
                "empty": state_stats.get("empty", 0),
                "failed": state_stats.get("failed", 0),
                "skipped": 0,
                "summaries": len(records),
            },
            note=f"从 SQLite 读入 {len(database_records)} 篇（不调用模型）",
        )
        reporter.set_phase("saving", "写「中途预览.md」（不调用模型）")
        paths["preview"].parent.mkdir(parents=True, exist_ok=True)
        paths["preview"].write_text(render.render_markdown(records), encoding="utf-8")

        print_summary(records)
        reporter.set_phase("done")
        print(f"已重新生成: {paths['preview']}（本次未调用模型）")
        return EXIT_OK
    finally:
        reporter.stop()


# ---------------- 入口 ----------------

def main(argv=None) -> int:
    fix_windows_console()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not (args.models or args.test or args.all or args.rebuild_md or args.reset_summaries):
        parser.print_help()
        print("\n请选择一个动作：--models / --test / --all / --rebuild-md / --reset-summaries")
        return EXIT_ERROR

    # 产物固定写在输出根目录（默认：项目根目录下的 output/），不建时间戳子目录
    paths = resolve_paths(args, timestamped=False)
    try:
        settings = bs_config.get_settings()
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return EXIT_ERROR

    if args.models:
        return cmd_models(args, settings)
    if args.reset_summaries:
        SummaryStore(settings["db_path"]).reset()
        print("已清空摘要相关表；原始日记、FTS 和统计表未修改。")
        return EXIT_OK
    if args.test:
        return cmd_test(args, settings, paths)
    if args.all:
        return cmd_all(args, settings, paths)
    return cmd_rebuild(args, settings, paths)


if __name__ == "__main__":
    sys.exit(main())