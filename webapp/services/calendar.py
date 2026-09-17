"""日历回顾相关业务规则。"""

import calendar

from database import Database
from webapp.schemas import (
    OnThisDayGroup,
    OnThisDayItem,
    OnThisDayResponse,
    RandomDayResponse,
)


class InvalidCalendarDate(ValueError):
    """月、日组合不是有效日期。"""


def get_on_this_day(db: Database, month: int, day: int) -> OnThisDayResponse:
    """查询并按年份分组返回某月某日的日记。"""

    max_day = calendar.monthrange(2000, month)[1]
    if day > max_day:
        raise InvalidCalendarDate(f"{month}月没有{day}日")

    result = db.on_this_day(month, day)
    grouped: dict[int, list[dict]] = {}
    for item in result:
        grouped.setdefault(item["year"], []).append(item)

    groups = [
        OnThisDayGroup(
            year=year,
            items=[OnThisDayItem.model_validate(item) for item in items],
        )
        for year, items in sorted(grouped.items())
    ]
    return OnThisDayResponse(
        month=month,
        day=day,
        total=len(result),
        groups=groups,
    )


def get_random_day(db: Database) -> RandomDayResponse | None:
    """随机取一个有日记的日期及该日全部条目。"""

    selected_day = db.random_date()
    if selected_day is None:
        return None

    entries = db.entries_for_date(selected_day["date"])
    return RandomDayResponse(
        date=selected_day["date"],
        year=selected_day["year"],
        month=selected_day["month"],
        day=selected_day["day"],
        total=len(entries),
        items=[OnThisDayItem.model_validate(entry) for entry in entries],
    )