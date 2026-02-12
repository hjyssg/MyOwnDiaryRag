-- 日记数据库表结构
-- 一天一条数据的设计

CREATE TABLE diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,                           -- 日记日期 (YYYY-MM-DD格式)
    year INTEGER NOT NULL,                        -- 年份 (便于查询)
    month INTEGER NOT NULL,                       -- 月份 (便于查询)
    day INTEGER NOT NULL,                         -- 日期 (便于查询)
    content TEXT NOT NULL,                        -- 日记内容
    file_source TEXT,                             -- 源文件路径
    entry_type TEXT CHECK(entry_type IN ('single_day', 'multi_day', 'retrospective', 'summary', 'stock_diary', 'note')), -- 文件类型
    word_count INTEGER DEFAULT 0,                 -- 字数统计
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, entry_type)
);

-- 创建索引优化查询
CREATE INDEX idx_diary_date ON diary_entries(date);
CREATE INDEX idx_diary_year ON diary_entries(year);
CREATE INDEX idx_diary_year_month ON diary_entries(year, month);
CREATE INDEX idx_diary_type ON diary_entries(entry_type);
CREATE INDEX idx_diary_word_count ON diary_entries(word_count);

-- 创建全文搜索索引（用于内容搜索）
CREATE VIRTUAL TABLE diary_fts USING fts5(date, content, file_source);

-- 统计表（可选，用于快速查询统计信息）
CREATE TABLE diary_stats (
    year INTEGER PRIMARY KEY,
    total_entries INTEGER DEFAULT 0,
    total_words INTEGER DEFAULT 0,
    first_entry_date DATE,
    last_entry_date DATE,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
