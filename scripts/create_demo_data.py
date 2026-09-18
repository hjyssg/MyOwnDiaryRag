#!/usr/bin/env python3
"""创建供 Web 界面和 API 演示使用的完全虚构 SQLite 日记库。

默认输出到 ``data/demo_diary.db``，不会读取或改写 .env 指向的个人日记库。
重复运行会重建该演示文件，适合演示、截图与新贡献者本地开发。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from summary_fingerprint import algorithm_fingerprint, cache_key, entry_key, source_hash

SCHEMA_FILE = ROOT_DIR / "create_diary_db.sql"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "demo_diary.db"
DEMO_FINGERPRINT = algorithm_fingerprint(
    {
        "algorithm_version": "demo-summary-v1",
        "prompt_hash": "demo-data",
        "model": "demo-writer",
        "purpose": "local-web-demo",
    }
)

DEMO_ENTRIES = [
    ("2021-09-17", "diary", "刚搬进学校附近的小房子。窗外有一棵很大的梧桐树，傍晚的光落在桌面上。今天第一次认真想：原来独立生活是这样安静又新鲜的事。", "快乐", "新的住处、新的城市，记录了独立生活刚开始时的期待。"),
    ("2022-01-01", "summary", "新年的第一天没有制定很宏大的计划。只是把房间收拾干净，煮了一碗面，给家里打了电话。希望今年能把注意力放回每天真正想做的事情上。", "期待", "用平静的仪式感开启新年，期待更专注地生活。"),
    ("2022-09-17", "diary", "下了一整天雨。和朋友躲在咖啡馆里聊工作、电影和以后想去的地方。雨停的时候，我们都说这样的普通下午也很值得记住。", "平淡", "雨天与朋友聊天的普通下午，被珍视为温暖的回忆。"),
    ("2023-03-12", "note", "周末沿着河边走了很久。风还有一点凉，但树已经开始发芽。回家路上买了一束白色郁金香，插在玻璃瓶里，房间忽然明亮起来。", "快乐", "春日散步和一束花，让平常的周末有了明亮的心情。"),
    ("2023-06-28", "stock_diary", "今天把最近的投资笔记重新整理了一遍。市场波动的时候，比起急着判断方向，更重要的是确认自己有没有遵守原先的规则。", "平淡", "在市场波动中回到长期规则，保持克制和理性。"),
    ("2023-09-17", "diary", "又是一年九月十七日。今天没有发生特别的事，但傍晚收到老朋友发来的照片，想起去年下雨的咖啡馆。原来时间会把一些瞬间慢慢酿成礼物。", "期待", "同一天的旧回忆被重新唤起，感受到时间沉淀下来的温柔。"),
    ("2023-12-31", "retrospective", "这一年学会了不把每一次停顿都当成退步。完成的事情并不总是显眼，但那些按时吃饭、认真休息、继续写下去的日子，也算在慢慢向前。", "平淡", "年度回顾中肯定了缓慢但持续的成长。"),
    ("2024-02-10", "diary", "春节回家，厨房里一直有汤的香味。饭后陪外婆在楼下晒太阳，她讲起年轻时坐很久火车去看海。听着听着，忽然觉得家人的故事也是我的来处。", "快乐", "春节与家人相处，从长辈的故事里感到温暖和连接。"),
    ("2024-05-18", "note", "完成了一个拖了很久的小项目。最后提交的那一刻没有想象中激动，更多是一种终于可以把桌面清空、去散步的轻松。", "快乐", "完成长期搁置的项目后，获得轻松而踏实的满足感。"),
    ("2024-09-17", "diary", "今天特意绕路去了那家咖啡馆。窗边的位置还在，只是梧桐叶已经有一点黄。点了和两年前一样的饮料，给过去的自己写了一句：你做得不错。", "快乐", "在熟悉的咖啡馆回望过去，并温柔地肯定了自己。"),
    ("2024-10-06", "diary", "最近的节奏有些乱，晚上也总是睡得不够。决定从明天开始把手机放到客厅，留半小时读书或只是发呆。先把日子过得慢一点。", "疲惫", "觉察到疲惫和失序，决定用小习惯重新找回生活节奏。"),
    ("2025-01-01", "summary", "今年想继续记录，不是为了证明每天都很精彩，而是想在很多年后还能认出那个认真生活过的自己。", "期待", "把持续记录视为与未来自己保持联系的方式。"),
    ("2025-04-20", "retrospective", "春天已经过去一半。回看前三个月，最开心的不是完成了多少清单，而是重新开始画画、做饭，还有每周和朋友见一次面。生活的质地好像更松一点了。", "快乐", "季度回顾发现，兴趣、做饭和朋友让生活变得更舒展。"),
]

MONTHLY_ENTRY_TYPES = ("diary", "note", "stock_diary", "retrospective", "summary")
MONTHLY_EMOTIONS = ("平淡", "期待", "快乐", "疲惫", "焦虑")


def busy_month_entries() -> list[tuple[str, str, str, str, str]]:
    """生成 2024 年 11 月的 100 篇长日记，供列表、分页和筛选功能演示。"""
    entries = []
    for day in range(1, 21):
        date_text = f"2024-11-{day:02d}"
        for index, entry_type in enumerate(MONTHLY_ENTRY_TYPES, start=1):
            record_number = (day - 1) * len(MONTHLY_ENTRY_TYPES) + index
            emotion = MONTHLY_EMOTIONS[(day + index - 2) % len(MONTHLY_EMOTIONS)]
            content = (
                f"2024 年 11 月 {day} 日，第 {record_number} 条演示记录，类型为 {entry_type}。"
                "今天按计划完成了手头的事项，并把过程、判断和后续安排整理下来。"
                "记录中包括当天发生的事情、需要跟进的问题、已经完成的部分，以及下一步准备尝试的方法。"
                "写下这些内容是为了测试长文本在阅读页、随机页和搜索结果中的展示，而不是任何真实个人经历。"
            )
            filler = (
                "这是一段用于本地界面演示的虚构文本。它保持中性的叙述方式，说明任务进度、时间安排、"
                "沟通结果和待办事项。通过重复但带有明确用途的段落，可以验证列表预览截断、全文排版、"
                "字数统计、摘要生成记录和不同筛选条件下的加载效果。"
            )
            while word_count(content) < 420:
                content += "\n\n" + filler
            summary = f"11 月 {day} 日的第 {record_number} 条演示记录，包含进度、安排和后续事项。"
            entries.append((date_text, entry_type, content, emotion, summary))
    return entries


def all_demo_entries() -> list[tuple[str, str, str, str, str]]:
    return [*DEMO_ENTRIES, *busy_month_entries()]


def word_count(content: str) -> int:
    return len("".join(content.split()))


def create_demo_database(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with sqlite3.connect(output) as connection:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        connection.execute(
            "INSERT INTO summary_algorithms (fingerprint, algorithm_version, prompt_hash, model, parameters_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (DEMO_FINGERPRINT, "demo-summary-v1", "demo-data", "demo-writer", '{"purpose":"local-web-demo"}', stamp),
        )
        for date_text, entry_type, content, emotion, summary in all_demo_entries():
            year, month, day = map(int, date_text.split("-"))
            words = word_count(content)
            connection.execute(
                "INSERT INTO diary_entries (date, year, month, day, content, file_source, entry_type, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date_text, year, month, day, content, "demo-data", entry_type, words),
            )
            entry = {"date": date_text, "entry_type": entry_type}
            key = entry_key(entry)
            content_hash = source_hash(content)
            connection.execute(
                """INSERT INTO entry_summaries
                (entry_key, entry_date, entry_type, year, month, day, word_count, source_hash,
                 algorithm_fingerprint, cache_key, status, summary, generated_at, updated_at,
                 emotion, emotion_status, emotion_cache_key, emotion_algorithm_fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, 'ok', ?, ?)""",
                (key, date_text, entry_type, year, month, day, words, content_hash, DEMO_FINGERPRINT,
                 cache_key(key, content_hash, DEMO_FINGERPRINT), summary, stamp, stamp, emotion,
                 cache_key(key, content_hash, DEMO_FINGERPRINT, namespace="emotion-cache-v1"), DEMO_FINGERPRINT),
            )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="创建完全虚构的 Web 演示日记数据库")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"输出 SQLite 路径（默认：{DEFAULT_OUTPUT}）")
    args = parser.parse_args()
    output = create_demo_database(args.output.expanduser().resolve())
    print(f"已创建演示数据库：{output}")
    print(f"包含 {len(all_demo_entries())} 篇完全虚构的日记和对应的 AI 摘要。")


if __name__ == "__main__":
    main()