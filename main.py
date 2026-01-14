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
# التصنيفات الثابتة
# ===============================================
CATEGORIES = {
    "novels": ["رواية", "روايات", "novel", "fiction"],
    "chemistry": ["كيمياء", "chemistry", "chem"],
    "physics": ["فيزياء", "physics"],
    "math": ["رياضيات", "math", "mathematics"],
    "religion": ["دين", "اسلام", "فقه", "حديث", "religion"],
    "arabic": ["لغة عربية", "العربية", "arabic"],
    "english": ["لغة انجليزية", "english"]
}

def detect_category(file_name: str) -> str:
    name = file_name.lower()
    for category, keywords in CATEGORIES.items():
        for k in keywords:
            if k.lower() in name:
                return category
    return "uncategorized"

# ===============================================
# إعداد قاعدة البيانات
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    db_url = os.getenv("DATABASE_URL")
    pool = await asyncpg.create_pool(dsn=db_url)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            category TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_books_category
        ON books(category);
        """)

        await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_books_name_trgm
        ON books USING gin (file_name gin_trgm_ops);
        """)

    app_context.bot_data["db_conn"] = pool
    logger.info("✅ Database ready with categories")

async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()

# ===============================================
# استقبال ملفات PDF
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.channel_post.document
    if doc.mime_type != "application/pdf":
        return

    category = detect_category(doc.file_name)
    pool = context.bot_data.get("db_conn")

    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO books(file_id, file_name, category)
        VALUES($1, $2, $3)
        ON CONFLICT (file_id) DO UPDATE
        SET file_name = EXCLUDED.file_name,
            category = EXCLUDED.category;
        """, doc.file_id, doc.file_name, category)

# ===============================================
# الاشتراك الإجباري
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
async def register_user(update, context):
    pool = context.bot_data.get("db_conn")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            update.effective_user.id
        )

# ===============================================
# /start
# ===============================================
async def start(update, context):
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text("يرجى الاشتراك في القناة أولاً")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 الروايات", callback_data="cat:novels")],
        [InlineKeyboardButton("⚗️ الكيمياء", callback_data="cat:chemistry")],
        [InlineKeyboardButton("🔬 الفيزياء", callback_data="cat:physics")],
        [InlineKeyboardButton("➗ الرياضيات", callback_data="cat:math")],
        [InlineKeyboardButton("🕌 الدين", callback_data="cat:religion")],
        [InlineKeyboardButton("📘 العربية", callback_data="cat:arabic"),
         InlineKeyboardButton("📗 الإنجليزية", callback_data="cat:english")]
    ])

    await update.message.reply_text(
        "📚 اختر الفهرس أو أرسل اسم الكتاب للبحث:",
        reply_markup=keyboard
    )

# ===============================================
# callbacks
# ===============================================
async def handle_start_callbacks(update, context):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("cat:"):
        category = query.data.split(":")[1]
        await send_books_page(update, context, category=category)
        return

    await handle_callbacks(update, context)

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
    token = os.getenv("BOT_TOKEN")

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence("bot_data.pickle"))
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
