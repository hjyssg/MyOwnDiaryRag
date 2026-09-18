# 日记 Web 系统（后端）

FastAPI 后端（本目录 `webapp-backend/`）只提供只读 JSON API，并在生产模式托管前端产物
`webapp-frontend/dist`；前端源码（React + TypeScript + Vite）在 `webapp-frontend/`。
SQLite 始终由 Web 使用 `mode=ro` 连接。

## 生产运行

```bash
pip install -r webapp-backend/requirements.txt
cd webapp-frontend
npm ci
npm run build
cd ..
python webapp-backend/app.py
```

访问 <http://127.0.0.1:8000>；API 文档位于 `/docs`。如果尚未构建前端，页面请求会返回
503 和明确提示，API 仍可正常使用。

## 前端开发

```bash
# 终端 1
python webapp-backend/app.py

# 终端 2
cd webapp-frontend
npm run dev
```

Vite 将 `/api` 转发到 `127.0.0.1:8000`。筛选状态均保存在 URL query 中。

### 没有个人日记时：使用演示数据

仓库提供了完全虚构、可重复生成的演示数据库，方便首次体验界面、开发和截图；它不会读取或覆盖
`.env` 配置的个人数据库：

```bash
python scripts/create_demo_data.py
DATABASE_PATH="$(pwd)/data/demo_diary.db" python webapp-backend/app.py
```

默认生成 `data/demo_diary.db`。重复执行脚本会重建该演示文件；如需其他位置可传
`--output /path/to/demo_diary.db`。

浏览页默认每页 50 篇（`per_page` 可选 35 / 50 / 100），点进某个年份即可一屏看到 35 篇以上；
年 / 月筛选是原生输入框 + 原生候选（`datalist`，候选来自 `/api/years` 与 `/api/months?year=`），
非法值（如月份 13）在前端就被丢弃，不会传给后端。"过去的今天"用原生 `type="date"` 日期框
（参考年为闰年 2024）并配 `今天 / 前一天 / 后一天` 快捷按钮，URL 仍是 `?month=&day=`。

## API

- `GET /api/years`
- `GET /api/months?year=`
- `GET /api/entries?year=&month=&entry_type=&q=&page=&per_page=`
- `GET /api/entries/full?year=&month=&entry_type=&q=`：按筛选条件返回所有匹配日记的完整正文，不分页；
  适用于浏览页“显示完整正文”模式，大范围查询可能产生较大响应。
- `GET /api/entries/{id}`
- `GET /api/on-this-day?month=&day=`：按年份分组返回该月日的日记（只带 120 字预览）。
- `GET /api/random`：随机一天；`items[].content` 为该篇**完整正文**（"随机一天"页直接展示全文）。
- `GET /api/summaries?year=&month=&entry_type=&emotion=&q=&status=&page=&per_page=`
- `GET /api/summaries/emotions`：情绪标签全集 + 各自条数（供筛选下拉；标签集来自根 `.env`）
- `GET /api/entries/{id}/summary`
- `GET /api/search?q=`：兼容接口，已弃用

摘要表尚未由 batch 创建时，摘要列表返回空分页，单篇摘要返回 `status=missing`，不会影响原文阅读。
正文变化后旧摘要返回 `status=stale` 且不返回旧摘要正文。

情绪字段：`emotion`（标签，空字符串表示没有）与 `emotion_status`
（`ok` / `empty` / `failed` / `stale` / `missing`）。标签集来自根 `.env` 的 `EMOTION_LABELS`，
非法 `emotion` 参数返回 422；未迁移的老库里这两个字段降级为 `""` / `missing`。

## 验证

```bash
pip install -r webapp-backend/requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"

cd webapp-frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

后端 SQL 集中在根目录 `database.py` 和 `summary_database.py`；router 只处理参数与 HTTP 状态，
service 组合业务规则。前端页面不直接访问 SQLite，也不散落裸 `fetch`。

目录内的模块按「本目录为根」扁平导入（如 `from routers.entries import ...`）：目录名
`webapp-backend` 带连字符、不能作为 Python 包名导入；根目录的 `config.py` /
`database.py` / `summary_database.py` 通过 `app.py` 里插入的项目根目录导入。