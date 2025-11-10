import os
import asyncpg
import hashlib
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers  # لوحة التحكم

# ===============================================
# إعداد اللوج
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# إعداد قاعدة البيانات مع تحسين المزامنة وطباعة الأخطاء التفصيلية
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)

        # محاولة إنشاء امتداد unaccent
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            logger.info("✅ Extension unaccent ensured.")
        except Exception as e:
            logger.warning(f"⚠️ Could not create unaccent extension: {e}")

        # محاولة إنشاء إعداد البحث العربي
        try:
            await conn.execute("""
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'arabic_simple') THEN
       CREATE TEXT SEARCH CONFIGURATION arabic_simple (PARSER = default);
   END IF;
END
$$;
""")
            await conn.execute("""
ALTER TEXT SEARCH CONFIGURATION arabic_simple
ALTER MAPPING FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
WITH unaccent, simple;
""")
            logger.info("✅ Arabic search configuration ensured.")
        except Exception as e:
            logger.warning(f"⚠️ Could not configure arabic_simple search: {e}")

        # الجداول الأساسية
        await conn.execute("""
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    file_id TEXT UNIQUE,
    file_name TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW(),
    tsv_content tsvector
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
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        # تخزين الاتصال في bot_data
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
# تطبيع النص العربي للبحث
# ===============================================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    return text

# ===============================================
# البحث المباشر مع الصفحات (محسن)
# ===============================================
BOOKS_PER_PAGE = 10

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return  # البحث فقط في الخاص

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    normalized_query = normalize_text(query)

    try:
        books = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE LOWER(REPLACE(
        REPLACE(REPLACE(REPLACE(REPLACE(file_name,'أ','ا'),'إ','ا'),'آ','ا'),'ى','ي'),'_',' ')
    ) LIKE '%' || $1 || '%'
ORDER BY uploaded_at DESC;
""", normalized_query)
    except Exception as e:
        logger.error(f"❌ Database query error: {e}")
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    if not books:
        await update.message.reply_text(f"❌ لم أجد أي كتب تطابق: {query}")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

async def send_books_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([
            InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

# ===============================================
# أزرار الملفات
# ===============================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @Boooksfree1bot"
            await query.message.reply_document(document=file_id, caption=caption)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
    elif data == "recheck_sub":
        await start(update, context)  # إعادة التحقق من الاشتراك عند الضغط على الزر

# ===============================================
# الاشتراك الإجباري والقناة
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===============================================
# أوامر أساسية (start)
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # تحقق من الاشتراك الإجباري
    is_subscribed = await check_subscription(update.effective_user.id, context.bot)
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 انضم إلى القناة", url=f"https://t.me/{CHANNEL_USERNAME}")],
            [InlineKeyboardButton("🔄 تحقّق بعد الانضمام", callback_data="recheck_sub")]
        ])
        await update.message.reply_text(
            f"🤍 أهلاً بك عزيزي القارئ!\n\n"
            f"لقد عملنا بجدّ وشغف على جمع وفهرسة أكثر من *99,000 كتاب* 📖 "
            f"لتكون متاحة لك مجانًا بسهولة وسرعة.\n\n"
            f"كل ما نطلبه منك هو *الانضمام إلى قناتنا الرسمية* "
            f"كلمسة تقدير بسيطة لدعم هذا المشروع الثقافي الرائع. 🌿\n\n"
            f"📢 القناة: [@{CHANNEL_USERNAME.lstrip('@')}](https://t.me/{CHANNEL_USERNAME})\n\n"
            f"بعد الانضمام، اضغط على زر *تحقّق بعد الانضمام* أدناه 👇",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # رسالة الترحيب بعد التحقق
    await update.message.reply_text(
        "🎉 أهلاً بك! هذا أول بوت مكتبة سريع من نوعه 📚\n"
        "يمكنك البحث عن أي كتاب مباشرة والحصول عليه في ثوانٍ.\n"
        "تجربة سلسة، واجهة بسيطة، وسرعة عالية.",
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

    # أوامر
    # ✅ لم نسجل /start هنا مباشرة، سيتم تسجيله عبر لوحة الإدارة
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(callback_handler))

    register_admin_handlers(app, start)  # لوحة الإدارة تسجل /start مع التحقق وتتبع المستخدمين

    if base_url:
        webhook_url = f"https://{base_url}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}"
        )
    else:
        logger.info("⚠️ WEB_HOST not available. Running in polling mode.")
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
