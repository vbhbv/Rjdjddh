import os
import asyncpg
import logging
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
    db_url = os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(db_url)

    await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

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
    CREATE INDEX IF NOT EXISTS idx_books_trgm
    ON books USING gin (file_name gin_trgm_ops);
    """)

    app_context.bot_data["db_conn"] = conn
    logger.info("✅ Database ready")

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()

# ===============================================
# استقبال ملفات PDF
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.channel_post.document
    conn = context.bot_data["db_conn"]
    await conn.execute("""
    INSERT INTO books(file_id, file_name)
    VALUES($1, $2)
    ON CONFLICT (file_id) DO UPDATE
    SET file_name = EXCLUDED.file_name
    """, doc.file_id, doc.file_name)

# ===============================================
# الاشتراك الإجباري
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id, bot):
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# ===============================================
# تسجيل المستخدم
# ===============================================
async def register_user(update, context):
    conn = context.bot_data["db_conn"]
    await conn.execute(
        "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
        update.effective_user.id
    )

# ===============================================
# الفهارس
# ===============================================
CATEGORIES = {
    "novels": ("📖 الروايات", ["رواية", "novel"]),
    "chem": ("⚗️ الكيمياء", ["كيمياء", "chem"]),
    "physics": ("⚛️ الفيزياء", ["فيزياء", "physics"]),
    "math": ("📐 الرياضيات", ["رياضيات", "math"]),
    "religion": ("📿 الدين", ["فقه", "حديث", "تفسير", "دين"]),
    "arabic": ("📘 اللغة العربية", ["نحو", "بلاغة", "صرف", "عربي"]),
    "english": ("📕 اللغة الإنجليزية", ["english", "grammar"])
}

# ===============================================
# Callback
# ===============================================
async def handle_start_callbacks(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = context.bot_data["db_conn"]

    if data.startswith("cat:"):
        key = data.split(":")[1]
        keywords = CATEGORIES[key][1]

        sql = """
        SELECT file_id, file_name FROM books
        WHERE """ + " OR ".join(["file_name ILIKE '%' || $%d || '%'" % (i+1) for i in range(len(keywords))]) + """
        LIMIT 20
        """

        rows = await conn.fetch(sql, *keywords)
        await send_books_page(query, rows, 0)

    elif data.startswith("file:"):
        await handle_callbacks(update, context)

# ===============================================
# /start
# ===============================================
async def start(update, context):
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text("يرجى الاشتراك بالقناة أولاً")
        return

    keyboard = [
        [InlineKeyboardButton(v[0], callback_data=f"cat:{k}")]
        for k, v in CATEGORIES.items()
    ]

    await update.message.reply_text(
        "📚 اختر فهرساً:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===============================================
# البحث
# ===============================================
async def search_books_with_subscription(update, context):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text("🚫 يجب الاشتراك أولاً")
        return
    await search_books(update, context)

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    app = (
        Application.builder()
        .token(os.getenv("BOT_TOKEN"))
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence("bot_data.pickle"))
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
