#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记 RAG 回忆助手
纯本地方案：FTS5 检索 + LM Studio (Gemma) 问答
"""

import sqlite3
import sys
import io
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

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

# 问答 prompt
QA_PROMPT = """你是一个私人日记助手。根据以下日记内容回答用户的问题。
只基于提供的日记内容回答，不要编造信息。如果日记中没有相关信息，请如实说明。
回答要简洁、准确，保持友好的语气。

## 相关日记摘要
{summaries}

## 详细日记内容
{full_entries}

## 用户问题
{question}

请回答："""


def call_llm(prompt, max_tokens=800):
    """调用 LM Studio 的 OpenAI 兼容 API"""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.5,
        "stream": False
    }).encode('utf-8')

    req = Request(
        LM_STUDIO_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except URLError as e:
        return f"[错误] LM Studio 连接失败: {e}"
    except Exception as e:
        return f"[错误] API 调用出错: {e}"


def extract_year_range(question):
    """从问题中提取年份范围"""
    # 匹配 "2023年" "2022-2024" "去年" 等
    year_patterns = [
        (r'(\d{4})年', lambda m: (int(m.group(1)), int(m.group(1)))),
        (r'(\d{4})-(\d{4})', lambda m: (int(m.group(1)), int(m.group(2)))),
        (r'(\d{4})到(\d{4})', lambda m: (int(m.group(1)), int(m.group(2)))),
    ]
    
    for pattern, extractor in year_patterns:
        match = re.search(pattern, question)
        if match:
            return extractor(match)
    
    # "去年" "前年" 等相对时间
    from datetime import datetime
    current_year = datetime.now().year
    
    if '去年' in question:
        return (current_year - 1, current_year - 1)
    if '前年' in question:
        return (current_year - 2, current_year - 2)
    if '今年' in question:
        return (current_year, current_year)
    
    return None


def search_diaries(conn, question, year_range=None, entry_types=None, limit=30):
    """
    混合检索：FTS5 搜索摘要和原文
    返回: [(id, date, content, summary, entry_type, rank), ...]
    """
    # 构建 FTS5 查询
    # 简单处理：提取关键词（去除常见停用词）
    stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    keywords = [w for w in question if len(w) > 1 and w not in stopwords]
    
    # 如果没有提取到关键词，用原问题
    if not keywords:
        search_query = question
    else:
        search_query = ' '.join(keywords[:5])  # 最多取5个关键词
    
    # 构建 SQL
    sql = """
        SELECT 
            e.id, e.date, e.content, e.summary, e.entry_type,
            (fts.rank * 10) as rank
        FROM diary_entries e
        JOIN diary_fts fts ON e.date = fts.date
        WHERE fts.content MATCH ?
    """
    
    params = [search_query]
    
    # 年份过滤
    if year_range:
        sql += " AND e.year >= ? AND e.year <= ?"
        params.extend(year_range)
    
    # 类型过滤
    if entry_types:
        placeholders = ','.join('?' * len(entry_types))
        sql += f" AND e.entry_type IN ({placeholders})"
        params.extend(entry_types)
    
    sql += " ORDER BY rank DESC LIMIT ?"
    params.append(limit)
    
    try:
        cursor = conn.execute(sql, params)
        return cursor.fetchall()
    except Exception as e:
        print(f"[警告]  FTS5 搜索出错: {e}")
        print(f"   查询: {search_query}")
        # Fallback: 简单的 LIKE 搜索
        sql_fallback = """
            SELECT id, date, content, summary, entry_type, 0 as rank
            FROM diary_entries
            WHERE content LIKE ?
        """
        params_fallback = [f'%{question[:50]}%']
        
        if year_range:
            sql_fallback += " AND year >= ? AND year <= ?"
            params_fallback.extend(year_range)
        
        sql_fallback += " ORDER BY date DESC LIMIT ?"
        params_fallback.append(limit)
        
        cursor = conn.execute(sql_fallback, params_fallback)
        return cursor.fetchall()


def format_context(results, top_summaries=10, top_full=3):
    """
    组装 context：
    - 前 N 条的摘要
    - 前 M 条的完整内容
    """
    summaries_text = ""
    full_entries_text = ""
    
    # 摘要部分
    for i, (entry_id, date, content, summary, entry_type, rank) in enumerate(results[:top_summaries], 1):
        if summary:
            summaries_text += f"{i}. {date} ({entry_type}): {summary}\n"
        else:
            # 如果没有摘要，用前100字
            summaries_text += f"{i}. {date} ({entry_type}): {content[:100]}...\n"
    
    # 完整内容部分
    for i, (entry_id, date, content, summary, entry_type, rank) in enumerate(results[:top_full], 1):
        full_entries_text += f"\n### {date} ({entry_type})\n{content}\n"
    
    return summaries_text.strip(), full_entries_text.strip()


def answer_question(conn, question):
    """回答用户问题"""
    print(f"\n[检索] 检索中...", end="", flush=True)
    
    # 提取年份范围
    year_range = extract_year_range(question)
    if year_range:
        print(f" [年份: {year_range[0]}-{year_range[1]}]", end="", flush=True)
    
    # 检索
    results = search_diaries(conn, question, year_range=year_range, limit=30)
    
    if not results:
        print(f"\n\n[错误] 没有找到相关日记")
        return
    
    print(f" 找到 {len(results)} 条相关日记\n")
    
    # 组装 context
    summaries, full_entries = format_context(results, top_summaries=10, top_full=3)
    
    # 构建 prompt
    prompt = QA_PROMPT.format(
        summaries=summaries,
        full_entries=full_entries,
        question=question
    )
    
    # 调用 LLM
    print("[思考] 思考中...\n")
    answer = call_llm(prompt)
    
    print(f"[回答] {answer}\n")
    
    # 显示引用的日记
    print("[参考] 参考日记:")
    for i, (entry_id, date, content, summary, entry_type, rank) in enumerate(results[:5], 1):
        print(f"  {i}. {date} ({entry_type})")


def interactive_mode():
    """交互式问答模式"""
    print("=" * 60)
    print("[检索] 日记回忆助手 (纯本地 RAG)")
    print("=" * 60)
    print("输入问题，按回车查询。输入 'quit' 或 'exit' 退出。")
    print("支持年份过滤，如：'2023年我去了哪里？'")
    print("=" * 60)
    
    # 测试连接
    print("\n[连接] 测试 LM Studio 连接...", end="", flush=True)
    test = call_llm("请回复'OK'", max_tokens=5)
    if "[错误]" in test:
        print(f"\n{test}")
        print("请确认 LM Studio 已启动并加载模型")
        return
    print(" [OK]\n")
    
    # 连接数据库
    conn = sqlite3.connect(get_db_path())
    
    # 检查是否有摘要
    cursor = conn.execute("SELECT COUNT(*) FROM diary_entries WHERE summary IS NOT NULL")
    summary_count = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM diary_entries")
    total_count = cursor.fetchone()[0]
    
    if summary_count == 0:
        print("[警告]  数据库中还没有摘要，建议先运行:")
        print("   python build_summaries.py --all")
        print("\n继续使用原文检索...\n")
    elif summary_count < total_count:
        print(f"[信息]  摘要进度: {summary_count}/{total_count} ({summary_count*100//total_count}%)")
        print()
    
    try:
        while True:
            try:
                question = input("\n> ").strip()
            except UnicodeDecodeError:
                print("[警告]  输入编码错误，请重试")
                continue
            
            if not question:
                continue
            
            if question.lower() in ['quit', 'exit', 'q']:
                print("\n[再见] 再见！")
                break
            
            answer_question(conn, question)
    
    except KeyboardInterrupt:
        print("\n\n[再见] 再见！")
    finally:
        conn.close()


def main():
    interactive_mode()


if __name__ == "__main__":
    main()
