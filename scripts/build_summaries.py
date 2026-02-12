#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记摘要生成脚本
使用本地 LM Studio (Gemma) 为每条日记生成压缩摘要
支持断点续跑、抽样测试模式
"""

import sqlite3
import sys
import io
import json
import time
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# 确保可导入项目根目录模块（如 config.py）
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Windows 控制台编码修复
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# LM Studio 配置
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

# 数据库路径将从配置加载
DB_PATH = None

def get_db_path():
    """获取数据库路径"""
    global DB_PATH
    if DB_PATH is None:
        from config import get_config
        config = get_config()
        DB_PATH = config['database_path']
    return DB_PATH

# 摘要 prompt
SUMMARY_PROMPT = """你是一个日记摘要助手。请用一句话概括以下日记的核心内容，保留关键人物、地点、事件和情绪。不要添加任何评论或解释，只输出摘要本身。

日期：{date}
日记内容：
{content}

一句话摘要："""

# note 类型的 prompt（可能多主题）
NOTE_SUMMARY_PROMPT = """你是一个日记摘要助手。请用2-3句话概括以下笔记的核心内容，保留关键主题和要点。不要添加任何评论或解释，只输出摘要本身。

日期：{date}
笔记内容：
{content}

摘要："""


def call_llm(prompt, max_tokens=200):
    """调用 LM Studio 的 OpenAI 兼容 API"""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False
    }).encode('utf-8')

    req = Request(
        LM_STUDIO_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except URLError as e:
        print(f"  [错误] LM Studio 连接失败: {e}")
        return None
    except Exception as e:
        print(f"  [错误] API 调用出错: {e}")
        return None


def truncate_content(content, max_chars=2000):
    """截取超长内容：前1500 + 后500"""
    if len(content) <= max_chars:
        return content
    return content[:1500] + "\n\n...[中间省略]...\n\n" + content[-500:]


def generate_summary(date_str, content, entry_type):
    """为单条日记生成摘要"""
    # 极短日记直接用原文
    clean = content.strip()
    if len(clean) < 20:
        return clean

    # 截取超长内容
    truncated = truncate_content(clean)

    # 选择 prompt
    if entry_type == 'note':
        prompt = NOTE_SUMMARY_PROMPT.format(date=date_str, content=truncated)
    else:
        prompt = SUMMARY_PROMPT.format(date=date_str, content=truncated)

    return call_llm(prompt)


def get_sample_entries(conn, count=10):
    """抽样获取不同类型的日记条目"""
    samples = []

    # 每种类型取几条
    type_counts = {
        'single_day': 3,
        'multi_day': 3,
        'stock_diary': 2,
        'note': 1,
        'retrospective': 1,
    }

    for entry_type, n in type_counts.items():
        cursor = conn.execute("""
            SELECT id, date, content, entry_type, word_count
            FROM diary_entries
            WHERE entry_type = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (entry_type, n))
        samples.extend(cursor.fetchall())

    return samples[:count]


def get_all_entries_without_summary(conn):
    """获取所有没有摘要的条目"""
    cursor = conn.execute("""
        SELECT id, date, content, entry_type, word_count
        FROM diary_entries
        WHERE summary IS NULL
        ORDER BY date
    """)
    return cursor.fetchall()


def update_summary(conn, entry_id, summary):
    """更新单条摘要"""
    conn.execute(
        "UPDATE diary_entries SET summary = ? WHERE id = ?",
        (summary, entry_id)
    )
    conn.commit()


def run_sample_test():
    """抽样测试模式：随机取几条日记测试摘要质量"""
    print("=" * 60)
    print("[摘要] 抽样测试模式 — 测试摘要生成质量")
    print("=" * 60)

    # 先测试 LM Studio 连接
    print("\n[连接] 测试 LM Studio 连接...")
    test = call_llm("请回复'连接成功'", max_tokens=10)
    if test is None:
        print("[错误] 无法连接 LM Studio，请确认已启动并加载模型")
        print(f"   地址: {LM_STUDIO_URL}")
        return False
    print(f"[OK] LM Studio 连接成功: {test}")

    conn = sqlite3.connect(get_db_path())
    samples = get_sample_entries(conn, count=10)

    print(f"\n抽取 {len(samples)} 条日记进行测试:\n")

    for i, (entry_id, date_str, content, entry_type, word_count) in enumerate(samples, 1):
        print(f"--- [{i}/{len(samples)}] {date_str} ({entry_type}, {word_count}字) ---")
        print(f"原文前100字: {content[:100]}...")

        start = time.time()
        summary = generate_summary(date_str, content, entry_type)
        elapsed = time.time() - start

        if summary:
            print(f"[摘要] {summary}")
            print(f"[耗时] {elapsed:.1f}s")

            # 写入数据库
            update_summary(conn, entry_id, summary)
            print(f"[OK] 已保存到数据库")
        else:
            print(f"[错误] 摘要生成失败")
        print()

    conn.close()
    print("=" * 60)
    print("抽样测试完成！请检查摘要质量，满意后运行全量模式：")
    print("  python build_summaries.py --all")
    return True


def run_full_build():
    """全量模式：为所有日记生成摘要"""
    print("=" * 60)
    print("[摘要] 全量摘要生成模式")
    print("=" * 60)

    # 测试连接
    print("\n[连接] 测试 LM Studio 连接...")
    test = call_llm("请回复'OK'", max_tokens=5)
    if test is None:
        print("[错误] 无法连接 LM Studio")
        return False
    print(f"[OK] 连接成功")

    conn = sqlite3.connect(get_db_path())
    entries = get_all_entries_without_summary(conn)
    total = len(entries)

    if total == 0:
        print("\n[OK] 所有日记已有摘要，无需处理")
        conn.close()
        return True

    print(f"\n待处理: {total} 条日记")
    print("按 Ctrl+C 可随时中断，下次运行会自动续跑\n")

    success = 0
    failed = 0
    start_time = time.time()

    try:
        for i, (entry_id, date_str, content, entry_type, word_count) in enumerate(entries, 1):
            elapsed = time.time() - start_time
            rate = success / elapsed * 3600 if elapsed > 0 and success > 0 else 0
            eta = (total - i) / (success / elapsed) if elapsed > 0 and success > 0 else 0

            print(f"[{i}/{total}] {date_str} ({entry_type}, {word_count}字) "
                  f"| 成功:{success} 失败:{failed} "
                  f"| {rate:.0f}条/h ETA:{eta/60:.0f}min", end="")

            summary = generate_summary(date_str, content, entry_type)

            if summary:
                update_summary(conn, entry_id, summary)
                success += 1
                print(f" [OK] {summary[:40]}...")
            else:
                failed += 1
                print(f" [错误]")

                # 连续失败3次就停止
                if failed >= 3 and success == 0:
                    print("\n[错误] 连续失败，停止运行")
                    break

    except KeyboardInterrupt:
        print(f"\n\n[暂停]  用户中断。已完成 {success}/{total} 条。下次运行自动续跑。")

    conn.close()

    total_time = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"完成: {success} 条 | 失败: {failed} 条 | 耗时: {total_time/60:.1f}分钟")
    return True


def main():
    parser = argparse.ArgumentParser(description='日记摘要生成工具')
    parser.add_argument('--all', action='store_true', help='全量生成模式')
    parser.add_argument('--test', action='store_true', help='抽样测试模式（默认）')
    args = parser.parse_args()

    if args.all:
        run_full_build()
    else:
        run_sample_test()


if __name__ == "__main__":
    main()
