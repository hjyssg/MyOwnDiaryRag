# 日记批量摘要

用本地 LM Studio 逐篇给日记写摘要，并额外判断一个情绪标签。
结果存在 `.env` 里 `DATABASE_PATH` 指向的同一个 SQLite 中，只调用本机模型。

## 快速开始

```bash
python batch_summary/main.py --models              # 先确认模型名（需要 LM Studio 已启动）
python batch_summary/main.py --test --samples 10   # 抽样试跑：只打印，不写文件
python batch_summary/main.py --all                 # 全量（可 Ctrl+C，重跑自动续跑）
```

产物只有一个文件：项目根目录下的 `output/中途预览.md`
—— 就在仓库最外层（与 `scripts/`、`webapp-*/` 平级），每次运行覆盖同一个文件。
运行期间每 60 秒刷新一次（可随时打开看进度）；跑完 / 中断时重写成最终版，
标题变成 `# 日记总结` 并在头部标记**生成日期**。

## 常用命令

| 命令 | 作用 |
|---|---|
| `--models` | 列出 LM Studio 可见的模型 |
| `--test --samples 10` | 抽样 10 篇试跑，只打印 |
| `--all` | 全量生成；中断后重跑同一条命令即续跑 |
| `--year 2024` / `--years 2020-2024` | 只跑指定年份 |
| `--emotion-only` | 只补情绪，摘要复用 |
| `--force-emotion` | 重算情绪（摘要仍按缓存） |
| `--rebuild-md` | 不调模型，用库里已有摘要重写预览 |
| `--reset-summaries` | 清空摘要表（含情绪），不动原始日记 |
| `--no-preview` | 不写任何文件，只打印进度 |

## 什么时候会重新调用模型？

默认走缓存：同一篇只要**日期 + 类型 + 正文**没变，就不会再调用模型。
摘要与情绪的缓存彼此独立。

| 你改了什么 | 结果 |
|---|---|
| 想全部重算 | `--all --force`（摘要）＋ `--force-emotion`（情绪） |
| 摘要 Prompt | 摘要全部重算 |
| `LLM_MODEL` / `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `LLM_JSON_MODE` / `LLM_REASONING_EFFORT` | 摘要全部重算 |
| 情绪 Prompt / `EMOTION_LABELS` / `LLM_EMOTION_MAX_TOKENS` | 只有情绪重算，摘要不受影响 |
| `LLM_TIMEOUT` / `LLM_BASE_URL` / 心跳与预览间隔 | 不重算 |
| 重新导入日记（`import_diary_to_db.py`） | 不自动全量重算；只有正文或日期/类型变了的篇目会重算 |

注意事项：

- `--all` 默认**不含** `stock_diary`（炒股流水），要一起处理加 `--include-stock`；
- `--force` 只管摘要，情绪仍走缓存；
- `failed` 的篇目下次会自动重试。

## 数据库

所有表定义集中在根目录 `create_diary_db.sql`（含 FTS5 虚拟表，无触发器）：

- `diary_entries` / `diary_fts` / `diary_stats`：原始日记、全文索引、年度统计；
- `entry_summaries`：每篇的摘要 + 情绪（batch 是唯一写入者，Web 只读）；
- `summary_algorithms`：算法指纹与参数（改 Prompt / 换模型会新增一条）；
- `summary_runs`：每次运行的状态与统计。

`create_diary_db.sql` 全部用 `IF NOT EXISTS` 写成，可重复执行：`--all` 会先跑它补齐缺的表；
早期版本建的摘要表若缺情绪列，会自动补列（不重建表、不动已有数据）。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```