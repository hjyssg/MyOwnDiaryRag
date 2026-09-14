#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日记 Web 浏览系统 - FastAPI 后端

功能：
  1. 浏览日记（按年份/月份/类型筛选、分页、关键词搜索）
  2. 🌟 过去的今天（On This Day）：查询每一年同月日的日记
  3. REST API 全部通过 Pydantic 校验，自动生成 /docs 文档

启动方式（在 webapp 目录下）：
    python app.py
    或
    uvicorn app:app --reload

页面地址：http://127.0.0.1:8000
API 文档：http://127.0.0.1:8000/docs
"""

import calendar
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import get_database_path
from database import Database
from schemas import (
    EntryDetail,
    EntryListResponse,
    MonthStat,
    OnThisDayGroup,
    OnThisDayItem,
    OnThisDayResponse,
    YearStat,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="日记浏览系统",
    description="纯本地日记浏览：支持按年/月浏览、全文搜索与「过去的今天」回顾。数据库只读访问。",
    version="1.0.0",
)

# 静态资源与模板
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 数据库实例（只读）
_db = Database(get_database_path())

# 条目类型的中文显示名
ENTRY_TYPE_LABELS = {
    "single_day": "单日",
    "multi_day": "多日",
    "stock_diary": "股票",
    "retrospective": "回忆",
    "summary": "总结",
    "note": "笔记",
}


def entry_type_label(t: str) -> str:
    return ENTRY_TYPE_LABELS.get(t, t or "日记")


templates.env.filters["entry_type_label"] = entry_type_label
templates.env.filters["month_name"] = lambda m: f"{m}月"


# ---------------------------------------------------------------
# 页面路由（服务端渲染）
# ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """首页：年份总览"""
    years = _db.years()
    total_entries = sum(y["entries"] for y in years)
    total_words = sum(y["words"] for y in years)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "years": years,
            "total_entries": total_entries,
            "total_words": total_words,
        },
    )


@app.get("/browse", response_class=HTMLResponse)
def browse_page(
    request: Request,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    entry_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
):
    """浏览页：按年/月/类型筛选 + 分页 + 关键词搜索"""
    per_page = 20
    data = _db.entries(year=year, month=month, entry_type=entry_type, query=q, page=page, per_page=per_page)
    total = _db.count_entries(year=year, month=month, entry_type=entry_type, query=q)
    pages = max(1, (total + per_page - 1) // per_page)

    # 列表筛选需要的年份数据（用于下拉框）
    years = [y["year"] for y in _db.years()]
    months = [m["month"] for m in _db.months(year)] if year else []

    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "entries": data,
            "total": total,
            "page": page,
            "pages": pages,
            "year": year,
            "month": month,
            "entry_type": entry_type,
            "q": q,
            "years": years,
            "months": months,
            "entry_types": sorted(ENTRY_TYPE_LABELS.keys()),
        },
    )


@app.get("/entries/{entry_id}", response_class=HTMLResponse)
def read_page(request: Request, entry_id: int):
    """单篇阅读页：全文 + 同月其他篇目侧栏"""
    entry = _db.entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="日记不存在")
    nearby = _db.nearby_entries(entry["year"], entry["month"], entry_id)
    return templates.TemplateResponse(
        request,
        "read.html",
        {"entry": entry, "nearby": nearby},
    )


@app.get("/on-this-day", response_class=HTMLResponse)
def on_this_day_page(
    request: Request,
    month: int | None = Query(default=None, ge=1, le=12),
    day: int | None = Query(default=None, ge=1, le=31),
):
    """过去的今天页面"""
    today = date.today()
    m = month if month is not None else today.month
    d = day if day is not None else today.day

    # 校验日期有效性（处理 2月30日 等不存在日期）
    max_day = calendar.monthrange(2000, m)[1]
    if d > max_day:
        raise HTTPException(status_code=400, detail=f"{m}月没有{d}日")

    result = _db.on_this_day(m, d)
    # 按年份分组
    grouped = {}
    for item in result:
        grouped.setdefault(item["year"], []).append(item)
    groups = [{"year": y, "items": grouped[y]} for y in sorted(grouped)]
    total = len(result)

    return templates.TemplateResponse(
        request,
        "on_this_day.html",
        {
            "month": m,
            "day": d,
            "groups": groups,
            "total": total,
            "has_records": bool(result),
        },
    )


# ---------------------------------------------------------------
# REST API（数据接口，供前端 fetch 或第三方调用）
# ---------------------------------------------------------------

@app.get("/api/years", response_model=list[YearStat])
def api_years():
    """年份统计列表"""
    return _db.years()


@app.get("/api/months", response_model=list[MonthStat])
def api_months(year: int = Query(ge=2000, le=2100)):
    """某一年各月份统计"""
    return _db.months(year)


@app.get("/api/entries", response_model=EntryListResponse)
def api_entries(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    entry_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """日记列表（分页）"""
    items = _db.entries(year=year, month=month, entry_type=entry_type, query=q, page=page, per_page=per_page)
    total = _db.count_entries(year=year, month=month, entry_type=entry_type, query=q)
    pages = max(1, (total + per_page - 1) // per_page)
    return EntryListResponse(
        total=total, page=page, per_page=per_page, pages=pages, items=items,
        year=year, month=month, entry_type=entry_type, query=q,
    )


@app.get("/api/entries/{entry_id}", response_model=EntryDetail)
def api_entry(entry_id: int):
    """单篇日记全文"""
    entry = _db.entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="日记不存在")
    return entry


@app.get("/api/on-this-day", response_model=OnThisDayResponse)
def api_on_this_day(
    month: int = Query(ge=1, le=12),
    day: int = Query(ge=1, le=31),
):
    """过去的今天：查询每一年同月日的日记（按年份分组）"""
    max_day = calendar.monthrange(2000, month)[1]
    if day > max_day:
        raise HTTPException(status_code=400, detail=f"{month}月没有{day}日")

    result = _db.on_this_day(month, day)
    grouped = {}
    for item in result:
        grouped.setdefault(item["year"], []).append(item)

    groups = [
        OnThisDayGroup(year=y, items=[OnThisDayItem(**i) for i in items])
        for y, items in sorted(grouped.items())
    ]
    return OnThisDayResponse(month=month, day=day, total=len(result), groups=groups)


@app.get("/api/search", response_model=EntryListResponse)
def api_search(
    q: str = Query(min_length=1, description="搜索关键词（FTS5）"),
    limit: int = Query(default=30, ge=1, le=100),
):
    """全文搜索"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="搜索关键词不能为空")
    try:
        items = _db.search(q, limit=limit)
    except Exception as exc:  # FTS 语法异常时给出友好提示
        raise HTTPException(status_code=400, detail=f"搜索失败：{exc}")
    total = len(items)
    return EntryListResponse(
        total=total, page=1, per_page=limit, pages=1, items=items, query=q,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)

