# 日记管理与检索系统

一个纯本地的日记管理与检索系统，支持日记导入、全文搜索、AI 摘要生成和统计分析。

## 功能特性

- 📝 **日记导入**：智能识别多种日记格式，自动分类和解析
- 🔍 **全文搜索**：基于 SQLite FTS5 的高效全文检索
- 🤖 **AI 摘要**：使用本地 LLM 为每条日记生成摘要
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
│   ├── 01_02.txt
│   └── ...
├── 2021/
│   ├── 01_01.txt    # 多日合一（内容中包含日期标记）
│   └── ...
└── ...
```

支持的日期格式：
- 文件名：`MM_DD.txt`（如 `01_15.txt`）
- 内容中的日期标记：`0115`、`01_15`、`1月15日`、`01/15`

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

### 4. 运行单元测试

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
