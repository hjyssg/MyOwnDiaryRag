#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记数据库导入脚本 v2
优化：智能文件类型判断、月份校验、同日合并、笔误检测、新增entry_type
"""

import os
import re
import sqlite3
import sys
import io
from datetime import datetime, date
from pathlib import Path
import logging

# 确保可导入项目根目录模块（如 config.py）
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Windows 控制台编码修复
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



class DiaryImporter:
    def __init__(self, diary_root_path, db_path):
        self.diary_root = Path(diary_root_path)
        self.db_path = db_path
        self.conn = None
        self.year_folders = [f"{year}" for year in range(2004, 2027)]
        self.excluded_items = {
            'anime_record', 'etc', 'fap', 'merged_diaries', 'database_tools',
            '.gitignore', 'README.md', '.git'
        }
        # 收集所有条目，用于同日合并
        self.all_entries = {}  # key: date_str -> list of entries
        # 警告收集
        self.warnings = []

    def connect_db(self):
        """连接数据库并创建表"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute("PRAGMA foreign_keys = ON")
            try:
                self.conn.execute("DELETE FROM diary_entries")
                self.conn.execute("DELETE FROM diary_fts")
                self.conn.execute("DELETE FROM diary_stats")
                logger.info("清空现有数据")
            except:
                with open(ROOT_DIR / "create_diary_db.sql", 'r', encoding='utf-8') as f:
                    self.conn.executescript(f.read())
                logger.info("创建新表")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False

    def close_db(self):
        if self.conn:
            self.conn.close()

    def get_word_count(self, text):
        text = re.sub(r'\s+', '', text)
        return len(text)

    def parse_date_from_filename(self, filename, year):
        """从文件名解析日期，支持 MM_DD.txt 和 MM_DD 开头的变体"""
        # 精确匹配 MM_DD.txt
        match = re.match(r'^(\d{1,2})_(\d{1,2})\.txt$', filename)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    return date(int(year), month, day)
                except ValueError:
                    pass
        # 匹配 MM_DD 开头带中文后缀的文件名，如 "04_01 封城日记.txt"
        match = re.match(r'^(\d{1,2})_(\d{1,2})\s', filename)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    return date(int(year), month, day)
                except ValueError:
                    pass
        # 匹配 MM_DD_ 开头，如 "09_01_马来西亚日记 v1.txt"
        match = re.match(r'^(\d{1,2})_(\d{1,2})_', filename)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                try:
                    return date(int(year), month, day)
                except ValueError:
                    pass
        return None

    def parse_month_from_filename(self, filename, year):
        """
        从文件名解析整月合集。
        支持 MM月.txt、MM月-标题.txt（如 01月.txt、05月-封城日记2.txt）。
        返回匹配到的月份(1-12)或 None
        """
        match = re.match(r'^(\d{1,2})月(?:[-_ ][^.]*)?\.txt$', filename)
        if match:
            month = int(match.group(1))
            if 1 <= month <= 12:
                return month
        # 也支持 MM月 开头无后缀直接 .txt（例如 2023/09_11 那种不含月）
        return None

    def is_title_line(self, line, year):
        """判断是否为标题行，如 '2025 生活日记' '2024 炒股日记'"""
        patterns = [
            rf'^{year}\s*生活日记',
            rf'^{year}\s*炒股日记',
            rf'^{year}\s*日记',
        ]
        for p in patterns:
            if re.match(p, line.strip()):
                return True
        return False

    def parse_date_marker(self, line, year):
        """
        解析内容中的日期标记行。
        支持格式：0101, 01_01, 1月1日, 01/01
        返回 date 对象或 None
        """
        line = line.strip()
        if not line:
            return None

        patterns = [
            # 0401 或 0401 周日 / 0401 星期三（整月合集常带星期后缀）
            (r'^(\d{2})(\d{2})(?:\s+(?:周|星期)[一二三四五六日天])?$', None),
            (r'^(\d{1,2})_(\d{1,2})$', None),   # 01_01
            (r'^(\d{1,2})月(\d{1,2})日$', None), # 1月1日
            (r'^(\d{1,2})/(\d{1,2})$', None),   # 01/01
        ]

        for pattern, _ in patterns:
            match = re.match(pattern, line)
            if match:
                month, day = int(match.group(1)), int(match.group(2))
                # 月份范围校验
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    return None
                try:
                    return date(int(year), month, day)
                except ValueError:
                    return None
        return None

    def count_date_markers(self, content, year):
        """统计内容中有多少个有效日期标记"""
        count = 0
        for line in content.split('\n'):
            line = line.strip()
            if line and self.parse_date_marker(line, year):
                count += 1
        return count

    def split_multi_day_content(self, content, year, file_source=""):
        """分割多日合一文件的内容，带笔误检测"""
        entries = []
        lines = content.split('\n')
        current_entry = {'date': None, 'content': []}
        prev_month = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # 保留空行在内容中（段落分隔）
                if current_entry['date'] and current_entry['content']:
                    current_entry['content'].append('')
                continue

            # 跳过标题行
            if self.is_title_line(stripped, year):
                continue

            # 检查是否是日期行
            entry_date = self.parse_date_marker(stripped, year)
            if entry_date:
                # 保存之前的条目
                if current_entry['date'] and current_entry['content']:
                    entries.append(current_entry)

                # 笔误检测：检查月份跳跃
                if prev_month is not None and entry_date.month != prev_month:
                    # 允许相邻月份（如1月文件包含到2月初）
                    if abs(entry_date.month - prev_month) > 2 and not (prev_month == 12 and entry_date.month <= 2):
                        self.warnings.append(
                            f"⚠️ 日期跳跃警告: {file_source} 中出现 {entry_date.strftime('%m/%d')}，"
                            f"前一条目是{prev_month}月，可能是笔误"
                        )
                prev_month = entry_date.month

                current_entry = {'date': entry_date, 'content': []}
            else:
                current_entry['content'].append(line.rstrip())

        # 保存最后一个条目
        if current_entry['date'] and current_entry['content']:
            entries.append(current_entry)

        # 转换格式，去除尾部空行
        result = []
        for entry in entries:
            # 去除尾部空行
            content_lines = entry['content']
            while content_lines and content_lines[-1] == '':
                content_lines.pop()
            content_text = '\n'.join(content_lines).strip()
            if content_text:
                result.append({
                    'date': entry['date'],
                    'content': content_text
                })

        return result

    def classify_file(self, file_path, year, content):
        """
        智能分类文件类型
        返回: 'single_day' | 'multi_day' | 'stock_diary' | 'retrospective' | 'summary' | 'note'
        """
        filename = file_path.name
        filename_lower = filename.lower()

        # index.md → 早期回忆
        if filename == 'index.md':
            return 'retrospective'

        # 股票日记
        if '股票' in filename:
            return 'stock_diary'

        # 特殊笔记类文件
        note_keywords = ['线下活动', '漫展', '名单', '感想', '规划', '目标',
                         '总结', '经验', '简史', '复诊', '帖子', '三角',
                         '叫魂', 'record']
        if any(kw in filename for kw in note_keywords):
            return 'note'

        # 学期总结类
        if any(kw in filename_lower for kw in ['semester', 'term', 'vaction']):
            return 'summary'

        # MM_DD.txt 格式的文件：通过内容中日期标记数量判断
        file_date = self.parse_date_from_filename(filename, year)
        if file_date:
            date_marker_count = self.count_date_markers(content, year)
            if date_marker_count >= 2:
                return 'multi_day'
            return 'single_day'

        # 整月合集 MM月.txt / MM月-标题.txt（如 01月.txt、05月-封城日记2.txt）
        if self.parse_month_from_filename(filename, year):
            return 'multi_day'

        # 无法识别
        return 'note'

    def process_file(self, file_path, year):
        """处理单个文件"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read().strip()

            if not content:
                logger.warning(f"文件为空: {file_path}")
                return []

            filename = file_path.name
            relative_path = str(file_path.relative_to(self.diary_root))
            file_type = self.classify_file(file_path, year, content)

            entries = []

            if file_type == 'retrospective':
                entries.append({
                    'date': date(int(year), 1, 1),
                    'content': content,
                    'entry_type': 'retrospective',
                    'file_source': relative_path
                })

            elif file_type == 'single_day':
                file_date = self.parse_date_from_filename(filename, year)
                if file_date:
                    entries.append({
                        'date': file_date,
                        'content': content,
                        'entry_type': 'single_day',
                        'file_source': relative_path
                    })

            elif file_type in ('multi_day', 'stock_diary'):
                multi_entries = self.split_multi_day_content(content, year, relative_path)
                if multi_entries:
                    for entry in multi_entries:
                        entries.append({
                            'date': entry['date'],
                            'content': entry['content'],
                            'entry_type': file_type,
                            'file_source': relative_path
                        })
                else:
                    # 拆分失败，作为整体存储
                    fallback_date = self.parse_date_from_filename(filename, year)
                    if not fallback_date:
                        fallback_month = self.parse_month_from_filename(filename, year)
                        if fallback_month:
                            fallback_date = date(int(year), fallback_month, 1)
                        else:
                            fallback_date = date(int(year), 1, 1)
                    entries.append({
                        'date': fallback_date,
                        'content': content,
                        'entry_type': file_type,
                        'file_source': relative_path
                    })
                    logger.warning(f"多日拆分失败，整体存储: {relative_path}")

            elif file_type == 'summary':
                entries.append({
                    'date': date(int(year), 12, 31),
                    'content': content,
                    'entry_type': 'summary',
                    'file_source': relative_path
                })

            elif file_type == 'note':
                # 笔记类：尝试从文件名提取月份，否则用1月1日
                fallback_date = self.parse_date_from_filename(filename, year)
                if not fallback_date:
                    fallback_date = date(int(year), 1, 1)
                entries.append({
                    'date': fallback_date,
                    'content': content,
                    'entry_type': 'note',
                    'file_source': relative_path
                })

            return entries

        except Exception as e:
            logger.error(f"处理文件失败 {file_path}: {e}")
            return []

    def collect_entry(self, entry):
        """收集条目，用于后续同日合并"""
        date_str = entry['date'].strftime('%Y-%m-%d')
        key = (date_str, entry['entry_type'])

        if key not in self.all_entries:
            self.all_entries[key] = entry
        else:
            # 同日同类型合并
            existing = self.all_entries[key]
            existing['content'] += f"\n\n---[同日补充]---\n\n{entry['content']}"
            existing['file_source'] += f" | {entry['file_source']}"
            self.warnings.append(
                f"📝 同日合并: {date_str} ({entry['entry_type']}) 来自 {entry['file_source']}"
            )

    def insert_entry(self, entry):
        """插入单条日记"""
        try:
            word_count = self.get_word_count(entry['content'])
            self.conn.execute("""
                INSERT OR REPLACE INTO diary_entries
                (date, year, month, day, content, file_source, entry_type, word_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry['date'].strftime('%Y-%m-%d'),
                entry['date'].year,
                entry['date'].month,
                entry['date'].day,
                entry['content'],
                entry['file_source'],
                entry['entry_type'],
                word_count,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            self.conn.execute("""
                INSERT OR REPLACE INTO diary_fts (date, content, file_source)
                VALUES (?, ?, ?)
            """, (
                entry['date'].strftime('%Y-%m-%d'),
                entry['content'],
                entry['file_source']
            ))
            return True
        except Exception as e:
            logger.error(f"插入数据失败: {e}")
            return False

    def update_stats(self):
        try:
            self.conn.execute("DELETE FROM diary_stats")
            cursor = self.conn.execute("""
                SELECT year, COUNT(*) as total_entries, SUM(word_count) as total_words,
                       MIN(date) as first_entry, MAX(date) as last_entry
                FROM diary_entries GROUP BY year ORDER BY year
            """)
            for row in cursor:
                self.conn.execute("""
                    INSERT INTO diary_stats
                    (year, total_entries, total_words, first_entry_date, last_entry_date, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (row[0], row[1], row[2], row[3], row[4],
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.conn.commit()
            logger.info("统计信息更新完成")
        except Exception as e:
            logger.error(f"更新统计失败: {e}")

    def run_import(self):
        if not self.connect_db():
            return False

        total_files = 0

        try:
            # 第一遍：收集所有条目
            for year in self.year_folders:
                year_path = self.diary_root / year
                if not year_path.is_dir():
                    continue

                logger.info(f"扫描年份: {year}")

                for file_path in sorted(year_path.iterdir()):
                    if not file_path.is_file():
                        continue
                    if file_path.suffix not in ['.txt', '.md']:
                        continue
                    # 排除图片等
                    if any(ext in file_path.name.lower() for ext in ['.jpg', '.png', '.xlsx', '.rtf']):
                        continue

                    total_files += 1
                    entries = self.process_file(file_path, year)
                    for entry in entries:
                        self.collect_entry(entry)

            # 第二遍：插入合并后的条目
            total_entries = 0
            for key, entry in sorted(self.all_entries.items()):
                if self.insert_entry(entry):
                    total_entries += 1

            self.conn.commit()
            self.update_stats()

            logger.info(f"导入完成! 处理 {total_files} 个文件，导入 {total_entries} 条日记")

            # 输出警告
            if self.warnings:
                print("\n" + "=" * 60)
                print("⚠️  警告和提示")
                print("=" * 60)
                for w in self.warnings:
                    print(w)
                print("=" * 60)

            self.show_stats()
            return True

        except Exception as e:
            logger.error(f"导入过程出错: {e}")
            import traceback
            traceback.print_exc()
            self.conn.rollback()
            return False
        finally:
            self.close_db()

    def show_stats(self):
        try:
            cursor = self.conn.execute("""
                SELECT year, total_entries, total_words, first_entry_date, last_entry_date
                FROM diary_stats ORDER BY year
            """)
            print(f"\n{'年份':<8} {'条目数':<8} {'总字数':<10} {'首篇日期':<12} {'末篇日期':<12}")
            print("-" * 60)
            grand_entries = 0
            grand_words = 0
            for row in cursor:
                year, entries, words, first_date, last_date = row
                grand_entries += entries
                grand_words += words
                print(f"{year:<8} {entries:<8} {words:<10} {first_date:<12} {last_date:<12}")
            print("-" * 60)
            print(f"{'总计':<8} {grand_entries:<8} {grand_words:<10}")

            # 按类型统计
            cursor2 = self.conn.execute("""
                SELECT entry_type, COUNT(*), SUM(word_count)
                FROM diary_entries GROUP BY entry_type ORDER BY COUNT(*) DESC
            """)
            print(f"\n{'类型':<16} {'条目数':<8} {'总字数':<10}")
            print("-" * 40)
            for row in cursor2:
                print(f"{row[0]:<16} {row[1]:<8} {row[2]:<10}")

        except Exception as e:
            logger.error(f"显示统计信息失败: {e}")


def main():
    from config import get_config
    
    try:
        config = get_config()
        diary_root = config['diary_base_path']
        db_path = config['database_path']
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        sys.exit(1)

    logger.info("开始导入日记到SQLite数据库 (v2)...")
    logger.info(f"日记根目录: {diary_root}")
    logger.info(f"数据库文件: {db_path}")

    importer = DiaryImporter(diary_root, db_path)

    if importer.run_import():
        logger.info("导入成功！")
    else:
        logger.error("导入失败！")
        sys.exit(1)


if __name__ == "__main__":
    main()
