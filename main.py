import os
import asyncpg
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, send_books_page, handle_callbacks

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

        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            logger.info("✅ Extension unaccent ensured.")
        except Exception as e:
            logger.warning(f"⚠️ Could not create unaccent extension: {e}")

        await conn.execute("""
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    file_id TEXT UNIQUE,
    file_name TEXT,
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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database connection and setup complete.")
    except Exception as e:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ===============================================
# استقبال ملفات PDF من القنوات
# ===============================================
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        if not conn:
            logger.error("❌ Database not connected.")
            return

        try:
            await conn.execute("""
INSERT INTO books(file_id, file_name)
VALUES($1, $2)
ON CONFLICT (file_id) DO UPDATE
SET file_name = EXCLUDED.file_name;
""", document.file_id, document.file_name)
            logger.info(f"📚 Indexed book: {document.file_name}")
        except Exception as e:
            logger.error(f"❌ Error indexing book: {e}")

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
# start
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_username = CHANNEL_USERNAME.lstrip('@')

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{channel_username}")]
        ])
        await update.message.reply_text(
            f"🚫 *يرجى الانضمام إلى القناة @{channel_username} لاستخدام البوت.*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "🎉 أهلاً بك! أرسل اسم أي كتاب وسأبحث لك عنه فوراً.",
        parse_mode="Markdown"
    )

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        logger.error("🚨 BOT_TOKEN not found.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    # البحث
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    # استقبال PDF من القنوات
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    # أزرار الصفحات + التحميل + الاقتراحات
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    # لوحة المشرف + start
    register_admin_handlers(app, start)

    if base_url:
        webhook_url = f"https://{base_url}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}"
        )
    else:
        logger.info("⚠️ Running in polling mode.")
        app.run_polling()

if __name__ == "__main__":
    run_bot()
