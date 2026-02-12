# 日记 RAG 系统

一个纯本地的日记管理和智能检索系统，支持日记导入、全文搜索、AI 摘要生成和智能问答。

## 功能特性

- 📝 **日记导入**：智能识别多种日记格式，自动分类和解析
- 🔍 **全文搜索**：基于 SQLite FTS5 的高效全文检索
- 🤖 **AI 摘要**：使用本地 LLM 为每条日记生成摘要
- 💬 **智能问答**：RAG 架构，基于日记内容回答问题
- 📊 **统计分析**：年度写作统计和趋势分析

## 系统要求

- Python 3.7+
- SQLite 3
- (可选) LM Studio - 用于 AI 摘要和问答功能

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

### 3. 智能问答

```bash
python scripts/diary_rag.py
```

交互式问答示例：
```
> 我去过几次日本？
> 2023年我去了哪里？
> 我初中的时候发生了什么？
```

### 4. 年度统计

```bash
python scripts/yearly_stats.py
```

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
- **AI 模型**：LM Studio（OpenAI 兼容 API）
- **RAG 架构**：混合检索（关键词 + 语义）+ LLM 生成

## 注意事项

- 数据库文件和 `.env` 配置文件不会被提交到 Git
- 所有数据处理都在本地进行，不会上传到云端
- 建议定期备份数据库文件

## License

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
