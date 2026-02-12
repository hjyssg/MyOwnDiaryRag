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

# 配置将从 .env 加载
DB_PATH = None
LM_STUDIO_URL = None

def get_config_value(key):
    """获取配置值"""
    global DB_PATH, LM_STUDIO_URL
    if DB_PATH is None or LM_STUDIO_URL is None:
        from config import get_config
        config = get_config()
        DB_PATH = config['database_path']
        LM_STUDIO_URL = config['lm_studio_url']
    
    if key == 'database_path':
        return DB_PATH
    elif key == 'lm_studio_url':
        return LM_STUDIO_URL
    return None

def get_db_path():
    """获取数据库路径"""
    return get_config_value('database_path')

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


def call_llm(prompt, max_tokens=800, temperature=0.5):
    """调用 LM Studio 的 OpenAI 兼容 API"""
    url = get_config_value('lm_studio_url')
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False
    }).encode('utf-8')

    req = Request(
        url,
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


# 分词 prompt
TOKENIZE_PROMPT = """请从以下问题中提取关键词，用于搜索日记。
只输出关键词，用空格分隔，不要输出其他内容。
关键词应该是名词、动词、地名、人名等实体词，忽略"的、了、吗、呢"等虚词。

问题：{question}

关键词："""


def extract_keywords_with_llm(question):
    """使用 LLM 提取关键词"""
    prompt = TOKENIZE_PROMPT.format(question=question)
    try:
        result = call_llm(prompt, max_tokens=50, temperature=0.1)
        # 清理结果，提取关键词
        # 处理可能的逗号、顿号等分隔符
        result = result.replace('，', ' ').replace('、', ' ').replace(',', ' ')
        keywords = result.strip().split()
        # 过滤掉可能的标点符号和空白
        keywords = [k.strip('，。！？、；：""''（）《》【】') for k in keywords]
        keywords = [k for k in keywords if k and len(k) > 0]
        return keywords[:8]  # 最多返回8个关键词
    except Exception as e:
        print(f"[警告] LLM 分词失败: {e}，使用简单分词")
        return None


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
    # 使用 LLM 提取关键词
    print("[分词]", end="", flush=True)
    keywords = extract_keywords_with_llm(question)
    
    # 如果 LLM 分词失败，使用简单分词作为后备
    if not keywords:
        stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '吗', '呢', '啊', '吧'}
        
        # 简单分词：提取2-4字的词组
        keywords = []
        for length in [4, 3, 2]:
            for i in range(len(question) - length + 1):
                word = question[i:i+length]
                if word not in stopwords and not any(c in stopwords for c in word):
                    keywords.append(word)
        
        # 如果没有提取到关键词，提取单字（排除停用词）
        if not keywords:
            keywords = [c for c in question if c not in stopwords and len(c.strip()) > 0]
        
        # 去重并保持顺序
        seen = set()
        unique_keywords = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique_keywords.append(k)
        keywords = unique_keywords[:8]
    
    # 构建搜索查询
    if not keywords:
        search_query = question
    else:
        search_query = ' '.join(keywords)
    
    print(f" [{search_query}]", end="", flush=True)
    
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


def is_broad_question(question):
    """判断是否是宽泛的问题（需要浏览大量摘要）"""
    broad_patterns = [
        r'去了哪里', r'去过哪', r'做了什么', r'发生了什么',
        r'有什么.*事', r'都.*了', r'总结', r'回顾'
    ]
    return any(re.search(pattern, question) for pattern in broad_patterns)


def get_year_summaries(conn, year_range, limit=100):
    """获取指定年份的所有摘要"""
    sql = """
        SELECT date, summary, entry_type
        FROM diary_entries
        WHERE year >= ? AND year <= ?
        AND summary IS NOT NULL
        ORDER BY date
        LIMIT ?
    """
    cursor = conn.execute(sql, [year_range[0], year_range[1], limit])
    return cursor.fetchall()


def answer_question(conn, question):
    """回答用户问题"""
    print(f"\n[检索] 检索中...", end="", flush=True)
    
    # 提取年份范围
    year_range = extract_year_range(question)
    if year_range:
        print(f" [年份: {year_range[0]}-{year_range[1]}]", end="", flush=True)
    
    # 判断是否是宽泛问题
    if year_range and is_broad_question(question):
        print(" [宽泛问题，浏览摘要]", end="", flush=True)
        
        # 获取该年份的所有摘要
        year_summaries = get_year_summaries(conn, year_range, limit=200)
        
        if not year_summaries:
            print(f"\n\n[提示] {year_range[0]}年没有日记")
            return
        
        print(f" 找到 {len(year_summaries)} 条日记\n")
        
        # 组装摘要文本
        summaries_text = ""
        for date, summary, entry_type in year_summaries:
            summaries_text += f"{date} ({entry_type}): {summary}\n"
        
        # 构建 prompt
        prompt = f"""你是一个私人日记助手。根据以下日记摘要回答用户的问题。
只基于提供的摘要回答，不要编造信息。

## {year_range[0]}年日记摘要
{summaries_text}

## 用户问题
{question}

请回答："""
        
        # 调用 LLM
        print("[思考] 思考中...\n")
        answer = call_llm(prompt, max_tokens=1000)
        
        print(f"[回答] {answer}\n")
        return
    
    # 常规关键词检索
    results = search_diaries(conn, question, year_range=year_range, limit=30)
    
    if not results:
        print(f"\n\n[提示] 没有找到相关日记")
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
