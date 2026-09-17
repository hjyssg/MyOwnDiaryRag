# 日记管理与检索系统

纯本地运行的日记管理与检索系统：**导入 → 全文检索 → 逐篇摘要 → 统计分析 → 网页回看**。
所有数据处理都在本机完成，日记内容不会上传到云端。

## 📚 文档导航

本项目由三个相对独立的模块组成，每个模块都有各自的详细文档：

| 模块 | 能做什么 | 详细文档 |
|------|----------|----------|
| **核心**（项目根目录） | 日记导入、SQLite FTS5 全文检索、年度字数统计、数据库结构 | 本文件 |
| **日记批量总结** | 用本地 LM Studio 模型为**每一篇**日记写摘要，生成按年份排列的《日记总结.md》 | [`scripts/batch_summary/README.md`](scripts/batch_summary/README.md) |
| **Web 浏览系统** | React + TypeScript 前端与 FastAPI 只读 API：浏览 / 搜索 / 摘要 / 回顾 | [`webapp/README.md`](webapp/README.md) |

## 功能特性

- 📝 **日记导入**：智能识别多种日记格式（单日 / 整月合集 / 多日合一），自动分类和解析
- 🔍 **全文搜索**：基于 SQLite FTS5 的高效全文检索
- 🧠 **日记批量总结**：用本地 LLM 为**每一篇**日记写一段摘要（不做重要性筛选），并额外判断情绪标签，按年份整理成目录 → [详细说明](scripts/batch_summary/README.md)
- 🌐 **网页浏览**：React 本地只读界面，支持浏览、搜索、摘要（可按情绪筛选）、「过去的今天」与随机回看 → [详细说明](webapp/README.md)
- 📊 **统计分析**：年度写作统计和趋势分析

## 系统要求

- Python 3.10+
- SQLite 3
- (可选) LM Studio - 用于日记批量总结

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

### 2. 年度统计

```bash
python scripts/yearly_stats.py
```

生成年度写作统计和趋势图表（图表输出为 `scripts/yearly_word_stats.png`，该图不入库）。

### 3. 日记批量总结（本地 LLM 逐篇写摘要）

用本地 LM Studio 模型逐篇阅读数据库中的日记，为**每一篇**写一段摘要（不做"重要/不重要"的筛选），
再额外判断一次**情绪标签**（默认 8 类：快乐/平淡/悲伤/生气/焦虑/疲惫/期待/其他），
生成按年份排列的 `日记总结.md`，并将摘要与情绪逐篇提交到同一个 SQLite 数据库供 Web 查询与筛选。

```bash
python scripts/batch_summary/main.py --models             # 1) 确认本地模型名（写入 .env）
python scripts/batch_summary/main.py --test --samples 10  # 2) 抽样试跑（同时打印情绪判断结果）
python scripts/batch_summary/main.py --all                # 3) 全量生成（可 Ctrl+C，重跑续跑）
python scripts/batch_summary/main.py --emotion-only       # 4) 只给老库补情绪（摘要一条都不重跑）
```

命令行参数、实时进度与中途预览、产物位置、断点续跑、Prompt 与摘要长度调整，
以及 `--year` / `--include-stock` / `--force` 等全部选项，见
**[`scripts/batch_summary/README.md`](scripts/batch_summary/README.md)**。

### 4. 网页浏览（本地只读）

在浏览器里回看日记：浏览 / 全文搜索 /「过去的今天」/ 随机一天。

```bash
pip install -r webapp/requirements.txt
cd frontend && npm ci && npm run build && cd ..
python webapp/app.py
```

打开 <http://127.0.0.1:8000> 即可。页面入口、REST API 与维护说明见
**[`webapp/README.md`](webapp/README.md)**。

### 5. 运行单元测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

测试覆盖日记批量总结模块和 FastAPI 契约。API 测试依赖可通过
`pip install -r webapp/requirements-dev.txt` 安装。

## 项目结构

```
MyOwnDiaryRag/
├── README.md                  # 本文件：总览 + 核心模块用法 + 文档导航
├── .env.example               # 配置模板（复制为 .env 后修改路径）
├── config.py                  # 读取根目录 .env（DATABASE_PATH / DIARY_BASE_PATH）
├── database.py                # 只读 Database 类：所有 SQL 都封装在这里
├── create_diary_db.sql        # 建表 SQL（含 FTS5 虚拟表与触发器）
├── scripts/
│   ├── import_diary_to_db.py  # 日记导入（智能识别文件类型）
│   ├── yearly_stats.py        # 年度字数统计 + 趋势图
│   └── batch_summary/         # 日记批量总结（本地 LLM）→ README.md
├── webapp/                    # 本地只读 Web 浏览系统       → README.md
├── tests/                     # 单元测试（无需真实 LLM）
└── diary_database.db          # SQLite 数据库（被 .gitignore 忽略，需自行生成）
```

## 数据库结构

### 主表：diary_entries

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| date | DATE | 日记日期 |
| year/month/day | INTEGER | 年/月/日 |
| content | TEXT | 日记内容 |
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

- **数据库**：SQLite + FTS5 全文搜索（统一由根目录 `database.py` 的只读 `Database` 类访问）
- **AI 模型**：LM Studio 本地模型（仅用于日记批量总结，非本机地址会被拒绝）
- **Web 层**：React + TypeScript + Vite SPA；FastAPI 提供只读 JSON API 与生产静态包
- **摘要存储**：与原始日记同一个 SQLite，使用稳定业务键和正文/算法 SHA-256 指纹
- **情绪标签**：摘要之外的第二条派生数据，拥有**独立**的算法指纹与缓存键（补情绪不会让摘要失效）

## 关于为何移除 RAG 问答

该类自然语言问答在个人日记场景里很难保证“稳定正确”，核心原因是：

- 统计口径常常不唯一（例如“去了几次”到底按天数、场次、提及次数还是实际出行）
- 文本里存在计划、回忆、引用、吐槽等噪声，关键词命中不等于事实发生
- 缺少明确标注数据时，模型与规则都只能做近似推断，无法给出可验证的确定答案

因此当前版本定位为：**导入 + 检索 + 日记批量总结 + 统计 + 本地网页回看**，不再提供 RAG 问答入口。

> 备注：随着未来 LLM 模型能力、长上下文与工具调用稳定性继续提升，
> 在口径先定义清楚的前提下，问答效果有机会明显改善；后续可再评估是否重启该能力。

## 注意事项

- 数据库文件（`*.db`）、`.env` 配置与批量总结产物（`scripts/batch_summary/output/`）都不会被提交到 Git
- 所有数据处理都在本地进行，不会上传到云端
- 建议定期备份数据库文件

## 相关文档

- 日记批量总结（本地 LLM 逐篇写摘要）：[`scripts/batch_summary/README.md`](scripts/batch_summary/README.md)
- Web 浏览系统（FastAPI 只读界面 + REST API）：[`webapp/README.md`](webapp/README.md)

## License

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
