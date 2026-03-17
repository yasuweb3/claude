from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from bot.models import Reminder, ReminderKind
from bot.repository import ReminderRepository
from bot.utils import date_key, minute_floor, weekdays_from_storage

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(
        self,
        *,
        repo: ReminderRepository,
        bot,
        chat_id: int,
        tz: ZoneInfo,
        daily_summary_hour: int,
        daily_summary_minute: int,
        poll_interval_seconds: int,
    ) -> None:
        self.repo = repo
        self.bot = bot
        self.chat_id = chat_id
        self.tz = tz
        self.daily_summary_hour = daily_summary_hour
        self.daily_summary_minute = daily_summary_minute
        self.poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_tick_minute: datetime | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="reminder-scheduler")
        logger.info("Scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        while self._running:
            now_local = minute_floor(datetime.now(self.tz))
            if self._last_tick_minute != now_local:
                try:
                    await self._tick(now_local)
                except Exception:  # noqa: BLE001
                    logger.exception("scheduler tick failed")
                self._last_tick_minute = now_local
            await asyncio.sleep(self.poll_interval_seconds)

    async def _tick(self, now_local: datetime) -> None:
        active = self.repo.list_active_reminders()
        for reminder in active:
            await self._dispatch_pre(reminder, now_local)
            await self._dispatch_due(reminder, now_local)
            await self._dispatch_nag(reminder, now_local)

        await self._dispatch_snooze(now_local)
        await self._dispatch_daily_summary(now_local)

    async def _dispatch_pre(self, reminder: Reminder, now_local: datetime) -> None:
        if reminder.pre_minutes <= 0:
            return
        due_at = now_local + timedelta(minutes=reminder.pre_minutes)
        if not self._occurs_at(reminder, due_at):
            return
        state = self.repo.get_occurrence_state(reminder.id, due_at)
        if state is not None and (state.pre_sent_at is not None or state.completed_at is not None):
            return

        text = self._build_reminder_text(reminder, due_at, "pre")
        message = await self._safe_send_message(
            text=text,
            reply_markup=self._build_action_keyboard(reminder.id, due_at),
        )
        if message:
            self.repo.mark_pre_sent(reminder.id, due_at, now_local, message.message_id)

    async def _dispatch_due(self, reminder: Reminder, now_local: datetime) -> None:
        if not self._occurs_at(reminder, now_local):
            return
        state = self.repo.get_occurrence_state(reminder.id, now_local)
        if state is not None and (state.due_sent_at is not None or state.completed_at is not None):
            return

        text = self._build_reminder_text(reminder, now_local, "due")
        message = await self._safe_send_message(
            text=text,
            reply_markup=self._build_action_keyboard(reminder.id, now_local),
        )
        if message:
            self.repo.mark_due_sent(reminder.id, now_local, now_local, message.message_id)

    async def _dispatch_nag(self, reminder: Reminder, now_local: datetime) -> None:
        due_at = now_local - timedelta(minutes=30)
        if not self._occurs_at(reminder, due_at):
            return
        state = self.repo.get_occurrence_state(reminder.id, due_at)
        if state is None:
            return
        if state.completed_at is not None or state.nag_sent_at is not None:
            return
        if state.due_sent_at is None:
            return

        text = self._build_reminder_text(reminder, due_at, "nag")
        message = await self._safe_send_message(
            text=text,
            reply_markup=self._build_action_keyboard(reminder.id, due_at),
        )
        if message:
            self.repo.mark_nag_sent(reminder.id, due_at, now_local, message.message_id)

    async def _dispatch_snooze(self, now_local: datetime) -> None:
        states = self.repo.due_snooze_states(now_local)
        for state in states:
            reminder = self.repo.get_reminder(state.reminder_id)
            if reminder is None:
                continue
            if state.completed_at is not None:
                continue
            text = self._build_reminder_text(reminder, state.occurrence_at.astimezone(self.tz), "snooze")
            message = await self._safe_send_message(
                text=text,
                reply_markup=self._build_action_keyboard(reminder.id, state.occurrence_at.astimezone(self.tz)),
            )
            if message:
                self.repo.mark_snooze_sent(reminder.id, state.occurrence_at, now_local, message.message_id)

    async def _dispatch_daily_summary(self, now_local: datetime) -> None:
        if (now_local.hour, now_local.minute) != (self.daily_summary_hour, self.daily_summary_minute):
            return

        last_sent = self.repo.get_app_state("daily_summary_last_sent")
        today_key = date_key(now_local.date())
        if last_sent == today_key:
            return

        occurrences = self.repo.today_occurrences(now_local.date())
        if not occurrences:
            text = "🗓 今日提醒总览\n\n今天没有提醒任务。"
        else:
            lines = ["🗓 今日提醒总览（按时间）", ""]
            for reminder, occurrence_at in occurrences:
                state = self.repo.get_occurrence_state(reminder.id, occurrence_at)
                if not reminder.active:
                    status = "已暂停"
                elif state is not None and state.completed_at is not None:
                    status = "已完成"
                elif occurrence_at < now_local:
                    status = "已过未完成"
                else:
                    status = "待提醒"
                lines.append(
                    f"- {occurrence_at.strftime('%H:%M')} | #{reminder.id} {reminder.title} | {status}"
                )
            text = "\n".join(lines)

        message = await self._safe_send_message(text=text)
        if message:
            self.repo.set_app_state("daily_summary_last_sent", today_key)

    def _occurs_at(self, reminder: Reminder, at_local: datetime) -> bool:
        at_local = minute_floor(at_local.astimezone(self.tz))

        if reminder.kind == ReminderKind.ONCE:
            if reminder.once_at is None:
                return False
            once_local = minute_floor(reminder.once_at.astimezone(self.tz))
            return once_local == at_local

        if reminder.time_of_day is None:
            return False
        if (reminder.time_of_day.hour, reminder.time_of_day.minute) != (at_local.hour, at_local.minute):
            return False

        if reminder.kind == ReminderKind.DAILY:
            return True
        if reminder.kind == ReminderKind.WEEKLY:
            days = weekdays_from_storage(reminder.weekdays)
            return at_local.weekday() in days
        return False

    def _build_action_keyboard(self, reminder_id: int, occurrence_at: datetime) -> InlineKeyboardMarkup:
        ts = int(occurrence_at.astimezone(timezone.utc).timestamp())
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ 完成", callback_data=f"c|{reminder_id}|{ts}")],
                [
                    InlineKeyboardButton("⏰ 稍后10分钟", callback_data=f"s|{reminder_id}|{ts}|10"),
                    InlineKeyboardButton("⏰ 稍后30分钟", callback_data=f"s|{reminder_id}|{ts}|30"),
                    InlineKeyboardButton("⏰ 稍后1小时", callback_data=f"s|{reminder_id}|{ts}|60"),
                ],
            ]
        )

    def _build_reminder_text(self, reminder: Reminder, occurrence_at: datetime, stage: str) -> str:
        when = occurrence_at.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        prefix = {
            "pre": "🔔 提前提醒",
            "due": "⏰ 到点提醒",
            "nag": "⚠️ 未完成催办（30分钟后）",
            "snooze": "🔁 稍后提醒",
        }.get(stage, "🔔 提醒")
        return (
            f"{prefix}\n\n"
            f"任务：{reminder.title}\n"
            f"时间：{when}\n"
            f"提醒ID：#{reminder.id}\n\n"
            "可点击下方按钮：完成 / 稍后。"
        )

    async def _safe_send_message(self, *, text: str, reply_markup=None):
        attempts = 3
        for idx in range(attempts):
            try:
                return await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    reply_markup=reply_markup,
                )
            except TelegramError as exc:
                logger.warning("send message failed (attempt %s/%s): %s", idx + 1, attempts, exc)
                if idx + 1 == attempts:
                    return None
                await asyncio.sleep(2**idx)
        return None
