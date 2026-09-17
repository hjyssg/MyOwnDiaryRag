#!/usr/bin/env python3
"""FastAPI JSON API 与 React 生产包入口。"""

import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from webapp.routers.calendar import router as calendar_router  # noqa: E402
from webapp.routers.entries import router as entries_router  # noqa: E402
from webapp.routers.summaries import router as summaries_router  # noqa: E402

FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

app = FastAPI(
    title="日记浏览系统",
    description="纯本地日记浏览与摘要 API。数据库只读访问。",
    version="2.0.0",
)


@app.exception_handler(sqlite3.DatabaseError)
async def database_error_handler(_request: Request, _exc: sqlite3.DatabaseError):
    return JSONResponse(status_code=500, content={"detail": "数据库读取失败"})


app.include_router(entries_router)
app.include_router(calendar_router)
app.include_router(summaries_router)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """把页面请求交给 React Router；API、docs 和 OpenAPI 路由不会被吞掉。"""

    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="前端尚未构建，请先运行 cd frontend && npm run build")
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)