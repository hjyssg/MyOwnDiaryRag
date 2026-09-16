# 📔 日记回溯 · Web 浏览系统

> 🏠 返回 [项目主 README](../README.md) ｜ 兄弟模块：[日记批量总结](../scripts/batch_summary/README.md)

一个纯**本地、只读**的日记浏览网页系统，构建在现有的
`diary_database.db`（SQLite + FTS5）之上。后端使用 **FastAPI**，
前端为轻量 **Jinja2 服务端渲染** + 少量原生 JS。数据全程不出本机。

## 目录

- [功能](#功能)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [REST API](#rest-api)
- [数据安全约定](#数据安全约定)
- [维护说明（面向后续 AI/开发者）](#维护说明面向后续-ai开发者)

## 功能

- 🗂️ **浏览日记**：按年份 / 月份 / 类型筛选，分页浏览，每篇含正文预览
- 📖 **内联展开阅读**：在多篇列表页（浏览 / 过去的今天）点击条目即可展开全文，无需跳转，
  自动关闭其他展开项（手风琴效果）；也可点击「在完整页面查看」打开独立阅读页
- 🔍 **全文搜索**：基于 SQLite FTS5 的关键词检索
- 🌟 **过去的今天**：输入月/日，回顾每一年的同一天你写了什么，
  支持「前一天 / 后一天」翻页（自动处理月末、年末与 2 月 29 日）
- 🎲 **随机一天**：从历年日记中随机抽取一天，直接展开阅读当天全部条目，
  可连续「再随机一篇」，并可一键跳转到该日期的「过去的今天」
- 📄 **阅读页**：查看全文，并列出同月其他篇目
- 📚 **REST API**：所有数据接口经 Pydantic 校验，自动生成交互式文档 `/docs`


## 快速开始

### 1. 环境准备

```bash
cd webapp
pip install -r requirements.txt
```

### 2. 配置

**前置条件**：数据库需先导入生成（见 [项目主 README](../README.md) 的「导入日记到数据库」）；
本系统只读，不会自动建库。

系统通过项目根目录的 `.env` + `config.py` 读取数据库路径，
无需在 `webapp/` 内重复配置。确认根目录 `.env` 的 `DATABASE_PATH` 指向
`diary_database.db` 即可。

### 3. 启动

方式一（推荐）：
```bash
python app.py
```

方式二：
```bash
uvicorn app:app --reload
```

Windows 也可直接双击 `run.bat`。

### 4. 访问

| 入口 | 地址 |
|------|------|
| 首页 | http://127.0.0.1:8000 |
| 浏览日记 | http://127.0.0.1:8000/browse |
| 过去的今天 | http://127.0.0.1:8000/on-this-day |
| 随机一天 | http://127.0.0.1:8000/random |
| API 交互文档 | http://127.0.0.1:8000/docs |

## 目录结构

```
webapp/
├── app.py            # FastAPI 主应用：页面路由 + REST API
├── schemas.py        # Pydantic 数据模型（校验 + 生成文档）
├── requirements.txt  # 依赖：fastapi / uvicorn[standard] / jinja2
├── run.bat           # Windows 一键启动
├── templates/        # Jinja2 页面模板
│   ├── base.html          # 母版（导航 + 布局）
│   ├── index.html         # 首页：年份总览
│   ├── browse.html        # 浏览：筛选 + 分页 + 搜索
│   ├── read.html          # 单篇阅读 + 同月侧栏
│   ├── on_this_day.html   # 过去的今天
│   └── random.html        # 随机一天
└── static/
    ├── style.css      # 样式
    └── app.js         # 少量前端交互
```

## REST API

所有接口返回 JSON，输入经 Pydantic 校验。详见 `/docs`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/years` | 年份统计（篇数 / 字数） |
| GET | `/api/months?year=` | 某年各月份统计 |
| GET | `/api/entries` | 日记列表（`year` / `month` / `entry_type` / `q` / `page` / `per_page`） |
| GET | `/api/entries/{id}` | 单篇全文 |
| GET | `/api/search?q=` | FTS5 全文搜索 |
| GET | `/api/on-this-day?month=&day=` | 过去的今天（按年份分组） |
| GET | `/api/random` | 随机一天的日记（该日期的全部条目） |

### 示例

过去的今天（9月14日）：
```bash
curl "http://127.0.0.1:8000/api/on-this-day?month=9&day=14"
```

```json
{
  "month": 9,
  "day": 14,
  "total": 11,
  "groups": [
    { "year": 2006, "items": [ { "id": ..., "date": "2006-09-14", "entry_type": "multi_day", ... } ] },
    ...
  ]
}
```

## 数据安全约定

- **只读访问**：所有数据库连接使用 SQLite `mode=ro` URI，绝不写入/修改数据
- **线程安全**：每次请求独立打开连接，用完即关
- **本地运行**：默认绑定 `127.0.0.1`，不对外网开放

## 维护说明（面向后续 AI/开发者）

- 改**页面样式/结构**：编辑 `templates/` 下的 Jinja2 文件与 `static/style.css`
- 改**数据查询**：一律封装在项目根目录 `database.py` 的 `Database` 类里，
  页面与 API 只调用其方法，不直接写 SQL
- 改**接口校验/文档**：编辑 `schemas.py` 中的 Pydantic 模型
- 新增接口：在 `app.py` 添加装饰器路由，并在上方表格与本文档同步更新

新增一种日记类型的中文名时，只需在 `app.py` 的 `ENTRY_TYPE_LABELS` 中补一项，
模板会自动通过 `entry_type_label` 过滤器显示。

---

相关文档：[项目主 README](../README.md) ｜ [日记批量总结](../scripts/batch_summary/README.md)
