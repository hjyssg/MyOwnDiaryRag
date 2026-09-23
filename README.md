# 日记管理与检索系统

纯本地运行的日记管理与检索系统：**导入 → 全文检索 → 逐篇摘要 → 统计分析 → 网页回看**。
所有数据处理都在本机完成，日记内容不会上传到云端。

## 📚 文档导航

本项目由三个相对独立的模块组成，每个模块都有各自的详细文档：

| 模块 | 能做什么 | 详细文档 |
|------|----------|----------|
| **核心**（项目根目录） | 日记导入、SQLite FTS5 全文检索、年度字数统计、数据库结构 | 本文件 |
| **数据库查询指南** | 给本地小模型用的「自然语言 → SQL」提示词素材：表结构、易错点、可照抄的 SELECT 示例 | [`db_query_guide.md`](db_query_guide.md) |
| **日记批量总结** | 用本地 LM Studio 模型为**每一篇**日记写摘要，生成按年份排列的《中途预览.md》（跑完即最终版） | [`batch_summary/README.md`](batch_summary/README.md) |
| **Web 浏览系统** | React + TypeScript 前端与 FastAPI 只读 API：浏览 / 搜索 / 摘要 / 回顾 | [`webapp-backend/README.md`](webapp-backend/README.md) |

## 功能特性

- 📝 **日记导入**：智能识别多种日记格式（单日 / 整月合集 / 多日合一），统一拆成单天入库
- 🔍 **全文搜索**：基于 SQLite FTS5 的高效全文检索
- 🧠 **日记批量总结**：用本地 LLM 为**每一篇**日记写一段摘要（不做重要性筛选），并额外判断情绪标签，按年份整理成目录 → [详细说明](batch_summary/README.md)
- 🌐 **网页浏览**：React 本地只读界面，支持浏览、搜索、摘要（可按情绪筛选）、「日期查找」与随机回看 → [详细说明](webapp-backend/README.md)
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

入库后的 `entry_type`（条目分类）只有五种：`diary`（普通日记）、`stock_diary`（股票日记）、
`note`（笔记）、`retrospective`（早年回忆）、`summary`（学期/阶段总结）。
「单日文件还是多日合一」只是导入时的解析方式，不再写进数据库。

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

用本地 LM Studio 模型逐篇阅读数据库中的日记，为**每一篇**写一段摘要

详细见
**[`batch_summary/README.md`](batch_summary/README.md)**。

### 4. 网页浏览（本地只读）

在浏览器里回看日记：浏览 / 全文搜索 /「日期查找」/ 随机一天。

```bash
cd webapp-frontend && npm ci && npm run build && cd ..   # 构建前端（只需一次，产物 dist/ 由后端托管）
python webapp-backend/app.py                            # 启动后端，访问 http://127.0.0.1:8000
```

### 5. 运行单元测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

测试覆盖日记批量总结模块和 FastAPI 契约。API 测试依赖可通过
`pip install -r webapp-backend/requirements-dev.txt` 安装。

## 项目结构

```
MyOwnDiaryRag/
├── README.md                  # 本文件：总览 + 核心模块用法 + 文档导航
├── .env.example               # 配置模板（复制为 .env 后修改路径）
├── config.py                  # 读取根目录 .env（DATABASE_PATH / DIARY_BASE_PATH）
├── database.py                # 只读 Database 类：所有 SQL 都封装在这里
├── create_diary_db.sql        # 所有表定义：日记表 + 摘要表 + FTS5 虚拟表（无触发器）
├── scripts/
│   ├── import_diary_to_db.py  # 日记导入（智能识别文件类型）
│   └── yearly_stats.py        # 年度字数统计 + 趋势图
├── batch_summary/             # 日记批量总结（本地 LLM，与 scripts/ 平级）→ README.md
├── webapp-backend/            # 本地只读 Web 后端（FastAPI，托管前端产物）→ README.md
├── webapp-frontend/           # React 前端源码（npm run build 产出 dist/）
├── tests/                     # 单元测试（无需真实 LLM）
└── diary_database.db          # SQLite 数据库（被 .gitignore 忽略，需自行生成）
```

## 技术架构

- **数据库**：SQLite + FTS5 全文搜索（统一由根目录 `database.py` 的只读 `Database` 类访问）
- **AI 模型**：LM Studio 本地模型（仅用于日记批量总结，非本机地址会被拒绝）
- **Web 层**：React + TypeScript + Vite SPA；FastAPI 提供只读 JSON API 与生产静态包
- **摘要存储**：与原始日记同一个 SQLite，使用稳定业务键和正文/算法 SHA-256 指纹
- **情绪标签**：摘要之外的第二条派生数据，拥有**独立**的算法指纹与缓存键（补情绪不会让摘要失效）

## 注意事项

- 数据库文件（`*.db`）、`.env` 配置与批量总结产物（`batch_summary/output/`）都不会被提交到 Git
- 所有数据处理都在本地进行，不会上传到云端
- 建议定期备份数据库文件

## 相关文档

- 日记批量总结（本地 LLM 逐篇写摘要）：[`batch_summary/README.md`](batch_summary/README.md)
- Web 浏览系统（FastAPI 只读界面 + REST API）：[`webapp-backend/README.md`](webapp-backend/README.md)
- 数据库查询指南（小模型 text2sql 提示词素材）：[`db_query_guide.md`](db_query_guide.md)

## License

MIT License


