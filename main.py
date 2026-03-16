from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.ai_parser import DeepSeekReminderParser
from bot.config import load_config
from bot.db import Database
from bot.handlers import BotHandlers
from bot.repository import ReminderRepository
from bot.scheduler import ReminderScheduler


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def build_application() -> Application:
    config = load_config()
    db = Database(config.database_url)
    db.init_schema()
    repo = ReminderRepository(db, config.timezone)
    ai_parser = None
    if config.deepseek_api_key:
        ai_parser = DeepSeekReminderParser(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            model=config.deepseek_model,
            tz=config.timezone,
        )

    handlers = BotHandlers(
        repo=repo,
        tz=config.timezone,
        owner_chat_id=config.chat_id,
        ai_parser=ai_parser,
    )

    async def post_init(application: Application) -> None:
        scheduler = ReminderScheduler(
            repo=repo,
            bot=application.bot,
            chat_id=config.chat_id,
            tz=config.timezone,
            daily_summary_hour=config.daily_summary_hour,
            daily_summary_minute=config.daily_summary_minute,
            poll_interval_seconds=config.poll_interval_seconds,
        )
        application.bot_data["scheduler"] = scheduler
        scheduler.start()
        await application.bot.set_my_commands(
            [
                BotCommand("help", "查看帮助"),
                BotCommand("list", "查看提醒列表"),
                BotCommand("add_daily", "新增每天提醒"),
                BotCommand("add_weekly", "新增每周提醒"),
                BotCommand("add_once", "新增单次提醒"),
            ]
        )

    async def post_shutdown(application: Application) -> None:
        scheduler: ReminderScheduler | None = application.bot_data.get("scheduler")
        if scheduler:
            await scheduler.stop()

    app = (
        ApplicationBuilder()
        .token(config.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help))
    app.add_handler(CommandHandler("add_daily", handlers.add_daily))
    app.add_handler(CommandHandler("add_weekly", handlers.add_weekly))
    app.add_handler(CommandHandler("add_once", handlers.add_once))
    app.add_handler(CommandHandler("list", handlers.list_reminders))
    app.add_handler(CommandHandler("delete", handlers.delete_reminder))
    app.add_handler(CommandHandler("pause", handlers.pause))
    app.add_handler(CommandHandler("resume", handlers.resume))
    app.add_handler(CommandHandler("edit_time", handlers.edit_time))
    app.add_handler(CommandHandler("edit_rule", handlers.edit_rule))
    app.add_handler(CommandHandler("edit_pre", handlers.edit_pre))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.natural_text))
    app.add_handler(CallbackQueryHandler(handlers.callback))

    return app


def main() -> None:
    configure_logging()
    app = build_application()
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
