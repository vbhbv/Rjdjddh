import os
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks
from index_handler import show_index, search_by_index, navigate_index_pages

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
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except Exception:
            pass

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

        app_context.bot_data["db_conn"] = conn
    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()

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
# تسجيل المستخدم
# ===============================================
async def register_user(update, context):
    conn = context.bot_data.get("db_conn")
    if conn and update.effective_user:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            update.effective_user.id
        )

# ===============================================
# أزرار البداية
# ===============================================
async def handle_start_callbacks(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
                [InlineKeyboardButton("📚 الفهرس العربي", callback_data="show_index")],
                [InlineKeyboardButton("📚 الفهرس الإنجليزي", callback_data="show_index_en")]
            ])
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=(
                    "📚 **تعليمات استخدام مكتبة الكتب الرقمية**\n\n"
                    "🔍 طريقة البحث الصحيحة:\n"
                    "• اكتب اسم الكتاب مباشرة\n"
                    "• أو اسم المؤلف\n"
                    "• أو كلمة مفتاحية واضحة\n\n"
                    "✅ أمثلة صحيحة:\n"
                    "فن اللامبالاة\n"
                    "جريمة الولادة\n"
                    "نيتشه\n\n"
                    "❌ أمثلة غير صحيحة:\n"
                    "أريد كتاب عن...\n"
                    "ممكن كتاب اسمه...\n"
                    "إرسال صورة 📷\n\n"
                    "ℹ️ ملاحظة: البوت يتعامل مع **النصوص فقط** ولا يدعم البحث بالصور.\n\n"
                    "✍️ **تنويه لدور النشر والمؤلفين:**\n"
                    "إدارة المكتبة تحترم حقوق الملكية الفكرية، "
                    "ونحن على استعداد كامل للتعاون مع دور النشر أو المؤلفين "
                    "بخصوص أي محتوى، يرجى التواصل معنا مباشرة."
                ),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.message.edit_text(
                "بعد الانضمام إلى القناة، اضغط على «تحقق من الاشتراك» للمتابعة."
            )

# ===============================================
# رسالة /start
# ===============================================
async def start(update, context):
    await register_user(update, context)
    channel_username = CHANNEL_USERNAME.lstrip('@')

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{channel_username}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "📚 **مرحبًا بك في مكتبة الكتب الرقمية**\n\n"
            "للوصول إلى البحث والفهارس، يرجى الاشتراك في القناة أولًا.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
        [InlineKeyboardButton("📚 الفهرس العربي", callback_data="show_index")],
        [InlineKeyboardButton("📚 الفهرس الإنجليزي", callback_data="show_index_en")]
    ])

    await update.message.reply_text(
        "📚 **تعليمات الاستخدام**\n\n"
        "اكتب اسم الكتاب أو المؤلف أو كلمة مفتاحية واضحة لبدء البحث.\n\n"
        "✍️ دور النشر والمؤلفون مرحب بتواصلهم معنا "
        "لأي استفسار أو طلب بخصوص المحتوى.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    port = int(os.getenv("PORT", 8080))

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(CommandHandler("start", start))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
