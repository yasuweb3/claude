from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from bot.db import Database
from bot.models import AppState, OccurrenceState, Reminder, ReminderKind
from bot.utils import weekdays_from_storage, weekdays_to_storage


class ReminderRepository:
    def __init__(self, db: Database, tz: ZoneInfo) -> None:
        self.db = db
        self.tz = tz

    def create_daily(self, title: str, at: time, pre_minutes: int) -> Reminder:
        with self.db.session() as session:
            reminder = Reminder(
                title=title,
                kind=ReminderKind.DAILY,
                time_of_day=at,
                pre_minutes=max(0, pre_minutes),
                active=True,
            )
            session.add(reminder)
            session.flush()
            return reminder

    def create_weekly(self, title: str, weekdays: list[int], at: time, pre_minutes: int) -> Reminder:
        with self.db.session() as session:
            reminder = Reminder(
                title=title,
                kind=ReminderKind.WEEKLY,
                weekdays=weekdays_to_storage(weekdays),
                time_of_day=at,
                pre_minutes=max(0, pre_minutes),
                active=True,
            )
            session.add(reminder)
            session.flush()
            return reminder

    def create_once(self, title: str, once_at: datetime, pre_minutes: int) -> Reminder:
        with self.db.session() as session:
            reminder = Reminder(
                title=title,
                kind=ReminderKind.ONCE,
                once_at=once_at,
                pre_minutes=max(0, pre_minutes),
                active=True,
            )
            session.add(reminder)
            session.flush()
            return reminder

    def list_reminders(self) -> list[Reminder]:
        with self.db.session() as session:
            stmt = select(Reminder).order_by(Reminder.id.asc())
            return list(session.scalars(stmt).all())

    def list_active_reminders(self) -> list[Reminder]:
        with self.db.session() as session:
            stmt = select(Reminder).where(Reminder.active.is_(True)).order_by(Reminder.id.asc())
            return list(session.scalars(stmt).all())

    def get_reminder(self, reminder_id: int) -> Reminder | None:
        with self.db.session() as session:
            stmt = select(Reminder).where(Reminder.id == reminder_id)
            return session.scalars(stmt).first()

    def delete_reminder(self, reminder_id: int) -> bool:
        with self.db.session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                return False
            session.delete(reminder)
            return True

    def set_active(self, reminder_id: int, active: bool) -> bool:
        with self.db.session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                return False
            reminder.active = active
            return True

    def update_time(
        self,
        reminder_id: int,
        *,
        time_of_day: time | None = None,
        once_at: datetime | None = None,
    ) -> Reminder | None:
        with self.db.session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                return None
            if reminder.kind == ReminderKind.ONCE:
                reminder.once_at = once_at
            else:
                reminder.time_of_day = time_of_day
            return reminder

    def update_rule(
        self,
        reminder_id: int,
        *,
        kind: ReminderKind,
        weekdays: list[int] | None = None,
        once_at: datetime | None = None,
    ) -> Reminder | None:
        with self.db.session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                return None

            reminder.kind = kind
            if kind == ReminderKind.ONCE:
                reminder.once_at = once_at
                reminder.weekdays = None
                reminder.time_of_day = None
            elif kind == ReminderKind.DAILY:
                reminder.once_at = None
                reminder.weekdays = None
                if reminder.time_of_day is None:
                    reminder.time_of_day = time(hour=9, minute=0)
            elif kind == ReminderKind.WEEKLY:
                reminder.once_at = None
                reminder.weekdays = weekdays_to_storage(weekdays or [0, 1, 2, 3, 4])
                if reminder.time_of_day is None:
                    reminder.time_of_day = time(hour=9, minute=0)
            return reminder

    def update_pre_minutes(self, reminder_id: int, pre_minutes: int) -> Reminder | None:
        with self.db.session() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                return None
            reminder.pre_minutes = max(0, pre_minutes)
            return reminder

    def _ensure_state(self, session, reminder_id: int, occurrence_at: datetime) -> OccurrenceState:
        stmt = select(OccurrenceState).where(
            OccurrenceState.reminder_id == reminder_id,
            OccurrenceState.occurrence_at == occurrence_at,
        )
        state = session.scalars(stmt).first()
        if state is None:
            state = OccurrenceState(reminder_id=reminder_id, occurrence_at=occurrence_at)
            session.add(state)
            session.flush()
        return state

    def get_occurrence_state(self, reminder_id: int, occurrence_at: datetime) -> OccurrenceState | None:
        with self.db.session() as session:
            stmt = select(OccurrenceState).where(
                OccurrenceState.reminder_id == reminder_id,
                OccurrenceState.occurrence_at == occurrence_at,
            )
            return session.scalars(stmt).first()

    def mark_pre_sent(self, reminder_id: int, occurrence_at: datetime, sent_at: datetime, message_id: int) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.pre_sent_at = sent_at
            state.last_message_id = message_id

    def mark_due_sent(self, reminder_id: int, occurrence_at: datetime, sent_at: datetime, message_id: int) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.due_sent_at = sent_at
            state.last_message_id = message_id

    def mark_nag_sent(self, reminder_id: int, occurrence_at: datetime, sent_at: datetime, message_id: int) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.nag_sent_at = sent_at
            state.last_message_id = message_id

    def mark_snooze_sent(self, reminder_id: int, occurrence_at: datetime, sent_at: datetime, message_id: int) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.snooze_sent_at = sent_at
            state.last_message_id = message_id

    def complete_occurrence(self, reminder_id: int, occurrence_at: datetime, completed_at: datetime) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.completed_at = completed_at

    def snooze_occurrence(
        self,
        reminder_id: int,
        occurrence_at: datetime,
        *,
        snooze_until: datetime,
    ) -> None:
        with self.db.session() as session:
            state = self._ensure_state(session, reminder_id, occurrence_at)
            state.snooze_until = snooze_until
            state.snooze_sent_at = None

    def due_snooze_states(self, now_local: datetime) -> list[OccurrenceState]:
        with self.db.session() as session:
            stmt = select(OccurrenceState).where(
                OccurrenceState.completed_at.is_(None),
                OccurrenceState.snooze_until.is_not(None),
                OccurrenceState.snooze_until <= now_local,
                OccurrenceState.snooze_sent_at.is_(None),
            )
            return list(session.scalars(stmt).all())

    def set_app_state(self, key: str, value: str) -> None:
        with self.db.session() as session:
            current = session.get(AppState, key)
            if current is None:
                current = AppState(key=key, value=value)
                session.add(current)
            else:
                current.value = value

    def get_app_state(self, key: str) -> str | None:
        with self.db.session() as session:
            current = session.get(AppState, key)
            return None if current is None else current.value

    def today_occurrences(self, day: date) -> list[tuple[Reminder, datetime]]:
        """返回当天所有提醒触发时间（本地时区），含暂停提醒。"""
        with self.db.session() as session:
            reminders = list(session.scalars(select(Reminder).order_by(Reminder.id.asc())).all())

        result: list[tuple[Reminder, datetime]] = []
        for reminder in reminders:
            if reminder.kind == ReminderKind.ONCE:
                if reminder.once_at is None:
                    continue
                local = reminder.once_at.astimezone(self.tz)
                if local.date() == day:
                    result.append((reminder, local))
                continue

            if reminder.time_of_day is None:
                continue

            if reminder.kind == ReminderKind.DAILY:
                occurrence = datetime.combine(day, reminder.time_of_day, tzinfo=self.tz)
                result.append((reminder, occurrence))
                continue

            if reminder.kind == ReminderKind.WEEKLY:
                days = weekdays_from_storage(reminder.weekdays)
                if day.weekday() in days:
                    occurrence = datetime.combine(day, reminder.time_of_day, tzinfo=self.tz)
                    result.append((reminder, occurrence))
        result.sort(key=lambda item: item[1])
        return result

    def next_occurrence(self, reminder: Reminder, now_local: datetime) -> datetime | None:
        if reminder.kind == ReminderKind.ONCE:
            if reminder.once_at is None:
                return None
            local = reminder.once_at.astimezone(self.tz)
            return local if local >= now_local else None

        if reminder.time_of_day is None:
            return None

        if reminder.kind == ReminderKind.DAILY:
            candidate = datetime.combine(now_local.date(), reminder.time_of_day, tzinfo=self.tz)
            if candidate >= now_local:
                return candidate
            return candidate + timedelta(days=1)

        if reminder.kind == ReminderKind.WEEKLY:
            weekdays = set(weekdays_from_storage(reminder.weekdays))
            for offset in range(0, 8):
                day = now_local.date() + timedelta(days=offset)
                if day.weekday() not in weekdays:
                    continue
                candidate = datetime.combine(day, reminder.time_of_day, tzinfo=self.tz)
                if candidate >= now_local:
                    return candidate
        return None
