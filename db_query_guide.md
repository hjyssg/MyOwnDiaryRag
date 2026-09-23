# 日记库查询指南（给本地小模型用）

供本地小模型把「自然语言问题 → 一条 SQL」用的提示词素材。**只读**，只允许 `SELECT`。
内容按「能塞进短上下文」写：表 2 张、规则 7 条、示例按问题类型分组。

> 本页**故意不写死**条数、年份范围、情绪标签：它们随导入和 `.env` 变化，SQL 里也不要依赖具体数字。

## 0. 直接复制到系统提示词的部分

```text
你是日记库查询助手。数据库是 SQLite，文件 diary_database.db，只读。
用户用中文问问题。你只输出一条 SELECT 语句：不要解释、不要 markdown 代码块、不要多条语句。
规则：
1. 只能 SELECT；禁止 INSERT/UPDATE/DELETE/DROP/CREATE/PRAGMA/ATTACH。
2. 只查这 2 张表：diary_entries（正文）、entry_summaries（摘要+情绪）。
3. 必须写 LIMIT（默认 100，最多 300）。
4. 输出正文一律用 substr(content, 1, 100)，绝不 SELECT 整段 content。
5. 日期题用 year / month / day 三个整数列，不要用 strftime。
6. 中文关键词模糊匹配用 content LIKE '%词%' 或 summary LIKE '%词%'。
7. 查「摘要 / 情绪」走 entry_summaries；查「原文某个词」走 diary_entries。
```

## 1. 表结构（只列这 2 张，其它表都不要用）

### diary_entries —— 日记正文（一天可能有多条）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER | 主键，无业务含义 |
| `date` | TEXT | `YYYY-MM-DD`，和 year/month/day 同义 |
| `year` / `month` / `day` | INTEGER | 年 / 月 / 日，**筛日期优先用这三个** |
| `content` | TEXT | 正文，可能很长 → 预览必须 `substr(content,1,100)` |
| `entry_type` | TEXT | 只有 5 个值：`diary` 普通日记、`stock_diary` 股票日记、`note` 随手记、`retrospective` 早年回忆、`summary` 阶段总结 |
| `word_count` | INTEGER | 字数，可用于「最长/最短的一篇」 |

索引：`date`、`year`、`(year, month)`、`entry_type`、`word_count`。

### entry_summaries —— 每篇的摘要 + 情绪（只覆盖一部分篇目）

| 列 | 类型 | 说明 |
|---|---|---|
| `entry_date` / `entry_type` | TEXT | 与 `diary_entries.date` / `entry_type` 一一对应，**JOIN 就用这两列** |
| `year` / `month` / `day` | INTEGER | 同上 |
| `summary` | TEXT | 该篇一句话摘要 |
| `emotion` | TEXT | 情绪标签，取值以根 `.env` 的 `EMOTION_LABELS` 为准（`config.get_emotion_labels()`，默认 `快乐,平淡,悲伤,生气,焦虑,疲惫,期待,其他`） |
| `status` | TEXT | `ok` / `empty` / `failed`，统计时加 `status = 'ok'` |
| `word_count` | INTEGER | 该篇字数 |

⚠️ 摘要表**只覆盖一部分篇目**（相当一部分 `stock_diary` 默认不生成摘要）：
「按摘要/情绪统计」得到的是有摘要的那部分，不等于全库；要全库数字请查 `diary_entries`。

## 2. 必须知道的坑

| 坑 | 正确做法 |
|---|---|
| **没有中文分词**：`content` 只能用子串匹配，没有词库/分词 | 中文关键词一律 `content LIKE '%词%'`；实测全库 LIKE 仅约 0.01 秒，不用担心慢 |
| **一天可能不止一条**：同一天可能有 `diary` + `stock_diary` 等多条 | 问「某天发生了什么」要列当天所有条目，不要假设唯一 |
| **`entry_summaries` 是派生数据**，可能落后于正文 | 用 JOIN 时优先 `JOIN ... ON e.date=s.entry_date AND e.entry_type=s.entry_type`，并按需 `s.status='ok'` |
| `content` 很长 | 永远 `substr(content,1,100)` 预览 |
| 情绪标签由根 `.env` 的 `EMOTION_LABELS` 决定（`config.get_emotion_labels()`） | 只用该标签集里的值精确匹配；不要写 `LIKE '%高兴%'` 猜别名 |
| `date` 是文本 | 比较用 `date >= '2025-01-01'`（ISO 字符串可直接比大小） |
| 大范围统计 | 用 `COUNT(*)` / `SUM(word_count)`，不要把行取回来 |

**不要查的表**：`diary_stats`（可能过期）、`summary_algorithms`、`summary_runs`、`summary_schema_migrations`。

## 3. 示例 SQL（照抄改词即可）

**数 / 统计**
```sql
-- 一共有多少篇
SELECT COUNT(*) FROM diary_entries;
-- 各年份篇数与总字数
SELECT year, COUNT(*) AS entries, SUM(word_count) AS words FROM diary_entries GROUP BY year ORDER BY year;
-- 各类型分布
SELECT entry_type, COUNT(*) AS n FROM diary_entries GROUP BY entry_type ORDER BY n DESC;
-- 哪个年份写得最多
SELECT year, COUNT(*) AS n FROM diary_entries GROUP BY year ORDER BY n DESC LIMIT 1;
-- 一共写了多少字
SELECT SUM(word_count) AS total_words FROM diary_entries;
```

**按日期找**
```sql
-- 某一天的全部条目
SELECT date, entry_type, word_count, substr(content,1,100) AS preview
FROM diary_entries WHERE date = '2025-01-01' ORDER BY id LIMIT 100;
-- 某个月
SELECT date, entry_type, substr(content,1,100) FROM diary_entries
WHERE year = 2024 AND month = 7 ORDER BY date LIMIT 100;
-- 某年全部（只给预览）
SELECT date, entry_type, substr(content,1,100) FROM diary_entries
WHERE year = 2020 ORDER BY date LIMIT 100;
-- 时间范围（区间用文本比较）
SELECT date, entry_type, substr(content,1,100) FROM diary_entries
WHERE date >= '2025-06-01' AND date <= '2025-06-30' ORDER BY date LIMIT 100;
-- 过去的今天（跨年份同月同日）
SELECT date, year, entry_type, substr(content,1,100) FROM diary_entries
WHERE month = 9 AND day = 23 ORDER BY year LIMIT 100;
-- 某天的日记，不要股票流水
SELECT date, entry_type, substr(content,1,100) FROM diary_entries
WHERE date = '2025-01-01' AND entry_type != 'stock_diary' LIMIT 100;
```

**按关键词（中文用 LIKE）**
```sql
-- 正文提到「旅行」的日记
SELECT date, entry_type, substr(content,1,100) FROM diary_entries
WHERE content LIKE '%旅行%' ORDER BY date DESC LIMIT 100;
-- 同时提到两个词
SELECT date, substr(content,1,100) FROM diary_entries
WHERE content LIKE '%旅行%' AND content LIKE '%飞机%' ORDER BY date DESC LIMIT 100;
-- 摘要里提到「加班」，并用摘要表（更快）
SELECT entry_date, entry_type, summary, emotion FROM entry_summaries
WHERE summary LIKE '%加班%' ORDER BY entry_date DESC LIMIT 100;
```

**情绪 / 摘要**
```sql
-- 所有「快乐」的日记摘要
SELECT entry_date, entry_type, emotion, summary FROM entry_summaries
WHERE emotion = '快乐' AND status = 'ok' ORDER BY entry_date DESC LIMIT 100;
-- 某年各种情绪的篇数
SELECT emotion, COUNT(*) AS n FROM entry_summaries
WHERE year = 2024 AND status = 'ok' GROUP BY emotion ORDER BY n DESC;
-- 情绪按年变化
SELECT year, emotion, COUNT(*) AS n FROM entry_summaries
WHERE status = 'ok' AND emotion IN ('快乐','悲伤','生气') GROUP BY year, emotion ORDER BY year;
-- 情绪 + 正文预览（JOIN 正文表）
SELECT e.date, e.entry_type, s.emotion, substr(e.content,1,100) AS preview
FROM entry_summaries s
JOIN diary_entries e ON e.date = s.entry_date AND e.entry_type = s.entry_type
WHERE s.emotion = '焦虑' AND s.status = 'ok'
ORDER BY e.date DESC LIMIT 100;
```

**最长 / 最短 / 随机**
```sql
-- 最长的一篇
SELECT date, entry_type, word_count, substr(content,1,100) FROM diary_entries ORDER BY word_count DESC LIMIT 5;
-- 随机回看一篇普通日记
SELECT date, entry_type, substr(content,1,200) FROM diary_entries
WHERE entry_type = 'diary' ORDER BY RANDOM() LIMIT 1;
-- 早年回忆
SELECT date, substr(content,1,200) FROM diary_entries WHERE entry_type = 'retrospective' ORDER BY date LIMIT 100;
```

## 4. 组装答案

拿到 SQL 结果后回答用户：
1. 先说数字，再列条目，每条给 `日期 + 类型 + 预览`；
2. 预览里的 `\n`、连续空白先压成空格再展示；
3. 结果为空就直说「没有找到」，不要编造；
4. 命中很多时说明「共 N 条，下面是最近 100 条左右」。

## 试用cmd工具
```bash
sqlite3 diary_database.db  "SELECT COUNT(*) FROM diary_entries WHERE content LIKE '%漫展%';"
```