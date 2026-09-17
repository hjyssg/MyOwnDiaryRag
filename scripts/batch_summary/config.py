#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 - 配置

复用根目录 ``config.py``（负责读取 .env 中的数据库路径），
在其之上补充本功能需要的 LLM 与处理参数。

各项参数都可以通过在项目根目录 ``.env`` 中追加同名键来覆盖：

    LLM_BASE_URL=http://127.0.0.1:1234/v1
    LLM_MODEL=                  # 留空则自动选择第一个非 embedding 模型
    LLM_TIMEOUT=180
    LLM_MAX_TOKENS=4096
    LLM_TEMPERATURE=0.2
    LLM_JSON_MODE=0             # 1=请求 JSON 模式（部分模型不支持）
    LLM_REASONING_EFFORT=none   # 推理模型思考开关：none=关闭思考；留空=不发送该参数
    EMOTION_ENABLED=1           # 1=每篇额外做一次情绪判断（默认开启）；0=只写摘要
    EMOTION_LABELS=快乐,平淡,悲伤,生气,焦虑,疲惫,期待,其他   # 标签集（最后一项为兜底）
    LLM_EMOTION_MAX_TOKENS=32   # 情绪判断的生成上限（只输出一个词）
    ALLOW_REMOTE_LLM=0          # 保持 0：只用本地模型，拒绝云端地址
    SUMMARY_HEARTBEAT_SECONDS=30 # 运行期间每隔多少秒打印一次状态块
    SUMMARY_PREVIEW_SECONDS=60   # 运行期间每隔多少秒刷新一次 中途预览.md（0 = 关闭）

注意本功能的定位：**每一篇日记都总结**，本地模型只负责"把这篇日记写成一段摘要"，
不负责判断哪些内容重要、也不负责给日期或标题——因此这里没有事件条数、标题长度、
相似度合并之类的参数，只有"摘要多长""正文给模型看多少"这两类旋钮。

旧版（年度日记回顾）用的 ``REVIEW_HEARTBEAT_SECONDS`` / ``REVIEW_PREVIEW_SECONDS``
仍然兼容：新键没配置时读旧键。
"""

import re
from datetime import datetime
from pathlib import Path

import config as root_config

# ---------------- 目录 ----------------
BASE_DIR = Path(__file__).resolve().parent           # scripts/batch_summary
ROOT_DIR = BASE_DIR.parent.parent                    # 项目根目录

# ---------------- 输入 / 输出路径 ----------------
PROMPT_FILE = BASE_DIR / "prompts" / "diary_summary_prompt.txt"
OUTPUT_DIR = BASE_DIR / "output"
# 每次运行的产物放在 output/YYMMDDHHMMSS/ 子目录里，互不覆盖，便于回头对比
RUN_DIR_FORMAT = "%y%m%d%H%M%S"
STATE_FILE_NAME = "summary_state.json"       # 断点续跑状态：固定在 output/ 根目录（跨运行共享）
STATUS_FILE_NAME = "运行状态.txt"             # 最新状态块：双击即可查看，不需要任何命令
MARKDOWN_FILE_NAME = "日记总结.md"            # 最终产物：按年份排列的逐篇摘要
SUMMARIES_FILE_NAME = "summaries.json"       # 结构化中间结果（每篇一条摘要记录）
LOG_FILE_NAME = "batch_summary.log"
PENDING_MD_NAME = "待复核_未产出摘要.md"       # 处理失败/空摘要的日记（含原文）
PENDING_JSON_NAME = "待复核_未产出摘要.json"
LOG_FILE = OUTPUT_DIR / LOG_FILE_NAME
STATE_FILE = OUTPUT_DIR / STATE_FILE_NAME    # 兼容旧引用（state.SummaryState 默认路径）

# ---------------- 实时进度（心跳） ----------------
# 主程序运行期间每隔多少秒打印一次"人类可读状态块"（可 --heartbeat 覆盖，.env 亦可用
# SUMMARY_HEARTBEAT_SECONDS 覆盖）；HEARTBEAT_MIN_SECONDS 防止把终端刷爆。
HEARTBEAT_SECONDS = 30
HEARTBEAT_MIN_SECONDS = 5

# ---------------- 中途预览（运行期间可随时打开） ----------------
# 全量跑要几小时，最终 日记总结.md 只在整轮结束后写一次；因此运行期间额外维护一份
# "截至当前"的 中途预览.md（可 --preview-every 覆盖，.env 亦可用 SUMMARY_PREVIEW_SECONDS 覆盖），
# 随时用编辑器打开就能看到已总结完的部分，不用等跑完。
PREVIEW_FILE_NAME = "中途预览.md"            # 放在本次运行目录里，与最终产物并存
PREVIEW_EVERY_SECONDS = 60                   # 每隔多少秒刷新一次（0 = 关闭）
PREVIEW_MIN_SECONDS = 5                      # 刷新间隔下限，防止把磁盘写爆

# ---------------- LLM（.env 可覆盖） ----------------
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:1234/v1"
# 摘要比"事件标题"长得多，单篇耗时也更长，故超时与 token 预算都比旧版宽松
DEFAULT_LLM_TIMEOUT = 180.0            # 单次请求超时（秒）
# 推理模型（Qwen3 等）会先输出思考再输出正文：预算太小会把 token 全花在思考上，
# 导致 message.content 为空（finish_reason=length）。故默认给足预算。
DEFAULT_LLM_MAX_TOKENS = 4096
DEFAULT_LLM_TEMPERATURE = 0.2
DEFAULT_LLM_JSON_MODE = False          # 摘要直接输出纯文本，不需要 JSON 模式
# 思考开关："" = 请求里不带该参数（留给模型默认，兼容非推理模型）；
#              "none" = 关闭思考（对推理模型最省时省 token，推荐）
DEFAULT_LLM_REASONING_EFFORT = ""
# 允许取值（"" 表示不发送该参数）
REASONING_EFFORT_CHOICES = ("none", "minimal", "low", "medium", "high")
# 允许的本地地址（host 部分）
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

# ---------------- 摘要与正文 ----------------
MAX_SUMMARY_CHARS = 60                 # 单篇摘要硬上限：Prompt 要求 20~40 字（最多 50），超出按句读截断
CONTENT_HEAD_CHARS = 4000              # 超长正文保留前部
CONTENT_TAIL_CHARS = 1000              # 超长正文保留后部
# 模型的"空答案"：清洗后与这些完全相等时视为没有摘要（记为 empty，进"待复核"清单）
REJECT_SUMMARIES = {
    "无", "无。", "没有", "暂无", "无内容", "无摘要", "无法总结", "空",
    "none", "null", "nan", "na", "n/a", "-", "—", "……", "...",
}

# ---------------- 情绪分类（.env 可覆盖） ----------------
# 与摘要各自独立：每篇在摘要之后额外发一次很短的询问，只让它回一个标签词。
# 标签集来自根 .env 的 EMOTION_LABELS（根 config.get_emotion_labels()），
# batch 与 Web 共用同一份定义，改一处两边同步。
EMOTION_PROMPT_FILE = BASE_DIR / "prompts" / "diary_emotion_prompt.txt"
EMOTION_LABEL_VERSION = "emotion-labels-v1"   # 归一化规则变化时递增（会让情绪重算）
DEFAULT_EMOTION_ENABLED = True                # EMOTION_ENABLED=0 可关闭（老库改造前想纯跑摘要时用）
EMOTION_LABELS = tuple(root_config.get_emotion_labels())
EMOTION_FALLBACK = EMOTION_LABELS[-1]         # 无法归类时的兜底标签（约定取标签集最后一项）
DEFAULT_EMOTION_MAX_TOKENS = 32               # 只输出一个词，32 足够
DEFAULT_EMOTION_TEMPERATURE = 0.0             # 分类任务取样温度：0 更稳定
EMOTION_MAX_OUTPUT_CHARS = 40                 # 子串兜底匹配的长度上限（输出太长就不猜）
# 别名 -> 标准标签（模型偶尔会写"开心""郁闷"这类词；命中别名就归一化）
EMOTION_ALIASES = {
    "高兴": "快乐", "开心": "快乐", "愉快": "快乐", "喜悦": "快乐", "兴奋": "快乐",
    "幸福": "快乐", "欢乐": "快乐", "满足": "快乐", "轻松": "快乐", "惊喜": "快乐",
    "愉快的一天": "快乐", "爽": "快乐",
    "平静": "平淡", "平常": "平淡", "普通": "平淡", "中性": "平淡", "无聊": "平淡",
    "一般": "平淡", "日常": "平淡", "寻常": "平淡", "无": "平淡", "没什么": "平淡",
    "难过": "悲伤", "伤心": "悲伤", "低落": "悲伤", "沮丧": "悲伤", "悲哀": "悲伤",
    "痛苦": "悲伤", "忧郁": "悲伤", "抑郁": "悲伤", "郁闷": "悲伤", "失落": "悲伤",
    "心碎": "悲伤", "想哭": "悲伤",
    "愤怒": "生气", "恼火": "生气", "气愤": "生气", "火大": "生气", "恼怒": "生气",
    "不爽": "生气", "吵架": "生气",
    "担心": "焦虑", "担忧": "焦虑", "紧张": "焦虑", "不安": "焦虑", "烦躁": "焦虑",
    "心焦": "焦虑", "压力": "焦虑", "害怕": "焦虑", "恐惧": "焦虑", "恐慌": "焦虑",
    "累": "疲惫", "疲劳": "疲惫", "疲倦": "疲惫", "困": "疲惫", "精疲力尽": "疲惫",
    "心力交瘁": "疲惫", "疲惫不堪": "疲惫",
    "期盼": "期待", "盼望": "期待", "憧憬": "期待", "向往": "期待", "希望": "期待",
    "混合": "其他", "复杂": "其他", "矛盾": "其他", "无法判断": "其他", "未知": "其他",
}

# ---------------- 调用与可靠性 ----------------
REQUEST_INTERVAL_SECONDS = 0.5         # 两次请求之间的最小间隔
MAX_RETRIES = 3                        # 单篇最多尝试次数（含首次）
RETRY_BACKOFF_BASE = 2.0               # 重试退避基数（秒）
MAX_CONSECUTIVE_FAILURES = 5           # 连续失败达到此数则停止整轮任务
STATE_SAVE_EVERY = 20                  # 每处理 N 篇落一次状态（防中断丢进度）
RANDOM_SEED = 20260101                 # --test 抽样用的固定随机种子

# ---------------- 默认处理范围 ----------------
# 默认排除 stock_diary（620 条日常炒股流水），需要时用 --types/--include-stock 纳入
DEFAULT_ENTRY_TYPES = ("single_day", "multi_day", "note", "retrospective", "summary")
ALL_ENTRY_TYPES = ("single_day", "multi_day", "stock_diary", "note", "retrospective", "summary")


def _env_str(env, key, default=""):
    value = (env.get(key) or "").strip()
    return value or default


def _env_float(env, key, default):
    try:
        return float(env.get(key, ""))
    except (TypeError, ValueError):
        return float(default)


def _env_int(env, key, default):
    try:
        return int(float(env.get(key, "")))
    except (TypeError, ValueError):
        return int(default)


def _env_bool(env, key, default=False):
    value = (env.get(key) or "").strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "y", "on"}


def get_settings():
    """读取根 .env（经由根 config.py）并合并本功能的 LLM 配置"""
    env = root_config.load_env()
    try:
        db_path = root_config.get_database_path()
    except Exception as exc:  # .env 缺失或路径未配置
        raise RuntimeError(f"读取数据库路径失败，请检查项目根目录 .env：{exc}") from exc

    return {
        "db_path": Path(db_path),
        "llm_base_url": _env_str(env, "LLM_BASE_URL", DEFAULT_LLM_BASE_URL).rstrip("/"),
        "llm_model": _env_str(env, "LLM_MODEL", ""),
        "llm_timeout": _env_float(env, "LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT),
        "llm_max_tokens": _env_int(env, "LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS),
        "llm_temperature": _env_float(env, "LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE),
        "llm_json_mode": _env_bool(env, "LLM_JSON_MODE", DEFAULT_LLM_JSON_MODE),
        "llm_reasoning_effort": _env_str(
            env, "LLM_REASONING_EFFORT", DEFAULT_LLM_REASONING_EFFORT
        ).lower(),
        "allow_remote_llm": _env_bool(env, "ALLOW_REMOTE_LLM", False),
        "emotion_enabled": _env_bool(env, "EMOTION_ENABLED", DEFAULT_EMOTION_ENABLED),
        "emotion_labels": list(EMOTION_LABELS),
        "emotion_fallback": EMOTION_FALLBACK,
        "emotion_label_version": EMOTION_LABEL_VERSION,
        "emotion_temperature": DEFAULT_EMOTION_TEMPERATURE,
        "emotion_max_tokens": _env_int(env, "LLM_EMOTION_MAX_TOKENS", DEFAULT_EMOTION_MAX_TOKENS),
        "content_head_chars": CONTENT_HEAD_CHARS,
        "content_tail_chars": CONTENT_TAIL_CHARS,
        "max_summary_chars": MAX_SUMMARY_CHARS,
        # 心跳间隔：SUMMARY_HEARTBEAT_SECONDS 优先，其次兼容旧的 REVIEW_HEARTBEAT_SECONDS
        "heartbeat_seconds": _env_int(
            env, "SUMMARY_HEARTBEAT_SECONDS",
            _env_int(env, "REVIEW_HEARTBEAT_SECONDS", HEARTBEAT_SECONDS),
        ),
        # 中途预览刷新间隔（秒），0 = 关闭（见 --preview-every / --no-preview）
        "preview_every_seconds": _env_int(
            env, "SUMMARY_PREVIEW_SECONDS",
            _env_int(env, "REVIEW_PREVIEW_SECONDS", PREVIEW_EVERY_SECONDS),
        ),
    }


def ensure_output_dir(output_dir=None) -> Path:
    """确保输出目录存在，返回该目录"""
    target = Path(output_dir) if output_dir else OUTPUT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def new_run_dir(base_dir=None, now=None) -> Path:
    """为本次运行创建 ``<base_dir>/YYMMDDHHMMSS/`` 子目录并返回

    每次运行一个独立子目录，历史产物互不覆盖；同一秒重复运行会追加 ``-2``、``-3``。
    """
    base = ensure_output_dir(base_dir)
    stamp = (now or datetime.now()).strftime(RUN_DIR_FORMAT)
    target = base / stamp
    suffix = 1
    while target.exists():
        suffix += 1
        target = base / f"{stamp}-{suffix}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def list_run_dirs(base_dir=None) -> list:
    """列出历史运行目录（新→旧）；``--flat-output`` 直接写在根目录的不算运行目录"""
    base = Path(base_dir) if base_dir else OUTPUT_DIR
    if not base.exists():
        return []
    pattern = re.compile(r"^\d{12}(-\d+)?$")
    return sorted(
        [d for d in base.iterdir() if d.is_dir() and pattern.match(d.name)],
        key=lambda d: d.name,
        reverse=True,
    )

