# 日记管理与检索系统

一个纯本地的日记管理与检索系统，支持日记导入、全文搜索、AI 摘要生成和统计分析。

## 功能特性

- 📝 **日记导入**：智能识别多种日记格式，自动分类和解析
- 🔍 **全文搜索**：基于 SQLite FTS5 的高效全文检索
- 🤖 **AI 摘要**：使用本地 LLM 为每条日记生成摘要
- **年度回顾**：用本地 LLM 从日记中提取人生重要事件，生成按年份排列的年度目录
- 📊 **统计分析**：年度写作统计和趋势分析

## 系统要求

- Python 3.7+
- SQLite 3
- (可选) LM Studio - 用于 AI 摘要功能

## 安装配置

### 1. 克隆项目

```bash
git clone https://github.com/hjyssg/MyOwnDiaryRag.git
cd MyOwnDiaryRag
```

### 2. 配置路径

复制配置文件模板并编辑：

```bash
cp .env.example .env
```

编辑 `.env` 文件，设置你的日记文件夹路径：

```
# 日记文件夹根目录（包含按年份组织的文件夹）
DIARY_BASE_PATH=/path/to/your/diary/folder

# 数据库文件路径
DATABASE_PATH=/path/to/your/diary/folder/database_tools/diary_database.db
```

### 3. 日记文件组织规范

日记文件应按以下结构组织：

```
diary_folder/
├── 2020/
│   ├── 01_01.txt    # 单日日记
│   ├── 01月.txt     # 整月合集（内容按日期标记拆分成单日条目）
│   ├── 01月-旅行记录.txt  # 整月合集带标题变体
│   └── ...
├── 2021/
│   ├── 01_01.txt    # 多日合一（内容中包含日期标记）
│   └── ...
└── ...
```

支持的日期格式：
- 文件名：`MM_DD.txt`（如 `01_15.txt`）
- 整月合集文件名：`MM月.txt`、`MM月-标题.txt`（如 `01月.txt`、`05月-旅行记录.txt`），此类文件会按内容中的日期标记拆分成单日条目
- 内容中的日期标记（整月合集/多日合一、股票日记等每段的第一行）：
  - `mmdd`（如 `0101`）
  - `mmdd 周X` / `mmdd 星期X`（如 `0101 周日`、`0101 星期三`）
  - `MM_DD`、`M月D日`、`MM/DD`

## 使用方法

### 1. 导入日记到数据库

```bash
python scripts/import_diary_to_db.py
```

这将扫描日记文件夹，智能识别文件类型，并导入到 SQLite 数据库。

### 2. 生成 AI 摘要（可选）

需要先启动 LM Studio 并加载模型（如 Gemma）。

抽样测试（测试 10 条）：
```bash
python scripts/build_summaries.py --test
```

全量生成：
```bash
python scripts/build_summaries.py --all
```

### 3. 年度统计

```bash
python scripts/yearly_stats.py
```

### 4. 年度日记回顾（本地 LLM 提取人生重要事件）

用本地 LM Studio 模型逐篇阅读数据库中的日记，提取"多年以后值得回看的人生重要事件"，
生成按年份排列的 `年度日记回顾.md`。全程本地运行，数据库以只读方式访问。

```bash
# 1) 先确认 LM Studio 中的实际模型名（不要猜），并按提示把 LLM_MODEL 写入 .env
python scripts/yearly_review/main.py --models

# 2) 抽样试跑（跨年份抽样，只打印，不写状态/输出文件）
python scripts/yearly_review/main.py --test --samples 10

# 3) 全量生成（可随时 Ctrl+C，重跑自动续跑，已处理的条目不会再调用模型）
python scripts/yearly_review/main.py --all

# 4) 不调用模型，仅用已有中间结果重新生成 Markdown
python scripts/yearly_review/main.py --rebuild-md

# 5) 想看进度（可选）：主程序运行时自己就会持续打印进度，这一步通常不需要
python scripts/yearly_review/status.py
```

- **运行期间程序自己打印实时进度**（默认每 30 秒一块，中文、人类可读）：
  已处理 xx / xx 篇（覆盖 xx / xx 天）、当前阶段（读取日记 / 调用模型 /
  生成年度重要事件 / 保存结果）、正在处理哪一天、成功/失败数、速度与预计剩余。
  也可直接在编辑器里打开 `<运行目录>\运行状态.txt` 查看，无需任何命令。
  调整间隔：`--heartbeat 60`，关闭：`--no-heartbeat`。
- **全量跑几小时也能中途看结果**：最终 `年度日记回顾.md` 只在整轮跑完才写，
  但运行期间主程序会自动刷新运行目录里的 **`中途预览.md`**（默认每 60 秒，正文与最终产物
  逐行一致），随时打开就能看到已提取的部分；`--preview-every 120` 调整间隔，
  `--preview-every 0` / `--no-preview` 关闭。
- **每次运行的产物放在 `scripts/yearly_review/output/<YYMMDDHHMMSS>/` 时间戳子目录**里
  （`年度日记回顾.md` / `中途预览.md` / `yearly_events.json` / `progress.json` / `运行状态.txt` /
  `待复核_判定无事件.md` / `yearly_review.log`），历史互不覆盖；
  断点状态固定在 `output/review_state.json`，跨运行共享，重跑即续跑。
- Prompt 独立配置：`scripts/yearly_review/prompts/yearly_review_prompt.txt`
- 详细说明：[`scripts/yearly_review/README.md`](scripts/yearly_review/README.md)
- 安全约定：`LLM_BASE_URL` 非本机地址会被直接拒绝，日记内容不出本机；
  数据库只读（`mode=ro`），原始日记不修改、不删除

### 5. 运行单元测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

生成年度写作统计和趋势图表。

## 数据库结构

### 主表：diary_entries

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| date | DATE | 日记日期 |
| year/month/day | INTEGER | 年/月/日 |
| content | TEXT | 日记内容 |
| summary | TEXT | AI 生成的摘要 |
| file_source | TEXT | 源文件路径 |
| entry_type | TEXT | 条目类型 |
| word_count | INTEGER | 字数 |

### 条目类型

- `single_day`：单日单篇
- `multi_day`：多日合一
- `stock_diary`：股票日记
- `retrospective`：早期回忆
- `summary`：总结类
- `note`：笔记类

## 技术架构

- **数据库**：SQLite + FTS5 全文搜索
- **AI 模型**：LM Studio（仅用于摘要生成）

## 关于为何移除 RAG 问答

该类自然语言问答在个人日记场景里很难保证“稳定正确”，核心原因是：

- 统计口径常常不唯一（例如“去了几次”到底按天数、场次、提及次数还是实际出行）
- 文本里存在计划、回忆、引用、吐槽等噪声，关键词命中不等于事实发生
- 缺少明确标注数据时，模型与规则都只能做近似推断，无法给出可验证的确定答案

因此当前版本定位为：**导入 + 检索 + 摘要 + 统计**，不再提供 RAG 问答入口。

> 备注：随着未来 LLM 模型能力、长上下文与工具调用稳定性继续提升，
> 在口径先定义清楚的前提下，问答效果有机会明显改善；后续可再评估是否重启该能力。

## 注意事项

- 数据库文件和 `.env` 配置文件不会被提交到 Git
- 所有数据处理都在本地进行，不会上传到云端
- 建议定期备份数据库文件

## License

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
