from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from bot.utils import parse_hhmm, parse_local_datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedReminderIntent:
    title: str
    kind: str  # once | daily | weekly
    pre_minutes: int
    time_of_day: time | None = None
    once_at: datetime | None = None
    weekdays: list[int] | None = None


class DeepSeekReminderParser:
    def __init__(self, *, api_key: str, base_url: str, model: str, tz: ZoneInfo) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.tz = tz

    async def parse(self, *, text: str, now_local: datetime) -> tuple[list[ParsedReminderIntent] | None, str]:
        prompt = self._build_prompt(text=text, now_local=now_local)
        try:
            raw = await self._chat(prompt)
            payload = self._load_json(raw)
            return self._validate_payload(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("deepseek parse failed: %s", exc)
            return None, "AI 解析失败，请换一种说法，或使用 /add_daily /add_weekly /add_once。"

    async def _chat(self, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是提醒解析器。把用户自然语言解析成严格 JSON，不要输出任何 JSON 之外的文字。"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    def _load_json(self, raw: str) -> dict[str, Any]:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _build_prompt(self, *, text: str, now_local: datetime) -> str:
        return (
            "请把这句话解析成提醒创建参数。\n"
            "当前时间（Asia/Shanghai）: "
            f"{now_local.strftime('%Y-%m-%d %H:%M')}\n"
            "输入: "
            f"{text}\n\n"
            "输出 JSON schema：\n"
            "{\n"
            '  "ok": true 或 false,\n'
            '  "reason": "失败原因，仅 ok=false 时必填",\n'
            '  "reminders": [\n'
            "    {\n"
            '      "title": "提醒标题",\n'
            '      "kind": "once | daily | weekly",\n'
            '      "time": "HH:MM",\n'
            '      "date": "YYYY-MM-DD (仅 once)",\n'
            '      "weekdays": [0-6, 其中 0=周一, 6=周日, 仅 weekly],\n'
            '      "pre_minutes": 10\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "规则：\n"
            "1) 缺信息时 ok=false 并写 reason。\n"
            "2) 如果一句话里有多个提醒，必须拆成多个 reminders 元素。\n"
            "3) 标题要简洁可读。\n"
            "4) 每天=kind=daily；工作日=kind=weekly 且 weekdays=[0,1,2,3,4]。\n"
            "5) 时间必须 24 小时制 HH:MM。\n"
        )

    def _validate_payload(self, payload: dict[str, Any]) -> tuple[list[ParsedReminderIntent] | None, str]:
        ok = bool(payload.get("ok", True))
        if not ok:
            return None, str(payload.get("reason", "信息不足，无法创建提醒"))

        if isinstance(payload.get("reminders"), list):
            raw_items = payload.get("reminders", [])
        else:
            # 兼容旧格式：顶层直接是一个提醒对象
            raw_items = [payload]

        intents: list[ParsedReminderIntent] = []
        for index, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                return None, f"第 {index} 条提醒格式无效"
            intent, error = self._validate_single_item(raw)
            if intent is None:
                return None, f"第 {index} 条提醒有误：{error}"
            intents.append(intent)

        if not intents:
            return None, "没有识别到任何提醒"
        return intents, ""

    def _validate_single_item(self, payload: dict[str, Any]) -> tuple[ParsedReminderIntent | None, str]:
        title = str(payload.get("title", "")).strip()
        if not title:
            return None, "没有识别到提醒标题"

        kind = str(payload.get("kind", "")).strip().lower()
        if kind not in {"once", "daily", "weekly"}:
            return None, "没有识别到提醒类型（once/daily/weekly）"

        pre_minutes = int(payload.get("pre_minutes", 10))
        pre_minutes = max(0, min(pre_minutes, 24 * 60))

        if kind == "once":
            date_str = str(payload.get("date", "")).strip()
            time_str = str(payload.get("time", "")).strip()
            if not date_str or not time_str:
                return None, "单次提醒缺少日期或时间"
            once_at = parse_local_datetime(date_str, time_str, self.tz)
            return ParsedReminderIntent(
                title=title,
                kind=kind,
                pre_minutes=pre_minutes,
                once_at=once_at,
            ), ""

        time_str = str(payload.get("time", "")).strip()
        if not time_str:
            return None, "缺少提醒时间（HH:MM）"
        at = parse_hhmm(time_str)

        if kind == "daily":
            return ParsedReminderIntent(
                title=title,
                kind=kind,
                pre_minutes=pre_minutes,
                time_of_day=at,
            ), ""

        raw_days = payload.get("weekdays")
        if not isinstance(raw_days, list):
            return None, "每周提醒缺少 weekdays"
        days: set[int] = set()
        for value in raw_days:
            day = int(value)
            if not (0 <= day <= 6):
                return None, "weekdays 取值必须在 0-6"
            days.add(day)
        if not days:
            return None, "weekdays 不能为空"

        return ParsedReminderIntent(
            title=title,
            kind=kind,
            pre_minutes=pre_minutes,
            time_of_day=at,
            weekdays=sorted(days),
        ), ""
