from __future__ import annotations

from datetime import datetime, time, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ReminderKind(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[ReminderKind] = mapped_column(SAEnum(ReminderKind, name="reminder_kind"), nullable=False)
    time_of_day: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    once_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    weekdays: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pre_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    occurrences: Mapped[list["OccurrenceState"]] = relationship(back_populates="reminder", cascade="all, delete-orphan")


class OccurrenceState(Base):
    __tablename__ = "occurrence_states"
    __table_args__ = (UniqueConstraint("reminder_id", "occurrence_at", name="uq_occurrence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reminder_id: Mapped[int] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pre_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nag_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snooze_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reminder: Mapped[Reminder] = relationship(back_populates="occurrences")


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
