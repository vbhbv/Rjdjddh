import os
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks  # البحث العادي
from index_handler import show_index, search_by_index, navigate_index_pages  # الفهرس مع الملاحة

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

        # الجداول
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
# التعامل مع أزرار callback
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # تحقق الاشتراك
    if data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            # الرسالة الجديدة بعد الاشتراك
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
                [InlineKeyboardButton("📚 عرض الفهرس", callback_data="show_index")]
            ])
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=(
                    "👋 أهلاً بك في بوت مكتبة الكتب 📚\n\n"
                    "أنا بوت ذكي احتوي على نصف مليون كتاب أستطيع مساعدتك في العثور على أي كتاب تبحث عنه، أو اقتراح كتب مشابهة للموضوع الذي تهتم به.\n\n"
                    "💡 طريقة الاستخدام:\n"
                    "- اكتب اسم الكتاب مباشرة، أو اكتب كلمات مفتاحية مثل: برمجة، فلسفة، اقتصاد...\n"
                    "- سأعرض لك أقرب النتائج بسرعة.\n\n"
                    "🔹 البوت تم تطويره بجهود فردية من قبل الاستاذ مجول شعلان الحيالي ودون أي دعم خارجي، ويتم تحمل تكاليف تشغيل المشروع بشكل فردي، ونرحب بكل من يريد التعاون معنا لضمان استمرار عمل المكتبة بشكل مجاني!"
                ),
                reply_markup=keyboard
            )
        else:
            await query.message.edit_text(
                "❌ لم يتم الاشتراك بعد. يرجى الاشتراك أولاً.\n"
                "اضغط على زر '✅ اشترك الآن' للانضمام إلى القناة."
            )

    # عرض الفهرس أو العودة له
    elif data == "show_index" or data == "home_index":
        await show_index(update, context)

    # اختيار فهرس فرعي
    elif data.startswith("index:"):
        await search_by_index(update, context)

    # تنقل صفحات الفهرس
    elif data.startswith("index_page:"):
        await navigate_index_pages(update, context)

    # أزرار البحث العادي
    elif data.startswith("file:") or data in ["next_page", "prev_page", "search_similar"]:
        await handle_callbacks(update, context)

# ===============================================
# رسالة البدء /start
# ===============================================
async def start(update: "telegram.Update", context: ContextTypes.DEFAULT_TYPE):
    channel_username = CHANNEL_USERNAME.lstrip('@')

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{channel_username}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "🚫 المعذرة! للوصول إلى جميع ميزات البوت، يجب الاشتراك في القناة التالية:\n"
            f"👉 @{channel_username}\n\n"
            "الاشتراك يتيح لك:\n"
            "- البحث عن أي كتاب بسهولة.\n"
            "- استكشاف كتب مشابهة ومواضيع متنوعة.\n"
            "- الوصول إلى مكتبة ضخمة تحتوي على مئات الآلاف من الكتب.\n\n"
            "اشترك الآن لتتمكن من الاستفادة الكاملة من مكتبة الكتب!",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        return

    # إذا كان مشتركاً بالفعل عند الضغط على /start
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
        [InlineKeyboardButton("📚 عرض الفهرس", callback_data="show_index")]
    ])
    await update.message.reply_text(
        "👋 أهلاً بك في بوت مكتبة الكتب 📚\n\n"
        "أنا بوت ذكي احتوي على نصف مليون كتاب أستطيع مساعدتك في العثور على أي كتاب تبحث عنه، أو اقتراح كتب مشابهة للموضوع الذي تهتم به.\n\n"
        "💡 طريقة الاستخدام:\n"
        "- اكتب اسم الكتاب مباشرة، أو اكتب كلمات مفتاحية مثل: برمجة، فلسفة، اقتصاد...\n"
        "- سأعرض لك أقرب النتائج بسرعة.\n\n"
        "🔹 البوت تم تطويره بجهود فردية من قبل الاستاذ مجول شعلان الحيالي ودون أي دعم خارجي، ويتم تحمل تكاليف تشغيل المشروع بشكل فردي، ونرحب بكل من يريد التعاون معنا لضمان استمرار عمل المكتبة بشكل مجاني!",
        reply_markup=keyboard
    )

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        logger.error("🚨 BOT_TOKEN not found in environment.")
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
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(CommandHandler("start", start))

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
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
