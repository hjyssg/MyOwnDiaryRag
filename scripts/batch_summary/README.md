# 日记批量摘要

使用 LM Studio 的 OpenAI-compatible 本地接口逐篇生成摘要，并为每篇额外判断一个**情绪标签**。
原始正文、摘要与情绪都保存在 `DATABASE_PATH` 指向的同一个 SQLite 文件中；
所有模型请求默认只允许本机地址。

## 使用

```bash
python scripts/batch_summary/main.py --models
python scripts/batch_summary/main.py --test --samples 10
python scripts/batch_summary/main.py --all
python scripts/batch_summary/main.py --year 2024
python scripts/batch_summary/main.py --rebuild-md
python scripts/batch_summary/main.py --emotion-only     # 只补情绪（摘要复用已有结果）
```

`--all` 首次运行会执行 `migrations/summaries/`，并创建：

- `summary_algorithms`：算法指纹与参数审计（摘要与情绪各一套指纹）；
- `entry_summaries`：每篇日记当前摘要 + 情绪标签；
- `summary_runs`：批处理运行状态（同时记录本轮使用的摘要/情绪算法指纹）；
- `summary_schema_migrations`：schema 版本。

SQLite 是唯一摘要主状态。Markdown、JSON、中途预览、进度和待复核文件均为派生产物。
`日记总结.md` 与 `中途预览.md` 的每行都是「日期 +【情绪】+ 摘要」，两边正文逐行一致
（`--no-emotion` / 情绪判断失败 / 空正文的篇目省略方括号）。
每篇摘要/情绪处理结束后立即提交，因此中断后已提交记录不会丢失。

## 情绪判断（摘要之外的第二条数据）

每篇日记在摘要之后**再发一次很短的请求**，模型只回一个标签词（例如 `快乐`），Python 负责归一化：

- 标签集来自根 `.env` 的 `EMOTION_LABELS`（逗号分隔、保序、去重；**最后一项是兜底标签**），
  默认 `快乐,平淡,悲伤,生气,焦虑,疲惫,期待,其他`；batch 与 Web 共用同一份定义；
- 归一顺序：精确标签 → 别名（`开心`→`快乐`）→ 输出里包含标签 → 输出里包含别名 → 兜底标签；
  兜底时记一条 warning，日志里能看到模型的原始输出，便于调整 Prompt；
- 情绪 Prompt 在 `prompts/diary_emotion_prompt.txt`（占位符 `{DATE}` / `{ENTRY_TYPE}` / `{CONTENT}` / `{LABELS}`）；
- 调用参数与摘要不同：`temperature=0`、`max_tokens=LLM_EMOTION_MAX_TOKENS`（默认 32）、不请求 JSON 模式。

常用开关：

| 命令 | 作用 |
|------|------|
| `--no-emotion` | 本轮只写摘要，不判断情绪（等价于 `.env` 的 `EMOTION_ENABLED=0`） |
| `--emotion-only` | 摘要一律复用，只为缺情绪/情绪过期的篇目各发一次调用（老库补情绪用这个） |
| `--force-emotion` | 忽略情绪缓存重算情绪（摘要仍按原有缓存规则） |

情绪结果会写入 `entry_summaries.emotion / emotion_status`，网页端「日记摘要」页可按下拉筛选；
同时 `日记总结.md` / `中途预览.md` 的每一行会带上 `【标签】`（如 `- 0120【快乐】今天去公园散步……`），
标签来自模型判断，Markdown 这一层不做任何猜测。`--emotion-only` 只补情绪时，
中途预览同样会因为情绪条数变化而重排，不必等最终产物。

## 缓存规则

缓存键由以下内容的 SHA-256 确定（摘要与情绪**各自独立**，互不使对方失效）：

- 稳定条目键 `v1:{date}:{entry_type}`；
- 完整原始正文 SHA-256；
- 摘要：Prompt、实际模型、temperature、max tokens、reasoning effort、JSON mode、截断长度、
  清洗版本及摘要长度共同组成的算法指纹；
- 情绪：情绪 Prompt、标签集（含兜底标签）、label 版本、实际模型、分类参数共同组成的算法指纹。

相同缓存键的 `ok` 和 `empty` 会复用；`failed` 会重试；`--force` 无条件重新生成。
因此「改情绪标签 / 改情绪 Prompt / 只补情绪」都不会让已跑完的摘要失效。
重新导入导致数据库自增 ID 变化时，只要日期、类型和正文不变，仍会复用摘要与情绪。

## 范围与清理

默认处理除 `stock_diary` 外的全部类型。支持：

```bash
--year 2024
--years 2020-2024
--types single_day,note
--include-stock
--limit 10
--emotion-only            # 只补情绪（摘要复用），可与 --year / --years 组合
```

成功完成且未使用 `--limit` 时，仅清理本次 scope 中已经不存在的 orphan。中断、连续失败或
限制条数运行不会误删其他摘要。

## 导出与重置

`--rebuild-md` 完全不调用模型，从 SQLite 重新生成当前运行目录中的：

- `日记总结.md`
- `summaries.json`（version 4，每篇含 `emotion` / `emotion_status`）
- `待复核_未产出摘要.md/json`

只重建派生摘要数据时使用：

```bash
python scripts/batch_summary/main.py --reset-summaries
```

该命令只清空摘要相关表（含情绪），不修改 `diary_entries`、`diary_fts` 或 `diary_stats`。
不要删除整个数据库。

## 进度与安全

- `--heartbeat SECONDS` / `--no-heartbeat`
- `--preview-every SECONDS` / `--no-preview`
- 状态块与 `progress.json` 会额外显示情绪计数（有情绪 / 情绪失败 / 情绪跳过）；
  旧版 `progress.json` 没有这些字段时照常显示，不会报错。
- 默认绑定本地 LM Studio；只有显式 `ALLOW_REMOTE_LLM=1` 才允许远程地址。
- 日志和错误字段不保存完整正文或 Prompt。
- Web 使用只读连接，batch 是摘要表（含情绪列）的唯一写入者。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

pipeline 测试使用 fake client，不需要启动 LM Studio。