#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年度写作统计脚本 - 纯字数版
仅显示逐年日记字数统计和字数写作趋势
"""

import sqlite3
import sys
from pathlib import Path

# 确保可导入项目根目录模块（如 config.py）
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def get_yearly_stats(db_path):
    """获取年度字数统计"""
    conn = sqlite3.connect(db_path)
    
    # 查询数据库中的全部年份
    query = """
    SELECT 
        year,
        SUM(word_count) as total_words,
        MIN(date) as first_entry,
        MAX(date) as last_entry,
        ROUND(SUM(word_count) / COUNT(DISTINCT strftime('%j', date)), 1) as avg_words_per_active_day
    FROM diary_entries
    GROUP BY year
    ORDER BY year
    """
    
    cursor = conn.execute(query)
    results = cursor.fetchall()
    conn.close()
    
    return results

def display_yearly_stats(stats):
    """显示年度字数统计表格"""
    print("\n" + "="*70)
    print(f"{'年份':<8} {'总字数':<12} {'日均字数':<12} {'首篇日期':<12} {'末篇日期':<12}")
    print("="*70)
    
    total_words = 0
    years_count = len(stats)
    
    for row in stats:
        year, words, first_date, last_date, avg_per_day = row
        total_words += words
        print(f"{year:<8} {words:<12} {avg_per_day:<12} {first_date:<12} {last_date:<12}")
    
    print("="*70)
    print(f"\n总结：{years_count}年间共写作 {total_words:,} 字，平均每年 {round(total_words/years_count):,} 字")
    
    return stats

def analyze_trends(stats):
    """分析字数写作趋势"""
    print(f"\n{'='*50}")
    print("📈 字数写作趋势分析")
    print(f"{'='*50}")
    
    # 找出字数极值年份
    max_words_year = max(stats, key=lambda x: x[1])
    min_words_year = min(stats, key=lambda x: x[1])
    
    print(f"📚 最高产年份: {max_words_year[0]}年 ({max_words_year[1]:,}字)")
    print(f"📝 最少字数年份: {min_words_year[0]}年 ({min_words_year[1]:,}字)")
    
    # 分析时期
    print(f"\n📊 不同时期字数产出:")
    
    periods = [
        ("初中-高中", 2004, 2010),
        ("大学时期", 2011, 2014),
        ("工作时期", 2015, max(s[0] for s in stats))
    ]
    
    for label, start, end in periods:
        period_data = [s for s in stats if start <= s[0] <= end]
        if period_data:
            period_words = sum(s[1] for s in period_data)
            print(f"   {label} ({start}-{end}): {period_words:,}字")

def create_charts(stats):
    """创建字数统计图表"""
    try:
        import matplotlib.pyplot as plt

        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
        plt.rcParams['axes.unicode_minus'] = False
        
        years = [s[0] for s in stats]
        words = [s[1] for s in stats]
        
        # 仅保留两个最核心的字数图表
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        fig.suptitle(
            f'日记字数统计趋势 ({min(years)}-{max(years)})',
            fontsize=16,
            fontweight='bold',
        )
        
        # 1. 年度字数曲线
        ax1.plot(years, words, marker='o', linewidth=2, color='#2E8B57')
        ax1.set_title('年度总字数趋势', fontweight='bold')
        ax1.set_ylabel('字数')
        ax1.grid(True, alpha=0.3)
        ax1.set_xticks(years[::2])
        ax1.tick_params(axis='x', rotation=45)
        
        # 2. 时期分布饼图
        early_words = sum(s[1] for s in stats if s[0] <= 2010)
        college_words = sum(s[1] for s in stats if 2011 <= s[0] <= 2014)
        work_words = sum(s[1] for s in stats if s[0] >= 2015)
        
        ax2.pie([early_words, college_words, work_words], 
                labels=['初中-高中', '大学', '工作'], 
                autopct='%1.1f%%', colors=['#FFB6C1', '#87CEEB', '#98FB98'], startangle=90)
        ax2.set_title('各时期字数贡献占比', fontweight='bold')
        
        plt.tight_layout()
        chart_path = Path(__file__).parent / "yearly_word_stats.png"
        plt.savefig(chart_path, dpi=300)
        print(f"\n📊 字数统计图表已保存到: {chart_path}")
        plt.show()
            
    except Exception as e:
        print(f"\n⚠️ 绘图失败: {e}")

def main():
    try:
        from config import get_database_path
        db_path = get_database_path()
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return
    
    if not db_path.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return
    
    print("📊 正在分析年度字数统计...")
    stats = get_yearly_stats(db_path)
    if not stats:
        return
    
    display_yearly_stats(stats)
    analyze_trends(stats)
    create_charts(stats)
    print(f"\n✅ 分析完成！")

if __name__ == "__main__":
    main()