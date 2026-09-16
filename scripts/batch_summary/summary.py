#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 装载 + 模型摘要清洗

本功能不让本地模型做任何"判断"（哪些内容重要、日期是哪天），
模型只负责一件事：**把这篇日记写成一段摘要**。其余全部由 Python 负责：

1. 剥离 markdown 代码块、``摘要：``之类前缀、列表符号与包裹引号；
2. 压缩空白——输出是"一篇一行"的目录，摘要统一压成单行；
3. 去掉开头重复的日期/时间铺垫（行首已经有 ``MMDD`` 标签，实测模型爱复述日期）；
4. 把句首的"作者/笔者"改回"我"（实测模型爱用第三人称）；
5. 丢掉末尾那句对日记/摘要本身的评述（"内容简洁且完整反映了原文"之类）；
6. 明显的空答案（``无`` / ``none`` 等）视为没有摘要，记为 ``empty``；
7. 超过 ``MAX_SUMMARY_CHARS`` 的摘要按句读截断，保证一行读得下去。

日期一律取数据库里这条日记的日期，不从模型输出里解析，因此这里没有日期解析、
标题校验、事件结构校验之类的代码。
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, Optional

from scripts.batch_summary import config as bs_config

logger = logging.getLogger(__name__)

# 代码块 / "摘要：" 前缀 / 列表与标题符号 / 需要剥掉的包裹字符
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.S)
_LABEL_RE = re.compile(
    r"^\s*(?:摘要|总结|简介|概要|内容摘要|日记摘要|summary|abstract)\s*[:：]\s*",
    re.I,
)
_MARK_PREFIX_RE = re.compile(r"^\s*(?:[-*+•·>]+|\d+[.)、]|#+)\s*")
_WRAP_CHARS = "\u201c\u201d\"'\u2018\u2019\u300c\u300d\u300e\u300f\u300a\u300b` \u3000"
_SENTENCE_ENDS = ("\u3002", "\uff01", "\uff1f", "\uff1b", ".", "!", "?", ";")
_MIN_KEEP_CHARS = 12                   # 截断兜底：至少保留这么多字的整句

# 摘要开头重复的日期/时间铺垫（行首已经有 MMDD 标签，再写一遍纯属浪费字数）
_LEADING_TIME_RES = (
    re.compile(
        r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]?"
        r"\s*(?:下午|上午|中午|晚上|傍晚|凌晨|早上|夜里)?"
        r"\s*的?\s*(?:这一天|这天|当天|当日|当晚)?\s*[，,、：:。]?\s*"
    ),
    re.compile(
        r"^\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}\s*[日号]?"
        r"\s*(?:下午|上午|中午|晚上|傍晚|凌晨|早上|夜里)?"
        r"\s*的?\s*(?:这一天|这天|当天|当日|当晚)?\s*[，,、：:。]?\s*"
    ),
    re.compile(r"^\d{1,2}\s*月\s*\d{1,2}\s*[日号]\s*的?\s*[，,、：:。]?\s*"),
    re.compile(r"^(?:这一天|这天|当日|当天|当晚)\s*[，,、：:]\s*"),
)
# 句首的"作者/笔者"改回"我"（实测模型爱用第三人称）
# 规则：只改行首或标点之后的；"这本书的作者"这种被修饰的写法不动
_AUTHOR_SELF_RE = re.compile(r"(^|[，,。；;！!？?：:])\s*(?:作者|笔者)")
# 末尾对日记/摘要本身的评述（实测小模型很爱写这些凑字数的话）
_META_TAIL_RE = re.compile(
    r"(?:整篇日记|整体来看|内容(?:简洁|完整)|完整(?:地)?反映|未涉及其他|"
    r"没有其他额外|仅记录了上述|以上(?:便是|就是)全部)"
)


def _strip_leading_time(text: str) -> str:
    """去掉开头重复的日期/时间铺垫（命中一条即停）"""
    for pattern in _LEADING_TIME_RES:
        stripped = pattern.sub("", text, count=1).strip()
        if stripped != text:
            return stripped
    return text


def _drop_meta_tail(text: str) -> str:
    """丢掉末尾那句"对日记或摘要本身的评述"（允许多句连续命中，最多丢 3 句）

    形如"整篇日记主要记录了……""内容简洁且完整反映了原文""未涉及其他额外的人物"。
    只处理最后一（几）句，且丢完必须还剩内容，避免把整条摘要丢空。
    """
    for _ in range(3):
        parts = [part for part in re.split(r"(?<=[。！？!?；;])", text) if part.strip()]
        if len(parts) < 2 or not _META_TAIL_RE.search(parts[-1]):
            break
        remaining = "".join(parts[:-1]).strip()
        if not remaining:
            break
        text = remaining
    return text


# ---------------- Prompt ----------------

def load_prompt_template(path: Optional[Path] = None) -> str:
    """读取 Prompt 文本（独立配置文件，改 Prompt 不需要改代码）"""
    prompt_path = Path(path) if path else bs_config.PROMPT_FILE
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在：{prompt_path}")
    text = prompt_path.read_text(encoding="utf-8").strip()
    missing = [token for token in ("{DATE}", "{CONTENT}") if token not in text]
    if missing:
        raise ValueError(f"Prompt 文件缺少占位符 {missing}：{prompt_path}")
    return text


def prompt_sha1(template: str) -> str:
    """Prompt 指纹（用于记录/判断 Prompt 是否变化）"""
    return hashlib.sha1(template.encode("utf-8")).hexdigest()[:12]


def prompt_sha1_from_file(path: Optional[Path] = None) -> str:
    return prompt_sha1(load_prompt_template(path))


def truncate_content(content: str) -> str:
    """超长正文：保留前 CONTENT_HEAD_CHARS + 后 CONTENT_TAIL_CHARS

    绝大部分日记（实测本库平均 223 字）都完整进 Prompt；只有少数上万字的长篇
    会被截断——要完整喂进去就必须同步放大 LM Studio 的 Context Length。
    """
    text = (content or "").strip()
    total = bs_config.CONTENT_HEAD_CHARS + bs_config.CONTENT_TAIL_CHARS
    if len(text) <= total:
        return text
    return (
        text[: bs_config.CONTENT_HEAD_CHARS]
        + "\n\n...[中间省略]...\n\n"
        + text[-bs_config.CONTENT_TAIL_CHARS :]
    )


def build_prompt(template: str, entry: Dict, *, truncate: bool = True) -> str:
    """把日记信息填入 Prompt 模板

    使用 str.replace 而非 str.format，避免模板里的花括号需要转义。
    """
    content = entry.get("content") or ""
    if truncate:
        content = truncate_content(content)
    return (
        template.replace("{DATE}", str(entry.get("date") or ""))
        .replace("{ENTRY_TYPE}", str(entry.get("entry_type") or ""))
        .replace("{CONTENT}", content)
    )


# ---------------- 摘要清洗 ----------------

def truncate_summary(text: str) -> str:
    """超过 ``MAX_SUMMARY_CHARS`` 时按句读截断（优先留整句，其次保留第一句，最后才省略号）"""
    limit = int(bs_config.MAX_SUMMARY_CHARS or 0)
    if limit <= 0 or len(text) <= limit:
        return text
    clipped = text[:limit]
    ends = [index for index in (clipped.rfind(mark) for mark in _SENTENCE_ENDS) if index >= 0]
    if ends:
        usable = [index for index in ends if index >= limit // 3]   # 句读太靠前就不是好截点
        if usable:
            return clipped[: max(usable) + 1]
        first = min(ends)
        if first >= _MIN_KEEP_CHARS:        # 宁可只留第一句完整的话，也不要半句
            return clipped[: first + 1]
    return clipped.rstrip("\uff0c,\u3001;\uff1b:\uff1a ") + "\u2026"


def clean_summary(raw_text) -> str:
    """把模型输出清洗成"一行摘要"；清洗后为空表示没有产出摘要

    * 取出代码块里的内容（模型偶尔会把摘要包在 ``` 里）；
    * 去掉 ``摘要：`` 之类前缀与列表符号/标题符号；
    * 去掉包裹引号，把换行与连续空白压成单个空格；
    * 去掉开头重复的日期/时间铺垫：句首的"作者/笔者"改成"我"；
    * 丢掉末尾那句对日记/摘要本身的评述（如"内容简洁且完整反映了原文"）；
    * 按 ``MAX_SUMMARY_CHARS`` 截断。
    """
    text = str(raw_text or "")
    if not text.strip():
        return ""

    fenced = _FENCE_RE.search(text)
    if fenced and fenced.group(1).strip():
        text = fenced.group(1)

    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _MARK_PREFIX_RE.sub("", line).strip()
        if line:
            lines.append(line)
    text = " ".join(lines)

    text = _LABEL_RE.sub("", text).strip()
    text = text.strip(_WRAP_CHARS).strip()
    text = re.sub(r"\s+", " ", text).strip()
    text = _strip_leading_time(text)
    text = _AUTHOR_SELF_RE.sub(r"\1我", text)
    text = _drop_meta_tail(text).strip()
    return truncate_summary(text)


def is_blank_summary(text: str) -> bool:
    """是否为"没有摘要"（空、纯符号，或模型常见的空答案如 ``无`` / ``none``）"""
    value = str(text or "").strip()
    if not value:
        return True
    if value.lower().strip("\u3002\uff01\uff1f!?.") in bs_config.REJECT_SUMMARIES:
        return True
    return not re.search(r"[\w\u4e00-\u9fff]", value)


def summarize_from_response(raw_text: str, entry: Dict, logger_=None) -> str:
    """从模型原始输出得到摘要；没有可用摘要时返回空字符串（调用方记为 empty）

    "没有可用摘要"包括三类：模型输出为空、清洗后只剩空答案（``无`` / ``none``）、
    清洗后只剩标点或 emoji。
    """
    log = logger_ or logger
    text = clean_summary(raw_text)
    if is_blank_summary(text):
        log.warning(
            "模型没有产出可用摘要（entry_id=%s）：%r",
            entry.get("id"), (raw_text or "")[:120],
        )
        return ""
    return text


__all__ = [
    "build_prompt",
    "clean_summary",
    "is_blank_summary",
    "load_prompt_template",
    "prompt_sha1",
    "prompt_sha1_from_file",
    "summarize_from_response",
    "truncate_content",
    "truncate_summary",
]

