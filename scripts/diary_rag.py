#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记 RAG 回忆助手（增强版）
纯本地方案：结构化过滤 + FTS5/LIKE 检索 + LM Studio 问答
"""

import sqlite3
import sys
import io
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
    if key == 'lm_studio_url':
        return LM_STUDIO_URL
    return None


def get_db_path():
    return get_config_value('database_path')


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


TOKENIZE_PROMPT = """请从以下问题中提取关键词，用于搜索日记。
只输出关键词，用空格分隔，不要输出其他内容。
关键词应该是名词、动词、地名、人名等实体词，忽略“的、了、吗、呢”等虚词。

问题：{question}

关键词："""


COMMON_STOPWORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也',
    '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '吗', '呢',
    '啊', '吧', '今年', '去年', '前年', '月份', '月', '年', '吗', '了', '呢', '是不是', '是否'
}


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


def extract_keywords_with_llm(question):
    """使用 LLM 提取关键词"""
    prompt = TOKENIZE_PROMPT.format(question=question)
    try:
        result = call_llm(prompt, max_tokens=50, temperature=0.1)
        result = result.replace('，', ' ').replace('、', ' ').replace(',', ' ')
        keywords = result.strip().split()
        keywords = [k.strip('，。！？、；："”"“\'（）《》【】()') for k in keywords]
        keywords = [k for k in keywords if k and k not in COMMON_STOPWORDS]
        return keywords[:8]
    except Exception:
        return None


def normalize_keywords(keywords):
    """关键词清洗，避免 FTS5 MATCH 语法错误。"""
    cleaned = []
    for k in keywords:
        token = re.sub(r'[\s,，。！？、；："“”\'`()\[\]{}<>]+', '', k)
        if not token:
            continue
        if token in COMMON_STOPWORDS:
            continue
        if token.isdigit() and len(token) <= 2:
            continue
        cleaned.append(token)
    # 去重保序
    seen = set()
    result = []
    for token in cleaned:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result[:8]


def extract_keywords(question):
    llm_tokens = extract_keywords_with_llm(question)
    if llm_tokens:
        tokens = normalize_keywords(llm_tokens)
        if tokens:
            return tokens

    # 兜底：抓取中文词片段、英文、数字年份
    candidates = re.findall(r'[\u4e00-\u9fff]{2,6}|[A-Za-z]{2,}|\d{4}', question)
    tokens = normalize_keywords(candidates)
    if tokens:
        return tokens

    # 最后兜底
    return normalize_keywords(list(question))


def extract_year_range(question):
    """从问题中提取年份范围"""
    year_patterns = [
        (r'(\d{4})年', lambda m: (int(m.group(1)), int(m.group(1)))),
        (r'(\d{4})-(\d{4})', lambda m: (int(m.group(1)), int(m.group(2)))),
        (r'(\d{4})到(\d{4})', lambda m: (int(m.group(1)), int(m.group(2)))),
    ]

    for pattern, extractor in year_patterns:
        match = re.search(pattern, question)
        if match:
            return extractor(match)

    current_year = datetime.now().year
    if '去年' in question:
        return (current_year - 1, current_year - 1)
    if '前年' in question:
        return (current_year - 2, current_year - 2)
    if '今年' in question:
        return (current_year, current_year)
    return None


def extract_month(question):
    """提取月份，支持“1月/一月/一月份”等。"""
    m = re.search(r'(1[0-2]|[1-9])\s*月', question)
    if m:
        return int(m.group(1))

    month_cn = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
        '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12
    }
    m = re.search(r'(十一|十二|十|一|二|三|四|五|六|七|八|九)月', question)
    if m:
        return month_cn[m.group(1)]
    return None


def detect_trip_yes_no_question(question):
    """识别“去了X吗”类问题并提取地点。"""
    q = question.strip('？?。!！')
    patterns = [
        r'去了(?P<city>[\u4e00-\u9fffA-Za-z]{2,10}?)了?吗$',
        r'去过(?P<city>[\u4e00-\u9fffA-Za-z]{2,10}?)了?吗$',
        r'有没有去(?P<city>[\u4e00-\u9fffA-Za-z]{2,10})$'
    ]
    for p in patterns:
        m = re.search(p, q)
        if m:
            city = m.group('city')
            city = re.sub(r'(这个|那个|那边|这里)$', '', city)
            city = re.sub(r'了$', '', city)
            if city:
                return city
    return None


def is_where_question(question):
    return bool(re.search(r'去了?哪里|去过哪|到过哪', question))


def get_city_mentions(conn, year_range, month=None, limit=20):
    """在指定时间范围中统计常见城市命中次数。"""
    cities = [
        '上海', '厦门', '广州', '北京', '天津', '成都', '重庆', '深圳', '杭州', '南京',
        '苏州', '香港', '澳门', '武汉', '青岛', '西安', '长沙', '三亚', '万宁', '福州',
        '泉州', '东京', '大阪', '京都', '首尔'
    ]
    base_sql = """
        SELECT COUNT(*)
        FROM diary_entries
        WHERE year >= ? AND year <= ?
    """
    params_base = [year_range[0], year_range[1]]
    if month is not None:
        base_sql += " AND month = ?"
        params_base.append(month)

    result = []
    for city in cities:
        sql = base_sql + " AND content LIKE ?"
        params = params_base + [f'%{city}%']
        cnt = conn.execute(sql, params).fetchone()[0]
        if cnt > 0:
            result.append((city, cnt))
    result.sort(key=lambda x: (-x[1], x[0]))
    return result[:limit]


def query_trip_presence(conn, city, year_range=None, month=None):
    sql = "SELECT COUNT(*) FROM diary_entries WHERE content LIKE ?"
    params = [f'%{city}%']
    if year_range:
        sql += " AND year >= ? AND year <= ?"
        params.extend([year_range[0], year_range[1]])
    if month is not None:
        sql += " AND month = ?"
        params.append(month)
    count = conn.execute(sql, params).fetchone()[0]
    return count


def build_fts_query(tokens):
    """构造 FTS5 MATCH 查询，避免非法语法（逗号等）。"""
    safe_terms = []
    for token in tokens:
        t = token.replace('"', '""').strip()
        if not t:
            continue
        # 使用短语包裹，避免特殊字符导致语法异常
        safe_terms.append(f'"{t}"')
    if not safe_terms:
        return None
    # 使用 OR 提高召回，避免问题词全部 AND 导致无结果
    return ' OR '.join(safe_terms)


def search_diaries(conn, question, year_range=None, month=None, entry_types=None, limit=30):
    """混合检索：FTS5 + LIKE 兜底"""
    print("[分词]", end="", flush=True)
    tokens = extract_keywords(question)
    print(f" [{', '.join(tokens)}]", end="", flush=True)

    fts_query = build_fts_query(tokens)
    if fts_query:
        sql = """
            SELECT
                e.id, e.date, e.content, e.summary, e.entry_type,
                (fts.rank * 10) as rank
            FROM diary_entries e
            JOIN diary_fts fts ON e.date = fts.date
            WHERE fts.content MATCH ?
        """
        params = [fts_query]
        if year_range:
            sql += " AND e.year >= ? AND e.year <= ?"
            params.extend(year_range)
        if month is not None:
            sql += " AND e.month = ?"
            params.append(month)
        if entry_types:
            placeholders = ','.join('?' * len(entry_types))
            sql += f" AND e.entry_type IN ({placeholders})"
            params.extend(entry_types)
        sql += " ORDER BY rank DESC LIMIT ?"
        params.append(limit)
        try:
            rows = conn.execute(sql, params).fetchall()
            if rows:
                return rows
        except Exception as e:
            print(f"[警告]  FTS5 搜索出错: {e}")
            print(f"   查询: {fts_query}")

    # LIKE 兜底：按 tokens 组装 OR 检索
    like_sql = """
        SELECT id, date, content, summary, entry_type, 0 as rank
        FROM diary_entries
        WHERE 1=1
    """
    like_params = []
    if year_range:
        like_sql += " AND year >= ? AND year <= ?"
        like_params.extend(year_range)
    if month is not None:
        like_sql += " AND month = ?"
        like_params.append(month)

    if tokens:
        clauses = []
        for token in tokens[:6]:
            clauses.append("content LIKE ?")
            like_params.append(f'%{token}%')
        like_sql += " AND (" + " OR ".join(clauses) + ")"
    else:
        like_sql += " AND content LIKE ?"
        like_params.append(f'%{question[:50]}%')

    like_sql += " ORDER BY date DESC LIMIT ?"
    like_params.append(limit)
    return conn.execute(like_sql, like_params).fetchall()


def format_context(results, top_summaries=10, top_full=3):
    summaries_text = ""
    full_entries_text = ""

    for i, (entry_id, date, content, summary, entry_type, rank) in enumerate(results[:top_summaries], 1):
        if summary:
            summaries_text += f"{i}. {date} ({entry_type}): {summary}\n"
        else:
            summaries_text += f"{i}. {date} ({entry_type}): {content[:100]}...\n"

    for i, (entry_id, date, content, summary, entry_type, rank) in enumerate(results[:top_full], 1):
        full_entries_text += f"\n### {date} ({entry_type})\n{content}\n"

    return summaries_text.strip(), full_entries_text.strip()


def answer_question_text(conn, question, use_llm=True):
    """核心问答函数，返回文本（便于单测）。"""
    year_range = extract_year_range(question)
    month = extract_month(question)

    city = detect_trip_yes_no_question(question)
    if city:
        cnt = query_trip_presence(conn, city, year_range=year_range, month=month)
        time_scope = ""
        if year_range:
            if year_range[0] == year_range[1]:
                time_scope += f"{year_range[0]}年"
            else:
                time_scope += f"{year_range[0]}-{year_range[1]}年"
        if month is not None:
            time_scope += f"{month}月"
        if cnt > 0:
            return f"去了。{time_scope}相关日记中检索到 {cnt} 条提到“{city}”的记录。"
        return f"没去（或未记录）。{time_scope}相关日记中没有检索到“{city}”的记录。"

    if year_range and is_where_question(question):
        mentions = get_city_mentions(conn, year_range, month=month, limit=15)
        if not mentions:
            return "没找到明确地点记录。"
        city_text = '、'.join([f"{c}({n})" for c, n in mentions])
        if year_range[0] == year_range[1]:
            return f"{year_range[0]}年你提到/去过的地点包括：{city_text}。"
        return f"{year_range[0]}-{year_range[1]}年你提到/去过的地点包括：{city_text}。"

    results = search_diaries(conn, question, year_range=year_range, month=month, limit=30)
    if not results:
        return "没有找到相关日记。"

    if not use_llm:
        top_dates = [row[1] for row in results[:5]]
        return f"找到 {len(results)} 条相关日记，日期示例：{', '.join(top_dates)}"

    summaries, full_entries = format_context(results, top_summaries=10, top_full=3)
    prompt = QA_PROMPT.format(summaries=summaries, full_entries=full_entries, question=question)
    return call_llm(prompt)


def answer_question(conn, question):
    print(f"\n[检索] 检索中...", end="", flush=True)
    year_range = extract_year_range(question)
    month = extract_month(question)
    if year_range:
        print(f" [年份: {year_range[0]}-{year_range[1]}]", end="", flush=True)
    if month is not None:
        print(f" [月份: {month}]", end="", flush=True)

    answer = answer_question_text(conn, question, use_llm=True)
    print(f"\n\n[回答] {answer}\n")


def interactive_mode():
    print("=" * 60)
    print("[检索] 日记回忆助手 (纯本地 RAG)")
    print("=" * 60)
    print("输入问题，按回车查询。输入 'quit' 或 'exit' 退出。")
    print("支持年份过滤，如：'2023年我去了哪里？'")
    print("=" * 60)

    print("\n[连接] 测试 LM Studio 连接...", end="", flush=True)
    test = call_llm("请回复'OK'", max_tokens=5)
    if "[错误]" in test:
        print(f"\n{test}")
        print("请确认 LM Studio 已启动并加载模型")
        return
    print(" [OK]\n")

    conn = sqlite3.connect(get_db_path())
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
