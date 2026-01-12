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

        pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=3,
            max_size=15,
            command_timeout=60
        )

        async with pool.acquire() as conn:
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

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """)

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fts_books
            ON books USING gin (to_tsvector('arabic', file_name));
            """)

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trgm_books
            ON books USING gin (file_name gin_trgm_ops);
            """)

        app_context.bot_data["db_conn"] = pool
        logger.info("✅ Database pool ready.")

    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()

# ===============================================
# استقبال ملفات PDF من القنوات
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        pool = context.bot_data.get("db_conn")
        if not pool:
            return
        async with pool.acquire() as conn:
            await conn.execute("""
            INSERT INTO books(file_id, file_name)
            VALUES($1, $2)
            ON CONFLICT (file_id) DO UPDATE
            SET file_name = EXCLUDED.file_name;
            """, document.file_id, document.file_name)

# ===============================================
# الاشتراك الإجباري
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===============================================
# عداد المستخدمين
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if pool and update.effective_user:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                update.effective_user.id
            )

# ===============================================
# start (✔️ المفقودة – تم إصلاح الخطأ)
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "🌿 أهلاً بك\n\nيرجى الاشتراك في القناة أولاً",
            reply_markup=keyboard
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 أكثر الكتب تحميلاً", callback_data="top_downloads_week")]
    ])

    await update.message.reply_text(
        "📚 مرحباً بك في مكتبة الكتب\n\nأرسل اسم الكتاب للبحث",
        reply_markup=keyboard
    )

# ===============================================
# callbacks
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        file_id = data.replace("file:", "")
        pool = context.bot_data.get("db_conn")
        if pool:
            async with pool.acquire() as conn:
                book = await conn.fetchrow("SELECT id FROM books WHERE file_id=$1", file_id)
                if book:
                    await conn.execute(
                        "INSERT INTO downloads (book_id, user_id) VALUES ($1, $2)",
                        book["id"], query.from_user.id
                    )
        await handle_callbacks(update, context)

    elif data in ["next_page", "prev_page", "search_similar", "top_downloads_week"]:
        await handle_callbacks(update, context)

# ===============================================
# البحث
# ===============================================
async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text("🚫 يرجى الاشتراك أولاً.")
        return
    await search_books(update, context)

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
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
