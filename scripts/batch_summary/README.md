# 日记批量摘要

使用 LM Studio 的 OpenAI-compatible 本地接口逐篇生成摘要。原始正文和摘要都保存在
`DATABASE_PATH` 指向的同一个 SQLite 文件中；所有模型请求默认只允许本机地址。

## 使用

```bash
python scripts/batch_summary/main.py --models
python scripts/batch_summary/main.py --test --samples 10
python scripts/batch_summary/main.py --all
python scripts/batch_summary/main.py --year 2024
python scripts/batch_summary/main.py --rebuild-md
```

`--all` 首次运行会执行 `migrations/summaries/`，并创建：

- `summary_algorithms`：算法指纹与参数审计；
- `entry_summaries`：每篇日记当前摘要；
- `summary_runs`：批处理运行状态；
- `summary_schema_migrations`：schema 版本。

SQLite 是唯一摘要主状态。Markdown、JSON、中途预览、进度和待复核文件均为派生产物。
每篇摘要处理结束后立即提交，因此中断后已提交记录不会丢失。

## 缓存规则

缓存键由以下内容的 SHA-256 确定：

- 稳定条目键 `v1:{date}:{entry_type}`；
- 完整原始正文 SHA-256；
- Prompt、实际模型、temperature、max tokens、reasoning effort、JSON mode、截断长度、
  清洗版本及摘要长度共同组成的算法指纹。

相同缓存键的 `ok` 和 `empty` 会复用；`failed` 会重试；`--force` 无条件重新生成。
重新导入导致数据库自增 ID 变化时，只要日期、类型和正文不变，仍会复用摘要。

## 范围与清理

默认处理除 `stock_diary` 外的全部类型。支持：

```bash
--year 2024
--years 2020-2024
--types single_day,note
--include-stock
--limit 10
```

成功完成且未使用 `--limit` 时，仅清理本次 scope 中已经不存在的 orphan。中断、连续失败或
限制条数运行不会误删其他摘要。

## 导出与重置

`--rebuild-md` 完全不调用模型，从 SQLite 重新生成当前运行目录中的：

- `日记总结.md`
- `summaries.json`
- `待复核_未产出摘要.md/json`

只重建派生摘要数据时使用：

```bash
python scripts/batch_summary/main.py --reset-summaries
```

该命令只清空摘要相关表，不修改 `diary_entries`、`diary_fts` 或 `diary_stats`。不要删除整个数据库。

## 进度与安全

- `--heartbeat SECONDS` / `--no-heartbeat`
- `--preview-every SECONDS` / `--no-preview`
- 默认绑定本地 LM Studio；只有显式 `ALLOW_REMOTE_LLM=1` 才允许远程地址。
- 日志和错误字段不保存完整正文或 Prompt。
- Web 使用只读连接，batch 是摘要表的唯一写入者。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

pipeline 测试使用 fake client，不需要启动 LM Studio。