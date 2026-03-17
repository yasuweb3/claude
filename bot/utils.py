from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "周一": 0,
    "星期一": 0,
    "1": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "周二": 1,
    "星期二": 1,
    "2": 1,
    "wed": 2,
    "wednesday": 2,
    "周三": 2,
    "星期三": 2,
    "3": 2,
    "thu": 3,
    "thursday": 3,
    "周四": 3,
    "星期四": 3,
    "4": 3,
    "fri": 4,
    "friday": 4,
    "周五": 4,
    "星期五": 4,
    "5": 4,
    "sat": 5,
    "saturday": 5,
    "周六": 5,
    "星期六": 5,
    "6": 5,
    "sun": 6,
    "sunday": 6,
    "周日": 6,
    "周天": 6,
    "星期日": 6,
    "星期天": 6,
    "0": 6,
    "7": 6,
}

WEEKDAY_LABELS = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}


def parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("时间格式应为 HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间范围无效")
    return time(hour=hour, minute=minute)


def parse_local_datetime(date_str: str, time_str: str, tz: ZoneInfo) -> datetime:
    raw = f"{date_str} {time_str}"
    dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=tz)


def format_hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def parse_weekdays(raw: str) -> list[int]:
    normalized = raw.strip().lower()
    if normalized in {"workday", "weekday", "工作日"}:
        return [0, 1, 2, 3, 4]

    tokens = [part.strip() for part in raw.replace("，", ",").split(",") if part.strip()]
    if not tokens:
        raise ValueError("请提供至少一个星期几")

    days: set[int] = set()
    for token in tokens:
        key = token.lower()
        if key not in WEEKDAY_ALIASES:
            raise ValueError(f"无法识别的星期格式: {token}")
        days.add(WEEKDAY_ALIASES[key])
    return sorted(days)


def weekdays_to_storage(days: list[int]) -> str:
    return ",".join(str(day) for day in sorted(set(days)))


def weekdays_from_storage(raw: str | None) -> list[int]:
    if not raw:
        return []
    return sorted({int(part) for part in raw.split(",") if part})


def weekdays_label(days: list[int]) -> str:
    if days == [0, 1, 2, 3, 4]:
        return "工作日"
    return ",".join(WEEKDAY_LABELS[day] for day in days)


def minute_floor(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def same_minute(a: datetime, b: datetime) -> bool:
    return minute_floor(a) == minute_floor(b)


def date_key(d: date) -> str:
    return d.strftime("%Y-%m-%d")
