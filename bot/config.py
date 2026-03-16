from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    chat_id: int
    database_url: str
    timezone: ZoneInfo
    daily_summary_hour: int
    daily_summary_minute: int
    poll_interval_seconds: int


def _parse_summary_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("DAILY_SUMMARY_TIME 必须是 HH:MM 格式")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("DAILY_SUMMARY_TIME 超出有效时间范围")
    return hour, minute


def load_config() -> AppConfig:
    load_dotenv()

    bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    chat_id_raw = os.getenv("TG_CHAT_ID", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    timezone_name = os.getenv("TIMEZONE", "Asia/Shanghai").strip()
    summary_time = os.getenv("DAILY_SUMMARY_TIME", "10:00").strip()
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))

    if not bot_token:
        raise ValueError("缺少 TG_BOT_TOKEN")
    if not chat_id_raw:
        raise ValueError("缺少 TG_CHAT_ID")
    if not database_url:
        raise ValueError("缺少 DATABASE_URL")

    hour, minute = _parse_summary_time(summary_time)

    return AppConfig(
        bot_token=bot_token,
        chat_id=int(chat_id_raw),
        database_url=database_url,
        timezone=ZoneInfo(timezone_name),
        daily_summary_hour=hour,
        daily_summary_minute=minute,
        poll_interval_seconds=max(5, poll_interval),
    )
