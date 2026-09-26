#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记数据库导入脚本 v2
优化：智能文件分类、月份校验、同日合并、笔误检测、entry_type（普通日记统一为 diary）

日期体检（2026-09 新增）：导入时会检查「2月30日」这类不存在的日期，以及
「3月的日记放进 5月文件」这种月份 / 年份错放。发现问题**不会阻止正常日记入库**，
只在控制台重点提示，并在项目根目录输出《日记导入日期检查报告.md》警报报告，供人工核对修正。
"""

import calendar
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

#: 日期检查报告的默认文件名（写在项目根目录，可被 DiaryImporter(report_path=...) 覆盖）
DEFAULT_REPORT_NAME = "日记导入日期检查报告.md"



class DiaryImporter:
    #: 内容里的日期标记写法（与 README 列出的格式一致）。
    #: 只用来判断「一段文字像不像日期」，不判断合法性——
    #: 这样 2月30日 这类不存在的日期也能被抓出来提示用户。
    DATE_MARKER_PATTERNS = (
        r'^(\d{2})(\d{2})(?:\s+(?:周|星期)[一二三四五六日天])?$',  # 0401 / 0401 周三
        r'^(\d{1,2})_(\d{1,2})$',                                  # 01_01
        r'^(\d{1,2})月(\d{1,2})日$',                                # 1月1日
        r'^(\d{1,2})/(\d{1,2})$',                                   # 01/01
    )

    def __init__(self, diary_root_path, db_path, report_path=None):
        self.diary_root = Path(diary_root_path)
        self.db_path = db_path
        #: 日期检查报告输出位置；None 表示默认写项目根目录的《日记导入日期检查报告.md》
        self.report_path = Path(report_path) if report_path else None
        self.conn = None
        self.year_folders = sorted(
            path.name
            for path in self.diary_root.iterdir()
            if path.is_dir() and re.fullmatch(r"\d{4}", path.name)
        )
        self.excluded_items = {
            'anime_record', 'etc', 'fap', 'merged_diaries', 'database_tools',
            '.gitignore', 'README.md', '.git'
        }
        # 收集所有条目，用于同日合并
        self.all_entries = {}  # key: date_str -> list of entries
        # 警告收集（普通提示，如「同日合并」，与日期无关）
        self.warnings = []
        # 日期相关的普通提示（跨月溢出、文件内日期跳跃）；会进报告的「其他日期提示」
        self.date_notes = []
        # 重点提示：非法日期 / 月份错放 / 年份错放，很可能是写错，需要用户重点核对
        self.critical_warnings = []
        # 供日期检查报告使用的计数
        self.scanned_files = 0
        self.imported_entries = 0

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
        # 匹配 MM_DD 开头带中文后缀的文件名，如 "04_01 周末随笔.txt"
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
        支持 MM月.txt、MM月-标题.txt（如 01月.txt、05月-旅行记录.txt）。
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

    def extract_date_token(self, text):
        """一段文字长得像日期标记时返回 (month, day)，否则返回 None。

        与 parse_date_marker 共用 DATE_MARKER_PATTERNS，但**不做合法性判断**：
        2月30日、13月1日 这类不存在的日期也会被识别出来，交给调用方提示用户。
        """
        text = text.strip()
        for pattern in self.DATE_MARKER_PATTERNS:
            match = re.match(pattern, text)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None

    def parse_date_marker(self, line, year):
        """
        解析内容中的日期标记行。
        支持格式：0101, 01_01, 1月1日, 01/01
        返回 date 对象或 None
        """
        token = self.extract_date_token(line)
        if not token:
            return None

        month, day = token
        # 月份范围校验
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        try:
            return date(int(year), month, day)
        except ValueError:
            return None

    def count_date_markers(self, content, year):
        """统计内容中有多少个有效日期标记"""
        count = 0
        for line in content.split('\n'):
            line = line.strip()
            if line and self.parse_date_marker(line, year):
                count += 1
        return count

    @staticmethod
    def _month_gap(a, b):
        """两个月份之间的真实间隔（12月↔1月 视为相邻，间隔 1）"""
        gap = abs(a - b)
        return min(gap, 12 - gap)

    @staticmethod
    def _is_valid_date(year, month, day):
        try:
            date(int(year), month, day)
            return True
        except ValueError:
            return False

    @staticmethod
    def _date_reason(year, month, day):
        """给「这个日期不存在」补一句人话原因，例如 2月最多 28/29 日"""
        if not (1 <= month <= 12):
            return f"{month}月不存在"
        last_day = calendar.monthrange(int(year), month)[1]
        return f"{year}年{month}月没有{day}日（该月最多{last_day}日）"

    def _expected_month_from_filename(self, filename):
        """从文件名推断这篇日记「应该」属于几月：05月.txt → 5，05_03.txt → 5，否则 None"""
        match = re.match(r'^(\d{1,2})月', filename)
        if match and 1 <= int(match.group(1)) <= 12:
            return int(match.group(1))
        match = re.match(r'^(\d{1,2})_(\d{1,2})', filename)
        if match and 1 <= int(match.group(1)) <= 12:
            return int(match.group(1))
        return None

    def record_critical(self, message):
        """记录一条「很可能是写错了」的重点提示（控制台高亮 + 写进日期检查报告）"""
        self.critical_warnings.append(message)
        logger.error(message)

    def check_file_dates(self, file_path, year, content, relative_path):
        """对单个文件做日期体检：非法日期、月份错放、年份错放。

        只记录提示，**不改变解析结果**：正常日记照常入库，
        可疑的日期标记本来就解析不出来（维持原有行为），交给用户人工核对。
        """
        filename = file_path.name

        # 1) 文件名里的日期是否合法：02_30.txt 这种
        for pattern in (r'^(\d{1,2})_(\d{1,2})\.txt$',
                        r'^(\d{1,2})_(\d{1,2})\s',
                        r'^(\d{1,2})_(\d{1,2})_'):
            match = re.match(pattern, filename)
            if match:
                month, day = int(match.group(1)), int(match.group(2))
                if not self._is_valid_date(year, month, day):
                    self.record_critical(
                        f"[非法日期·文件名] {relative_path}：文件名里的 {month}月{day}日 "
                        f"不存在（{self._date_reason(year, month, day)}），这篇会落到兜底日期"
                    )
                break

        # 2) 文件名内嵌年份 ≠ 所在年份文件夹
        year_match = re.search(r'(?:19|20)\d{2}', filename)
        if year_match and int(year_match.group(0)) != int(year):
            self.record_critical(
                f"[年份错放] {relative_path}：文件名写着 {year_match.group(0)} 年，"
                f"文件却放在 {year} 文件夹里，很可能是放错了"
            )

        # 3) 逐行检查内容里的日期标记
        expected_month = self._expected_month_from_filename(filename)
        for line_no, line in enumerate(content.split('\n'), 1):
            token = self.extract_date_token(line)
            if not token:
                continue
            stripped = line.strip()
            # 纯 4 位「年份」行（如线下活动文件里的「2024」「2027」小标题）不是日期，跳过
            if re.fullmatch(r'(?:19|20)\d{2}', stripped):
                continue
            month, day = token
            if not (1 <= month <= 12 and 1 <= day <= 31):
                self.record_critical(
                    f"[非法日期] {relative_path} 第{line_no}行「{stripped}」："
                    f"解析成 {month}月{day}日，月份或日期超出范围，很可能是写错了"
                )
                continue
            if not self._is_valid_date(year, month, day):
                self.record_critical(
                    f"[非法日期] {relative_path} 第{line_no}行「{stripped}」："
                    f"{self._date_reason(year, month, day)}，这个日期不存在，很可能是写错了"
                )
                continue
            if expected_month is None or month == expected_month:
                continue
            if self._month_gap(month, expected_month) >= 2:
                self.record_critical(
                    f"[月份错放] {relative_path} 第{line_no}行「{stripped}」："
                    f"{month}月的日记却出现在「{filename}」（应为 {expected_month}月）里，"
                    f"很可能是写错月份或放错了文件"
                )
            else:
                self.date_notes.append(
                    f"ℹ️ 跨月溢出: {relative_path} 第{line_no}行「{stripped}」"
                    f"与文件名月份 {expected_month}月 相差 1 个月（可能是月初/月末顺带记录）"
                )

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
                        self.date_notes.append(
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
        智能分类文件
        返回: 'diary' | 'stock_diary' | 'retrospective' | 'summary' | 'note'

        普通日记（单日文件 MM_DD.txt、多日合一、整月合集 MM月.txt）统一归为 'diary'；
        「整篇存还是按日期标记拆分」由 should_split_content() 单独判断，不再写进 entry_type。
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

        # MM_DD.txt 格式的普通日记文件
        if self.parse_date_from_filename(filename, year):
            return 'diary'

        # 整月合集 MM月.txt / MM月-标题.txt（如 01月.txt、05月-旅行记录.txt）
        if self.parse_month_from_filename(filename, year):
            return 'diary'

        # 无法识别
        return 'note'

    def should_split_content(self, filename, year, content):
        """该日记文件是否需要按内容里的日期标记拆成单天（文件布局问题，与 entry_type 无关）"""
        # 整月合集 MM月.txt：一定按日期标记拆
        if self.parse_month_from_filename(filename, year):
            return True
        # MM_DD.txt：内容里有 >=2 个日期标记才拆，否则整篇就是一天
        if self.parse_date_from_filename(filename, year):
            return self.count_date_markers(content, year) >= 2
        # 其它（股票日记等文件名不带日期的合集）：一律尝试拆分
        return True

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
            # 日期体检：非法日期 / 月份错放 / 年份错放（只记录提示，不影响入库）
            self.check_file_dates(file_path, year, content, relative_path)
            file_type = self.classify_file(file_path, year, content)

            entries = []

            if file_type == 'retrospective':
                entries.append({
                    'date': date(int(year), 1, 1),
                    'content': content,
                    'entry_type': 'retrospective',
                    'file_source': relative_path
                })

            elif file_type in ('diary', 'stock_diary'):
                # 普通日记与股票日记都按「一天一条」入库：
                # 单日文件整篇存；多日合一 / 整月合集按日期标记拆成单天。
                need_split = self.should_split_content(filename, year, content)
                multi_entries = self.split_multi_day_content(content, year, relative_path) if need_split else []
                if multi_entries:
                    for entry in multi_entries:
                        entries.append({
                            'date': entry['date'],
                            'content': entry['content'],
                            'entry_type': file_type,
                            'file_source': relative_path
                        })
                else:
                    # 单日文件，或拆分失败时作为整体存储
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
                    if need_split:
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

            self.scanned_files = total_files
            self.imported_entries = total_entries

            logger.info(f"导入完成! 处理 {total_files} 个文件，导入 {total_entries} 条日记")

            # 重点提示：很可能是写错了，放在最显眼的位置
            if self.critical_warnings:
                print("\n" + "#" * 68)
                print("❗❗ 重点提示：下面这些都像是写错了，请逐条核对 ❗❗")
                print("#" * 68)
                for w in self.critical_warnings:
                    print(w)
                print("#" * 68)

            # 输出警告（日期提示 + 其它普通提示）
            notes = self.date_notes + self.warnings
            if notes:
                print("\n" + "=" * 60)
                print("⚠️  警告和提示")
                print("=" * 60)
                for w in notes:
                    print(w)
                print("=" * 60)

            report_path = self.write_date_report()
            print(f"\n📄 日期检查报告: {report_path}")

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

    def write_date_report(self, report_path=None):
        """把本次导入的日期体检结果写成 Markdown 报告。

        默认写到项目根目录的《日记导入日期检查报告.md》（也可在构造 DiaryImporter
        时指定 ``report_path`` 覆盖）。无论有没有问题都会生成，方便每次导入留档。
        """
        target = Path(report_path) if report_path else (self.report_path or ROOT_DIR / DEFAULT_REPORT_NAME)
        lines = [
            "# 日记导入日期检查报告",
            "",
            f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 日记根目录：{self.diary_root}",
            f"- 扫描文件：{self.scanned_files} 个，入库条目：{self.imported_entries} 条",
            "",
        ]

        if self.critical_warnings:
            lines.append(f"## ❗ 重点提示（很可能是写错了，请逐条核对，共 {len(self.critical_warnings)} 条）")
            lines.append("")
            lines += [f"{index}. {w}" for index, w in enumerate(self.critical_warnings, 1)]
            lines.append("")
        else:
            lines += ["## ✅ 未发现非法日期或月份 / 年份错放", ""]

        if self.date_notes:
            lines.append(f"## ℹ️ 其他日期提示（共 {len(self.date_notes)} 条）")
            lines.append("")
            lines += [f"- {w}" for w in self.date_notes]
            lines.append("")

        if self.warnings:
            # 同日合并等与日期无关的导入提示，只给个指引，避免报告被刷屏
            lines.append(f"> 另有 {len(self.warnings)} 条与日期无关的导入提示（如同日合并），见控制台输出。")
            lines.append("")

        target.write_text("\n".join(lines), encoding="utf-8")
        return target

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
