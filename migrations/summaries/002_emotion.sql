-- 情绪分类：与摘要同一条记录，但拥有独立的算法指纹与缓存键，
-- 因此"补情绪"或"改情绪标签/prompt"都不会让已跑完的摘要失效。
-- 注意：ALTER TABLE ADD COLUMN 不允许 UNIQUE/PRIMARY KEY；合法性由 Python 侧
-- 的标签常量（根 .env 的 EMOTION_LABELS）保证，故这里不加 CHECK。

ALTER TABLE entry_summaries ADD COLUMN emotion TEXT NOT NULL DEFAULT '';
ALTER TABLE entry_summaries ADD COLUMN emotion_status TEXT;                -- ok/empty/failed；NULL=未评估
ALTER TABLE entry_summaries ADD COLUMN emotion_cache_key TEXT;
ALTER TABLE entry_summaries ADD COLUMN emotion_algorithm_fingerprint TEXT;
ALTER TABLE entry_summaries ADD COLUMN emotion_error TEXT;

-- 该轮运行使用的情绪算法指纹：Web 侧据此判断"情绪算法已过期"
ALTER TABLE summary_runs ADD COLUMN emotion_algorithm_fingerprint TEXT;

CREATE INDEX IF NOT EXISTS idx_entry_summaries_emotion ON entry_summaries(emotion);
