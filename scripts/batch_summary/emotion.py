#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪分类：Prompt 装载 + 标签归一 + 独立缓存键

与 :mod:`scripts.batch_summary.summary` 的分工：

* 摘要：模型写一段话，Python 负责清洗成一行；
* 情绪：模型**只回一个词**，Python 负责把它归一化到 .env 里定义的标签集。

归一化顺序（命中即停）：

1. 精确匹配标签（``快乐``）；
2. 精确匹配别名（``开心`` → ``快乐``）；
3. 输出里包含某个标签（模型多写了半句解释）；
4. 输出里包含某个别名（同上，但只在前两类都没命中时猜，且输出不能太长）；
5. 都不中 → 兜底标签（标签集最后一项，默认 ``其他``），并记一条 warning 便于调 Prompt。

情绪与摘要各有独立的算法指纹与缓存键（见
:func:`summary_fingerprint.emotion_payload`）：

* 补情绪、改标签集、改情绪 Prompt、换模型 → 只让**情绪**重算，摘要一条都不失效；
* 正文变化 → 情绪与摘要一起失效（都由 ``source_hash`` 决定）。
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from scripts.batch_summary import config as bs_config
from scripts.batch_summary import summary as summary_mod
from scripts.batch_summary.llm import LLMError
from summary_fingerprint import EMOTION_CACHE_NAMESPACE, cache_key as make_cache_key

logger = logging.getLogger("scripts.batch_summary")

_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.S)
_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:情绪|情感|心情|标签|分类|emotion|mood|label)\s*[:：]?\s*", re.I
)
_WRAP_CHARS = "\u201c\u201d\"'`\u300c\u300d\u300e\u300f\u300a\u300b\u3000"
_TRAIL_CHARS = "\u3002\uff01\uff1f\uff1b:\uff1a,\uff0c\u3001.\\!?;~ \t\r\n"
# 这类整句回答本身就在说"我判断不了"，不要再用子串去猜标签
_HARD_TO_GUESS_MARKERS = ("无法判断", "不确定", "不能确定")
# 日志/终端里最多出现多少字的模型输出（情绪模型理论上只该回一个词）
_LOG_SNIPPET_CHARS = 20


def safe_snippet(text, *, limit: int = _LOG_SNIPPET_CHARS) -> str:
    """把模型输出压成"可以安全写进日志"的短片段

    情绪模型理论上只回一个词；万一它不听话、复述了日记原文，把这段文字写进日志
    就等于把正文落盘。因此超过 ``limit`` 字时只记长度，**不记内容**。
    """
    value = " ".join(str(text or "").split())
    if not value:
        return "（空）"
    if len(value) > limit:
        return f"（{len(value)} 字的整句回答，内容已省略，避免把日记正文写进日志）"
    return value


def load_prompt_template(path: Optional[Path] = None) -> str:
    """读取情绪 Prompt 模板（独立配置文件；改 Prompt 不需要改代码）"""
    prompt_path = Path(path) if path else bs_config.EMOTION_PROMPT_FILE
    if not prompt_path.exists():
        raise FileNotFoundError(f"情绪 Prompt 文件不存在：{prompt_path}")
    text = prompt_path.read_text(encoding="utf-8").strip()
    missing = [token for token in ("{DATE}", "{CONTENT}", "{LABELS}") if token not in text]
    if missing:
        raise ValueError(f"情绪 Prompt 文件缺少占位符 {missing}：{prompt_path}")
    return text


def prompt_sha1(template: str) -> str:
    """Prompt 指纹（与摘要同一个实现，便于状态文件对照）"""
    return summary_mod.prompt_sha1(template)


def format_labels(labels: Optional[Sequence[str]] = None) -> str:
    """渲染 ``{LABELS}`` 占位符：``快乐 / 平淡 / ...``"""
    return " / ".join(str(label) for label in (labels or bs_config.EMOTION_LABELS))


def build_prompt(template: str, entry: Dict, *, labels: Optional[Sequence[str]] = None,
                 truncate: bool = True) -> str:
    """把日记信息填入情绪 Prompt（正文截断规则与摘要完全一致）"""
    prompt = summary_mod.build_prompt(template, entry, truncate=truncate)
    return prompt.replace("{LABELS}", format_labels(labels))


# ---------------- 标签归一 ----------------

def clean_label(raw) -> str:
    """把模型原始输出压成"一行一个短词"：取代码块内容 / 第一行，剥前缀、引号与标点"""
    text = str(raw or "")
    if not text.strip():
        return ""
    fenced = _FENCE_RE.search(text)
    if fenced and fenced.group(1).strip():
        text = fenced.group(1)
    first_line = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            first_line = line
            break
    label = _LABEL_PREFIX_RE.sub("", first_line).strip()
    label = label.strip(_WRAP_CHARS).strip()
    return label.strip(_TRAIL_CHARS).strip()


def normalize_emotion(raw, *, labels: Optional[Sequence[str]] = None,
                      aliases: Optional[Dict[str, str]] = None,
                      fallback: Optional[str] = None) -> Tuple[str, str]:
    """把模型输出归一成一个合法标签

    返回 ``(标签, 归一前的中间形式)``；第二个值仅用于日志/诊断。
    """
    label_list = [str(label) for label in (labels or bs_config.EMOTION_LABELS)]
    alias_map = dict(bs_config.EMOTION_ALIASES if aliases is None else aliases)
    final = str(fallback or label_list[-1])

    def accept(label: str) -> Optional[str]:
        """别名映射结果必须仍在标签集内（标签集被改过时忽略这条别名）"""
        return label if label in label_list else None

    text = clean_label(raw)
    if not text:
        return final, ""
    if text in label_list:
        return text, text
    if text in alias_map:
        mapped = accept(alias_map[text])
        if mapped:
            return mapped, text
    compact = re.sub(r"\s+", "", text)
    if compact in label_list:
        return compact, compact
    if compact in alias_map:
        mapped = accept(alias_map[compact])
        if mapped:
            return mapped, compact
    if len(compact) <= bs_config.EMOTION_MAX_OUTPUT_CHARS and not any(
        marker in compact for marker in _HARD_TO_GUESS_MARKERS
    ):
        for label in label_list:
            if label in compact:
                return label, compact
        for alias, label in alias_map.items():
            if alias in compact:
                mapped = accept(label)
                if mapped:
                    return mapped, compact
    return final, compact


# ---------------- 每次运行的情绪判断器 ----------------

class EmotionClassifier:
    """某一轮运行的情绪判断器（持有 client、Prompt、标签集与算法指纹）

    ``enabled=False``（``--no-emotion`` 或 ``EMOTION_ENABLED=0``）时主程序直接跳过情绪环节。
    """

    def __init__(self, client, template: str, *, fingerprint: str,
                 labels: Optional[Sequence[str]] = None,
                 fallback: Optional[str] = None,
                 max_tokens: Optional[int] = None,
                 enabled: bool = True,
                 logger_=None):
        self.client = client
        self.template = template
        self.fingerprint = fingerprint
        self.labels = [str(label) for label in (labels or bs_config.EMOTION_LABELS)]
        self.fallback = str(fallback or self.labels[-1])
        self.max_tokens = int(max_tokens or bs_config.DEFAULT_EMOTION_MAX_TOKENS)
        self.enabled = bool(enabled)
        self.log = logger_ or logger
        self.call_count = 0

    def cache_key(self, entry_key_value: str, source_hash_value: str) -> str:
        """情绪缓存键（与摘要缓存键同一个函数，只是命名空间不同）"""
        return make_cache_key(entry_key_value, source_hash_value, self.fingerprint,
                              namespace=EMOTION_CACHE_NAMESPACE)

    def classify(self, entry: Dict) -> Dict:
        """调用模型判断情绪；返回 ``{"emotion", "status", "error", "raw"}``

        ``status``：``ok`` = 有标签（含兜底）｜``failed`` = 调用失败（下次重跑重试）。
        空正文由调用方直接记为 ``empty``，不会走到这里。
        """
        prompt = build_prompt(self.template, entry, labels=self.labels)
        try:
            raw = self.client.chat(
                prompt,
                max_tokens=self.max_tokens,
                temperature=bs_config.DEFAULT_EMOTION_TEMPERATURE,
                json_mode=False,
            )
            self.call_count += 1
        except LLMError as exc:
            return {"emotion": "", "status": "failed", "error": str(exc), "raw": ""}
        except Exception as exc:   # 任何意外都不应中断整轮任务
            return {"emotion": "", "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}", "raw": ""}
        emotion, note = normalize_emotion(raw, labels=self.labels, fallback=self.fallback)
        if emotion == self.fallback and note != self.fallback:
            # 只记"安全的短片段"：模型若复述了日记正文，超过 20 字就只记长度
            self.log.warning(
                "情绪标签无法归一，回退为 %s（entry_id=%s，模型输出=%s）",
                self.fallback, entry.get("id"), safe_snippet(raw),
            )
        return {"emotion": emotion, "status": "ok", "error": None, "raw": raw or ""}


__all__ = [
    "EmotionClassifier",
    "build_prompt",
    "clean_label",
    "format_labels",
    "load_prompt_template",
    "normalize_emotion",
    "prompt_sha1",
    "safe_snippet",
]
