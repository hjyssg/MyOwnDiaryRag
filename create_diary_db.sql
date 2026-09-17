-- 数据库表结构（唯一 DDL 来源）
-- 日记部分：一天一条数据；摘要部分：每篇一条摘要 + 情绪
-- 全部使用 IF NOT EXISTS，可重复执行（SummaryStore.migrate() / 导入脚本都会跑它）

CREATE TABLE IF NOT EXISTS diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,                           -- 日记日期 (YYYY-MM-DD格式)
    year INTEGER NOT NULL,                        -- 年份 (便于查询)
    month INTEGER NOT NULL,                       -- 月份 (便于查询)
    day INTEGER NOT NULL,                         -- 日期 (便于查询)
    content TEXT NOT NULL,                        -- 日记内容
    file_source TEXT,                             -- 源文件路径
    entry_type TEXT CHECK(entry_type IN ('diary', 'retrospective', 'summary', 'stock_diary', 'note')), -- 条目分类（普通日记=diary）
    word_count INTEGER DEFAULT 0,                 -- 字数统计
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, entry_type)
);

-- 创建索引优化查询
CREATE INDEX IF NOT EXISTS idx_diary_date ON diary_entries(date);
CREATE INDEX IF NOT EXISTS idx_diary_year ON diary_entries(year);
CREATE INDEX IF NOT EXISTS idx_diary_year_month ON diary_entries(year, month);
CREATE INDEX IF NOT EXISTS idx_diary_type ON diary_entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_diary_word_count ON diary_entries(word_count);

-- 创建全文搜索索引（用于内容搜索）
CREATE VIRTUAL TABLE IF NOT EXISTS diary_fts USING fts5(date, content, file_source);

-- 统计表（可选，用于快速查询统计信息）
CREATE TABLE IF NOT EXISTS diary_stats (
    year INTEGER PRIMARY KEY,
    total_entries INTEGER DEFAULT 0,
    total_words INTEGER DEFAULT 0,
    first_entry_date DATE,
    last_entry_date DATE,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
-- ============================================================================
-- 以下为摘要相关表（batch_summary 写入，Web 只读）
-- 这里是"最终形态"（含情绪列）：新建库一次到位，旧库缺列由
-- SummaryStore.migrate() 自动补齐（见 summary_database.py 的 LEGACY_COLUMNS）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS summary_algorithms (
    fingerprint TEXT PRIMARY KEY,                  -- 算法指纹（sha256）
    algorithm_version TEXT NOT NULL,               -- 算法版本常量
    prompt_hash TEXT NOT NULL,                     -- Prompt 内容哈希
    model TEXT NOT NULL,                           -- 实际使用的模型名
    parameters_json TEXT NOT NULL,                 -- 温度/token/截断长度等
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entry_summaries (
    entry_key TEXT PRIMARY KEY,                    -- v1:{date}:{entry_type}（与自增 id 无关）
    entry_date TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    source_hash TEXT NOT NULL,                     -- 正文 sha256（变则摘要过期）
    algorithm_fingerprint TEXT NOT NULL,           -- 生成这份摘要用的算法
    cache_key TEXT NOT NULL,                       -- 断点续跑命中判定用
    status TEXT NOT NULL CHECK(status IN ('ok', 'empty', 'failed')),
    summary TEXT NOT NULL DEFAULT '',
    error TEXT,
    generated_at TEXT,
    updated_at TEXT NOT NULL,
    emotion TEXT NOT NULL DEFAULT '',              -- 情绪标签（模型只回一个词）
    emotion_status TEXT,                           -- ok/empty/failed；NULL=未评估
    emotion_cache_key TEXT,
    emotion_algorithm_fingerprint TEXT,            -- 与摘要指纹彼此独立
    emotion_error TEXT,
    FOREIGN KEY(algorithm_fingerprint) REFERENCES summary_algorithms(fingerprint),
    UNIQUE(entry_date, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_entry_summaries_date ON entry_summaries(entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_year_month ON entry_summaries(year, month);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_type ON entry_summaries(entry_type);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_status ON entry_summaries(status);
CREATE INDEX IF NOT EXISTS idx_entry_summaries_emotion ON entry_summaries(emotion);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entry_summaries_cache_key ON entry_summaries(cache_key);

CREATE TABLE IF NOT EXISTS summary_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    algorithm_fingerprint TEXT NOT NULL,
    scope_json TEXT NOT NULL,                      -- 本轮范围（年份/类型/limit/emotion_only）
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'interrupted', 'failed')),
    total INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    generated INTEGER NOT NULL DEFAULT 0,
    reused INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    emotion_algorithm_fingerprint TEXT,            -- Web 据此判断"情绪算法已过期"
    FOREIGN KEY(algorithm_fingerprint) REFERENCES summary_algorithms(fingerprint)
);
