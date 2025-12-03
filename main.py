import os
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, send_books_page, handle_callbacks

# ===============================================
# LOGGING
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# DATABASE INIT
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)

        # إنشاء الامتداد
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            logger.info("✅ Extension unaccent ensured.")
        except Exception as e:
            logger.warning(f"⚠️ Could not create unaccent extension: {e}")

        # جدول الكتب
        await conn.execute("""
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    file_id TEXT UNIQUE,
    file_name TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW()
);
""")

        # جدول المستخدمين
        await conn.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    joined_at TIMESTAMP DEFAULT NOW()
);
""")

        # جدول الإعدادات
        await conn.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

        # جدول الفهرسة الجديد
        await conn.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    keywords TEXT[]
);
""")

        # تعبئة الفهارس الافتراضية إذا كانت فارغة
        existing = await conn.fetchval("SELECT COUNT(*) FROM categories;")
        if existing == 0:
            await conn.execute("""
INSERT INTO categories (name, keywords) VALUES
('📚 الروايات', ARRAY['رواية','روايات','novel']),
('📘 قواعد اللغة العربية', ARRAY['قواعد','نحو','صرف','اعراب']),
('📕 كتب إنكليزية', ARRAY['english','انكليزي','لغة']),
('⚖️ كتب قانون', ARRAY=['قانون','قانونية','تشريع']),
('📝 الشعر', ARRAY=['شعر','شاعر','قصيدة']),
('📙 نقد أدبي', ARRAY=['نقد','نقد ادبي','تحليل']),
('🧪 كيمياء', ARRAY=['كيمياء','chemical','chemistry']),
('🧲 فيزياء', ARRAY=['فيزياء','physics']),
('📗 سياسة', ARRAY=['سياسة','سياسي'])
;
""")
            logger.info("📂 Default categories inserted.")

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
# INDEX PDFs FROM CHANNEL
# ===============================================
async def handle_pdf(update: "telegram.Update", context: ContextTypes.DEFAULT_TYPE):
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
# SUBSCRIPTION
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===============================================
# START BUTTONS + CATEGORIES
# ===============================================
async def build_categories_keyboard(conn):
    rows = []
    cats = await conn.fetch("SELECT id, name FROM categories ORDER BY id;")

    for c in cats:
        rows.append([InlineKeyboardButton(c["name"], callback_data=f"cat_{c['id']}")])

    rows.append([InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")])

    return InlineKeyboardMarkup(rows)


async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):

            conn = context.bot_data["db_conn"]
            keyboard = await build_categories_keyboard(conn)

            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=(
                    "👋 أهلاً بك في بوت مكتبة الكتب 📚\n\n"
                    "اكتب اسم أي كتاب أو موضوع وسأبحث لك بدقة.\n\n"
                    "👇 هذه الفهارس الجاهزة:"
                ),
                reply_markup=keyboard
            )
        else:
            await query.message.edit_text(
                "❌ لم يتم الاشتراك بعد. يرجى الاشتراك أولاً.\n\n"
                "اضغط على زر '✅ اشترك الآن' للانضمام إلى القناة."
            )

# ===============================================
# start /start
# ===============================================
async def start(update: "telegram.Update", context: ContextTypes.DEFAULT_TYPE):
    channel_username = CHANNEL_USERNAME.lstrip('@')

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{channel_username}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])

        await update.message.reply_text(
            "🚫 للاستخدام الكامل للبوت يجب الاشتراك بالقناة:\n"
            f"👉 @{channel_username}\n\n"
            "بعد الاشتراك اضغط (تحقق من الاشتراك).",
            reply_markup=keyboard,
        )
        return

    # إذا كان مشترك
    conn = context.bot_data["db_conn"]
    keyboard = await build_categories_keyboard(conn)

    await update.message.reply_text(
        "👋 أهلاً بك في بوت مكتبة الكتب 📚\n\n"
        "💡 طريقة الاستخدام:\n"
        "- اكتب اسم الكتاب مباشرة.\n"
        "- أو اكتب كلمات مفتاحية مثل: فلسفة، نحو، قانون...\n\n"
        "👇 يمكنك أيضًا تصفح الفهارس التالية:",
        reply_markup=keyboard
    )

# ===============================================
# RUN BOT
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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks, pattern="check_subscription"))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
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
        logger.info("⚠️ WEB_HOST missing → polling mode.")
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
