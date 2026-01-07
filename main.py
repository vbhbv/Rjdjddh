import os
import asyncpg
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks, send_books_page
from index_handler import show_index, show_index_en, search_by_index, navigate_index_pages

# ===============================================
# إعداد اللوج
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# إعداد قاعدة البيانات
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            name_normalized TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            book_id INT REFERENCES books(id),
            user_id BIGINT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        );
        """)

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database ready.")
    except Exception:
        logger.error("❌ Database error", exc_info=True)

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()

# ===============================================
# استقبال PDF
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document:
        doc = update.channel_post.document
        if doc.mime_type != "application/pdf":
            return
        conn = context.bot_data.get("db_conn")
        if not conn:
            return
        await conn.execute(
            """
            INSERT INTO books(file_id, file_name)
            VALUES($1,$2)
            ON CONFLICT (file_id) DO UPDATE SET file_name = EXCLUDED.file_name
            """,
            doc.file_id,
            doc.file_name
        )

# ===============================================
# الاشتراك
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# ===============================================
# تسجيل المستخدم
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if conn:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            update.effective_user.id
        )

# ===============================================
# callbacks العامة
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ("show_index", "home_index"):
        await show_index(update, context)

    elif data == "show_index_en":
        await show_index_en(update, context)

    elif data.startswith("file:") or data in ("next_page", "prev_page", "search_similar"):
        await handle_callbacks(update, context)

# ===============================================
# start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text("يرجى الاشتراك أولاً.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 الفهرس العربي", callback_data="show_index")],
        [InlineKeyboardButton("📚 الفهرس الإنجليزي", callback_data="show_index_en")]
    ])

    await update.message.reply_text("اختر:", reply_markup=keyboard)

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence("bot_data.pickle"))
        .build()
    )

    # ✅ Handlers مخصصة للفهارس (الحل)
    app.add_handler(CallbackQueryHandler(search_by_index, pattern="^index:"))
    app.add_handler(CallbackQueryHandler(navigate_index_pages, pattern="^index_page:"))

    # بقية الأزرار
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CommandHandler("start", start))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
