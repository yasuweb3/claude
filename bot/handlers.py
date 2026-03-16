from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.ai_parser import DeepSeekReminderParser, ParsedReminderIntent
from bot.models import Reminder, ReminderKind
from bot.repository import ReminderRepository
from bot.utils import (
    format_hhmm,
    minute_floor,
    parse_hhmm,
    parse_local_datetime,
    parse_weekdays,
    weekdays_from_storage,
    weekdays_label,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingIntent:
    intent: ParsedReminderIntent
    created_at: datetime


def _extract_pre_option(args: list[str], default_pre: int = 10) -> tuple[int, list[str]]:
    tokens = list(args)
    pre = default_pre
    for index, token in enumerate(list(tokens)):
        if token == "--pre":
            if index + 1 >= len(tokens):
                raise ValueError("`--pre` 后需要分钟数")
            pre = int(tokens[index + 1])
            del tokens[index : index + 2]
            return max(0, pre), tokens
        if token.startswith("--pre="):
            pre = int(token.split("=", 1)[1])
            del tokens[index]
            return max(0, pre), tokens
    return pre, tokens


def describe_rule(reminder: Reminder, tz: ZoneInfo) -> str:
    if reminder.kind == ReminderKind.ONCE:
        if reminder.once_at is None:
            return "单次（时间缺失）"
        return f"单次 {reminder.once_at.astimezone(tz).strftime('%Y-%m-%d %H:%M')}"

    if reminder.time_of_day is None:
        return "重复（时间缺失）"

    if reminder.kind == ReminderKind.DAILY:
        return f"每天 {format_hhmm(reminder.time_of_day)}"

    days = weekdays_from_storage(reminder.weekdays)
    return f"{weekdays_label(days)} {format_hhmm(reminder.time_of_day)}"


class BotHandlers:
    def __init__(
        self,
        repo: ReminderRepository,
        tz: ZoneInfo,
        owner_chat_id: int,
        ai_parser: DeepSeekReminderParser | None = None,
    ) -> None:
        self.repo = repo
        self.tz = tz
        self.owner_chat_id = owner_chat_id
        self.ai_parser = ai_parser
        self.pending_intents: dict[str, PendingIntent] = {}

    async def _ensure_owner(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None:
            return False
        if chat.id != self.owner_chat_id:
            if update.message:
                await update.message.reply_text("当前机器人只绑定了一个固定账号，暂不支持多人使用。")
            elif update.callback_query:
                await update.callback_query.answer("无权限", show_alert=True)
            return False
        return True

    def _cleanup_pending_intents(self) -> None:
        now = datetime.now(self.tz)
        expired = [
            token
            for token, pending in self.pending_intents.items()
            if (now - pending.created_at) > timedelta(hours=2)
        ]
        for token in expired:
            self.pending_intents.pop(token, None)

    def _intent_rule_text(self, intent: ParsedReminderIntent) -> str:
        if intent.kind == "once" and intent.once_at is not None:
            return f"单次 {intent.once_at.strftime('%Y-%m-%d %H:%M')}"
        if intent.kind == "daily" and intent.time_of_day is not None:
            return f"每天 {format_hhmm(intent.time_of_day)}"
        if intent.kind == "weekly" and intent.time_of_day is not None and intent.weekdays:
            return f"{weekdays_label(intent.weekdays)} {format_hhmm(intent.time_of_day)}"
        return "规则缺失"

    def _create_from_intent(self, intent: ParsedReminderIntent) -> Reminder:
        if intent.kind == "once" and intent.once_at is not None:
            return self.repo.create_once(
                title=intent.title,
                once_at=intent.once_at,
                pre_minutes=intent.pre_minutes,
            )
        if intent.kind == "daily" and intent.time_of_day is not None:
            return self.repo.create_daily(
                title=intent.title,
                at=intent.time_of_day,
                pre_minutes=intent.pre_minutes,
            )
        if intent.kind == "weekly" and intent.time_of_day is not None and intent.weekdays:
            return self.repo.create_weekly(
                title=intent.title,
                weekdays=intent.weekdays,
                at=intent.time_of_day,
                pre_minutes=intent.pre_minutes,
            )
        raise ValueError("AI 解析结果不完整，无法创建提醒")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        await self.help(update, context)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        text = (
            "📌 提醒机器人命令\n\n"
            "新增提醒：\n"
            "/add_daily HH:MM 标题 [--pre 10]\n"
            "/add_weekly 工作日 HH:MM 标题 [--pre 10]\n"
            "/add_weekly Mon,Wed,Fri HH:MM 标题 [--pre 10]\n"
            "/add_once YYYY-MM-DD HH:MM 标题 [--pre 10]\n\n"
            "管理提醒：\n"
            "/list\n"
            "/delete ID\n"
            "/pause ID\n"
            "/resume ID\n"
            "/edit_time ID HH:MM\n"
            "/edit_time ID YYYY-MM-DD HH:MM   (单次提醒)\n"
            "/edit_rule ID daily|workday|Mon,Wed,Fri\n"
            "/edit_rule ID once YYYY-MM-DD HH:MM\n"
            "/edit_pre ID 分钟\n\n"
            "自然语言：\n"
            "- 直接发一句话即可（例如：每个工作日下午六点提醒我打扫卫生）\n"
            "- AI 解析后会先给你确认按钮，确认后再创建\n\n"
            "说明：\n"
            "- 每天 10:00 自动发送今日总览\n"
            "- 到点提醒后，30 分钟未完成会催一次\n"
            "- 可在按钮里点“完成”或“稍后”"
        )
        await update.effective_message.reply_text(text)

    async def natural_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        message = update.effective_message
        if message is None or not message.text:
            return
        if self.ai_parser is None:
            await message.reply_text("当前未配置 DeepSeek API，暂时无法自然语言建提醒。")
            return

        self._cleanup_pending_intents()
        intent, reason = await self.ai_parser.parse(text=message.text.strip(), now_local=datetime.now(self.tz))
        if intent is None:
            await message.reply_text(
                f"🤔 我没有完全理解这句话：{reason}\n"
                "可以换个说法，或直接用 /add_daily /add_weekly /add_once。"
            )
            return

        token = secrets.token_urlsafe(6)
        self.pending_intents[token] = PendingIntent(intent=intent, created_at=datetime.now(self.tz))

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ 确认创建", callback_data=f"ai|ok|{token}"),
                    InlineKeyboardButton("❌ 取消", callback_data=f"ai|cancel|{token}"),
                ]
            ]
        )
        preview = (
            "🧠 AI 解析结果（请确认）\n\n"
            f"标题：{intent.title}\n"
            f"规则：{self._intent_rule_text(intent)}\n"
            f"提前：{intent.pre_minutes} 分钟"
        )
        await message.reply_text(preview, reply_markup=keyboard)

    async def add_daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        try:
            pre, args = _extract_pre_option(context.args)
            if len(args) < 2:
                raise ValueError("格式：/add_daily HH:MM 标题 [--pre 10]")
            at = parse_hhmm(args[0])
            title = " ".join(args[1:]).strip()
            if not title:
                raise ValueError("标题不能为空")
            reminder = self.repo.create_daily(title=title, at=at, pre_minutes=pre)
            await update.effective_message.reply_text(
                f"✅ 已创建提醒 #{reminder.id}\n规则：每天 {format_hhmm(at)}\n提前：{pre} 分钟\n标题：{title}"
            )
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"❌ 新增失败：{exc}")

    async def add_weekly(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        try:
            pre, args = _extract_pre_option(context.args)
            if len(args) < 3:
                raise ValueError("格式：/add_weekly 工作日 HH:MM 标题 [--pre 10]")
            days = parse_weekdays(args[0])
            at = parse_hhmm(args[1])
            title = " ".join(args[2:]).strip()
            if not title:
                raise ValueError("标题不能为空")
            reminder = self.repo.create_weekly(title=title, weekdays=days, at=at, pre_minutes=pre)
            await update.effective_message.reply_text(
                f"✅ 已创建提醒 #{reminder.id}\n规则：{weekdays_label(days)} {format_hhmm(at)}\n提前：{pre} 分钟\n标题：{title}"
            )
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"❌ 新增失败：{exc}")

    async def add_once(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        try:
            pre, args = _extract_pre_option(context.args)
            if len(args) < 3:
                raise ValueError("格式：/add_once YYYY-MM-DD HH:MM 标题 [--pre 10]")
            once_at = parse_local_datetime(args[0], args[1], self.tz)
            title = " ".join(args[2:]).strip()
            if not title:
                raise ValueError("标题不能为空")
            reminder = self.repo.create_once(title=title, once_at=once_at, pre_minutes=pre)
            await update.effective_message.reply_text(
                f"✅ 已创建提醒 #{reminder.id}\n规则：单次 {once_at.strftime('%Y-%m-%d %H:%M')}\n提前：{pre} 分钟\n标题：{title}"
            )
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"❌ 新增失败：{exc}")

    async def list_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        reminders = self.repo.list_reminders()
        if not reminders:
            await update.effective_message.reply_text("当前没有提醒，先用 /add_daily 或 /add_weekly 创建。")
            return

        now = datetime.now(self.tz)
        lines = ["📋 当前提醒列表", ""]
        for reminder in reminders:
            status = "启用" if reminder.active else "暂停"
            next_at = self.repo.next_occurrence(reminder, now)
            next_text = next_at.strftime("%Y-%m-%d %H:%M") if next_at else "无"
            lines.append(
                f"#{reminder.id} [{status}] {reminder.title}\n"
                f"  规则：{describe_rule(reminder, self.tz)}\n"
                f"  提前：{reminder.pre_minutes} 分钟\n"
                f"  下次：{next_text}"
            )
        await update.effective_message.reply_text("\n".join(lines))

    async def delete_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        if len(context.args) != 1:
            await update.effective_message.reply_text("格式：/delete ID")
            return
        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("ID 必须是数字")
            return
        ok = self.repo.delete_reminder(reminder_id)
        await update.effective_message.reply_text("✅ 已删除" if ok else "❌ 未找到对应提醒")

    async def pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._toggle_active(update, context, False)

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._toggle_active(update, context, True)

    async def _toggle_active(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        active: bool,
    ) -> None:
        if not await self._ensure_owner(update):
            return
        if len(context.args) != 1:
            cmd = "/resume" if active else "/pause"
            await update.effective_message.reply_text(f"格式：{cmd} ID")
            return
        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("ID 必须是数字")
            return
        ok = self.repo.set_active(reminder_id, active)
        if not ok:
            await update.effective_message.reply_text("❌ 未找到对应提醒")
            return
        await update.effective_message.reply_text("✅ 已恢复" if active else "✅ 已暂停")

    async def edit_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text(
                "格式：/edit_time ID HH:MM\n或 /edit_time ID YYYY-MM-DD HH:MM（单次提醒）"
            )
            return

        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("ID 必须是数字")
            return

        reminder = self.repo.get_reminder(reminder_id)
        if reminder is None:
            await update.effective_message.reply_text("❌ 未找到对应提醒")
            return

        try:
            if reminder.kind == ReminderKind.ONCE:
                if len(context.args) < 3:
                    raise ValueError("单次提醒需要 YYYY-MM-DD HH:MM")
                once_at = parse_local_datetime(context.args[1], context.args[2], self.tz)
                self.repo.update_time(reminder_id, once_at=once_at)
                await update.effective_message.reply_text(f"✅ 已更新为 {once_at.strftime('%Y-%m-%d %H:%M')}")
            else:
                at = parse_hhmm(context.args[1])
                self.repo.update_time(reminder_id, time_of_day=at)
                await update.effective_message.reply_text(f"✅ 已更新为 {format_hhmm(at)}")
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"❌ 更新时间失败：{exc}")

    async def edit_rule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text(
                "格式：/edit_rule ID daily|workday|Mon,Wed,Fri\n"
                "或 /edit_rule ID once YYYY-MM-DD HH:MM"
            )
            return
        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("ID 必须是数字")
            return

        reminder = self.repo.get_reminder(reminder_id)
        if reminder is None:
            await update.effective_message.reply_text("❌ 未找到对应提醒")
            return

        rule_token = context.args[1].strip().lower()
        try:
            if rule_token in {"once", "单次"}:
                if len(context.args) < 4:
                    raise ValueError("切换到单次需要提供 YYYY-MM-DD HH:MM")
                once_at = parse_local_datetime(context.args[2], context.args[3], self.tz)
                self.repo.update_rule(reminder_id, kind=ReminderKind.ONCE, once_at=once_at)
                await update.effective_message.reply_text(f"✅ 已改为单次 {once_at.strftime('%Y-%m-%d %H:%M')}")
                return

            if rule_token in {"daily", "每天"}:
                updated = self.repo.update_rule(reminder_id, kind=ReminderKind.DAILY)
                if updated and updated.time_of_day is None:
                    self.repo.update_time(reminder_id, time_of_day=time(hour=9, minute=0))
                await update.effective_message.reply_text("✅ 已改为每天重复")
                return

            if rule_token in {"workday", "weekday", "工作日"}:
                days = [0, 1, 2, 3, 4]
            else:
                days = parse_weekdays(context.args[1])
            self.repo.update_rule(reminder_id, kind=ReminderKind.WEEKLY, weekdays=days)
            await update.effective_message.reply_text(f"✅ 已改为 {weekdays_label(days)}")
        except Exception as exc:  # noqa: BLE001
            await update.effective_message.reply_text(f"❌ 修改规则失败：{exc}")

    async def edit_pre(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        if len(context.args) != 2:
            await update.effective_message.reply_text("格式：/edit_pre ID 分钟")
            return
        try:
            reminder_id = int(context.args[0])
            minutes = max(0, int(context.args[1]))
        except ValueError:
            await update.effective_message.reply_text("ID 和分钟都必须是数字")
            return

        updated = self.repo.update_pre_minutes(reminder_id, minutes)
        if updated is None:
            await update.effective_message.reply_text("❌ 未找到对应提醒")
            return
        await update.effective_message.reply_text(f"✅ 已更新提前提醒为 {minutes} 分钟")

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_owner(update):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return

        payload = query.data.split("|")
        try:
            if payload[0] == "ai" and len(payload) == 3:
                action = payload[1]
                token = payload[2]
                pending = self.pending_intents.get(token)
                if pending is None:
                    await query.answer("这个确认已过期", show_alert=True)
                    return
                if action == "cancel":
                    self.pending_intents.pop(token, None)
                    await query.answer("已取消")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:  # noqa: BLE001
                        pass
                    return
                if action == "ok":
                    self.pending_intents.pop(token, None)
                    reminder = self._create_from_intent(pending.intent)
                    await query.answer("已创建")
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except Exception:  # noqa: BLE001
                        pass
                    if query.message:
                        await query.message.reply_text(
                            "✅ 已创建提醒\n"
                            f"ID：#{reminder.id}\n"
                            f"标题：{pending.intent.title}\n"
                            f"规则：{self._intent_rule_text(pending.intent)}\n"
                            f"提前：{pending.intent.pre_minutes} 分钟"
                        )
                    return

            if payload[0] == "c" and len(payload) == 3:
                reminder_id = int(payload[1])
                ts = int(payload[2])
                occurrence_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(self.tz)
                self.repo.complete_occurrence(reminder_id, occurrence_at, datetime.now(self.tz))
                await query.answer("已标记完成")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:  # noqa: BLE001
                    pass
                if query.message:
                    await query.message.reply_text(f"✅ 已完成：提醒 #{reminder_id}")
                return

            if payload[0] == "s" and len(payload) == 4:
                reminder_id = int(payload[1])
                ts = int(payload[2])
                minutes = int(payload[3])
                occurrence_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(self.tz)
                snooze_until = minute_floor(datetime.now(self.tz) + timedelta(minutes=minutes))
                self.repo.snooze_occurrence(
                    reminder_id,
                    occurrence_at,
                    snooze_until=snooze_until,
                )
                await query.answer(f"已稍后 {minutes} 分钟")
                if query.message:
                    await query.message.reply_text(f"⏰ 已稍后 {minutes} 分钟：提醒 #{reminder_id}")
                return
        except Exception as exc:  # noqa: BLE001
            logger.exception("callback failed: %s", exc)
            await query.answer("操作失败，请稍后重试", show_alert=True)
            return

        await query.answer("无法识别的操作", show_alert=True)
