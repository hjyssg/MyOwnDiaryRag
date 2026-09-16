#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记总结 Markdown 生成

输出格式（按年份从早到晚，年内按日期从早到晚，每篇日记一行）：

    # 日记总结

    > 每篇日记一段摘要；日期取自日记本身的日期（MMDD）。同一天有多篇日记时各占一行。

    ## 2015年

    - 0120 今天去公园散步，全家都很伤心……
    - 0303 周末去郊外走了两天，天气很好……
    - 0101 新年回顾：去年的计划完成了大半……

日期标签直接取数据库里的日期（``MMDD``），不问模型，也不做区间合并：
每篇日记都有自己的一行摘要。
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

DEFAULT_TITLE = "# 日记总结"
UNKNOWN_LABEL = "日期不详"
HEADER_NOTE = "> 每篇日记一段摘要；日期取自日记本身的日期（MMDD）。同一天有多篇日记时各占一行。"

_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")


def year_of(record: Dict) -> int:
    """记录所属年份（优先 entry_date，取不到时退回记录里的 year 字段）"""
    match = _DAY_RE.match(str(record.get("entry_date") or ""))
    if match:
        return int(match.group(1))
    try:
        return int(record.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def format_date_label(record: Dict) -> str:
    """把数据库日期转成 'MMDD'（只有年月时用 'MM月'，都没有时用 '日期不详'）"""
    value = str(record.get("entry_date") or "")
    match = _DAY_RE.match(value)
    if match:
        return f"{match.group(2)}{match.group(3)}"
    match = _MONTH_RE.match(value)
    if match:
        return f"{match.group(2)}月"
    return UNKNOWN_LABEL


def render_sections(records: List[Dict]) -> List[str]:
    """年份小标题 + 每篇一行摘要（``render_markdown`` 与中途预览共用，正文永远一致）"""
    lines: List[str] = []
    current_year = None

    for record in records:
        summary = str(record.get("summary") or "").strip()
        if not summary:
            continue
        year = year_of(record)
        if year != current_year:
            if current_year is not None:
                lines.append("")
            lines.append(f"## {year}年" if year else "## 年份不详")
            lines.append("")
            current_year = year
        lines.append(f"- {format_date_label(record)} {summary}")
    return lines


def render_markdown(records: List[Dict], title: str = DEFAULT_TITLE) -> str:
    """生成最终 Markdown 文本"""
    lines = [title.strip(), "", HEADER_NOTE, ""] + render_sections(records)
    return "\n".join(lines).rstrip() + "\n"


def count_lines(markdown: str) -> int:
    """摘要行数（不含标题/空行），用于控制台汇总"""
    return sum(1 for line in markdown.splitlines() if line.startswith("- "))


def summarize_years(records: List[Dict]) -> Dict[int, int]:
    """每年摘要条数（供控制台汇总）"""
    summary: Dict[int, int] = {}
    for record in records:
        if not str(record.get("summary") or "").strip():
            continue
        year = year_of(record)
        summary[year] = summary.get(year, 0) + 1
    return dict(sorted(summary.items()))


# ---------------- 中途预览（运行期间可随时打开） ----------------

PREVIEW_TITLE = "# 日记总结（中途预览）"

_NOTE_RUNNING = "> 这是运行中的快照（每 {every} 秒自动更新）；完整结果以同目录的 日记总结.md 为准。"
_NOTE_RUNNING_NO_EVERY = "> 这是运行中的快照；完整结果以同目录的 日记总结.md 为准。"
_NOTE_INTERRUPTED = "> 任务已中断：这是中断时的快照，重跑同一命令即可续跑；完整结果以同目录的 日记总结.md 为准。"
_NOTE_DONE = "> 任务已完成：完整结果以同目录的 日记总结.md 为准。"
_NOTE_EMPTY = "> 目前还没有摘要（已处理的日记都是空正文，或都还没返回）。"


def preview_header(
    *,
    processed: int = 0,
    total: int = 0,
    current: Optional[Dict] = None,
    phase: str = "running",
    every: Optional[float] = None,
    now=None,
) -> str:
    """中途预览的头部（标题 + 两行引用说明），末尾带换行

    头部只讲"进度到哪了"，正文完全由 :func:`render_sections` 负责，
    因此中途看到的目录与跑完后的 ``日记总结.md`` 逐行一致。
    """
    stamp = (now or datetime.now()).strftime("%H:%M:%S")
    percent = (int(processed) / int(total) * 100) if int(total) > 0 else 0.0
    head = f"> 截至 {stamp} ｜ 已处理 {int(processed)} / {int(total)} 篇（{percent:.1f}%）"
    if current:
        head += (
            f" ｜ 正在处理 {current.get('date')} {current.get('entry_type')} "
            f"{current.get('word_count')}字"
        )

    if phase == "interrupted":
        note = _NOTE_INTERRUPTED
    elif phase == "done":
        note = _NOTE_DONE
    elif every:
        note = _NOTE_RUNNING.format(every=f"{float(every):g}")
    else:
        note = _NOTE_RUNNING_NO_EVERY
    return f"{PREVIEW_TITLE}\n\n{head}\n{note}\n"


def compose_preview(header: str, sections: List[str]) -> str:
    """头部 + 正文（正文为空时补一句说明），返回完整预览文本"""
    lines = [header.rstrip(), ""]
    if sections:
        lines.extend(sections)
    else:
        lines.append(_NOTE_EMPTY)
    return "\n".join(lines).rstrip() + "\n"


def render_preview(
    records: List[Dict],
    *,
    processed: int = 0,
    total: int = 0,
    current: Optional[Dict] = None,
    phase: str = "running",
    every: Optional[float] = None,
    now=None,
) -> str:
    """生成"中途预览"文本（运行期间由主程序节流刷新，可随时打开）"""
    header = preview_header(
        processed=processed, total=total, current=current,
        phase=phase, every=every, now=now,
    )
    return compose_preview(header, render_sections(records))


# ---------------- 待复核清单 ----------------

PENDING_TITLE = "# 待复核：没有产出摘要的日记"


def render_pending_markdown(items: List[Dict], title: str = PENDING_TITLE) -> str:
    """渲染"待复核"清单（含原文全文，便于逐条人工确认为什么没有摘要）"""
    failed = sum(1 for item in items if item.get("status") == "failed")
    lines = [
        title.strip(),
        "",
        f"- 条数：{len(items)}（其中处理失败 {failed} 条）",
        "- 用途：这些日记没有产出摘要（调用失败，或模型给出了空答案）。"
        "失败的条目在重跑同一命令时会自动重试；若反复失败，可调整 "
        "`prompts/diary_summary_prompt.txt` 或 LLM 参数后重跑。",
        "- 本文件由 `--all` / `--rebuild-md` 自动生成，不调用模型、不修改状态。",
        "",
    ]
    for item in items:
        status = item.get("status")
        label = "处理失败" if status == "failed" else "空摘要"
        if status == "failed" and item.get("error"):
            label += f"（{item['error']}）"
        lines += [
            "---",
            "",
            f"## {item.get('entry_date')}｜{item.get('entry_type')}｜"
            f"{item.get('word_count')}字｜entry_id={item.get('entry_id')}",
            "",
            f"**{label}**",
            "",
            (item.get("content") or "").strip() or "（空正文）",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"

