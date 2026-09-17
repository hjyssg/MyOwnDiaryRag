# 日记 Web 系统

前端使用 React + TypeScript + Vite，FastAPI 只提供只读 JSON API，并在生产模式托管
`frontend/dist`。SQLite 始终由 Web 使用 `mode=ro` 连接。

## 生产运行

```bash
pip install -r webapp/requirements.txt
cd frontend
npm ci
npm run build
cd ..
python webapp/app.py
```

访问 <http://127.0.0.1:8000>；API 文档位于 `/docs`。如果尚未构建前端，页面请求会返回
503 和明确提示，API 仍可正常使用。

## 前端开发

```bash
# 终端 1
python webapp/app.py

# 终端 2
cd frontend
npm run dev
```

Vite 将 `/api` 转发到 `127.0.0.1:8000`。筛选状态均保存在 URL query 中。

## API

- `GET /api/years`
- `GET /api/months?year=`
- `GET /api/entries?year=&month=&entry_type=&q=&page=&per_page=`
- `GET /api/entries/{id}`
- `GET /api/on-this-day?month=&day=`
- `GET /api/random`
- `GET /api/summaries?year=&month=&entry_type=&q=&status=&page=&per_page=`
- `GET /api/entries/{id}/summary`
- `GET /api/search?q=`：兼容接口，已弃用

摘要表尚未由 batch 创建时，摘要列表返回空分页，单篇摘要返回 `status=missing`，不会影响原文阅读。
正文变化后旧摘要返回 `status=stale` 且不返回旧摘要正文。

## 验证

```bash
pip install -r webapp/requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"

cd frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

后端 SQL 集中在根目录 `database.py` 和 `summary_database.py`；router 只处理参数与 HTTP 状态，
service 组合业务规则。前端页面不直接访问 SQLite，也不散落裸 `fetch`。