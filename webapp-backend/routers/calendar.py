"""年份统计和日历回顾 JSON API。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from database import Database
from dependencies import get_database
from schemas import (
    MonthStat,
    OnThisDayResponse,
    RandomDayResponse,
    YearStat,
)
from services.calendar import (
    InvalidCalendarDate,
    get_on_this_day,
    get_random_day,
)

router = APIRouter(prefix="/api", tags=["calendar"])


@router.get("/years", response_model=list[YearStat])
def api_years(db: Database = Depends(get_database)) -> list[dict]:
    """年份统计列表。"""

    return db.years()


@router.get("/months", response_model=list[MonthStat])
def api_months(
    year: int = Query(ge=2000, le=2100),
    db: Database = Depends(get_database),
) -> list[dict]:
    """某一年各月份统计。"""

    return db.months(year)


@router.get("/on-this-day", response_model=OnThisDayResponse)
def api_on_this_day(
    month: int = Query(ge=1, le=12),
    day: int = Query(ge=1, le=31),
    db: Database = Depends(get_database),
) -> OnThisDayResponse:
    """过去的今天：查询每一年同月日的日记。"""

    try:
        return get_on_this_day(db, month, day)
    except InvalidCalendarDate as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/random", response_model=RandomDayResponse)
def api_random(
    response: Response,
    db: Database = Depends(get_database),
) -> RandomDayResponse:
    """随机一天的日记（该日期的全部条目）。"""

    response.headers["Cache-Control"] = "no-store"
    result = get_random_day(db)
    if result is None:
        raise HTTPException(status_code=404, detail="暂无日记记录")
    return result