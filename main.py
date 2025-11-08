import os
import asyncpg
import hashlib
import logging
import fitz  # PyMuPDF
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
ALTER TEXT SEARCH CONFIGURATION arabic_simple ALTER MAPPING
FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
WITH unaccent, simple;
""")

        # الجداول
        await conn.execute("""
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    file_id TEXT UNIQUE,
    file_name TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW(),
    tsv_content tsvector,
    summary TEXT,
    category TEXT,
    pages INT
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

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database connection and setup complete.")
    except Exception as e:
        logger.error(f"❌ Database setup error: {e}")

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ===============================================
# دالة توليد الملخص والتصنيف (مثال بسيط)
# ===============================================
def generate_summary_and_category(text: str):
    # مثال بسيط جدًا على التصنيف والتلخيص
    summary = text[:200] + "..." if len(text) > 200 else text
    category = "رواية" if "رواية" in text else "عام"
    return summary, category

# ===============================================
# استقبال ملفات PDF من القنوات
# ===============================================
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')

        if conn:
            try:
                file_name = document.file_name
                # تحميل الملف مؤقتًا لاستخراج المحتوى
                file_path = f"/tmp/{file_name}"
                await document.get_file().download_to_drive(file_path)
                doc = fitz.open(file_path)
                pages = doc.page_count
                text_content = ""
                for page in doc:
                    text_content += page.get_text()
                doc.close()
                os.remove(file_path)

                # توليد الملخص والتصنيف
                summary, category = generate_summary_and_category(text_content)

                tsv_content = await conn.fetchval(
                    "SELECT to_tsvector('arabic_simple', $1);", text_content
                )
                await conn.execute("""
INSERT INTO books(file_id, file_name, tsv_content, summary, category, pages)
VALUES($1, $2, $3, $4, $5, $6)
ON CONFLICT (file_id) DO UPDATE
SET file_name = EXCLUDED.file_name,
    tsv_content = EXCLUDED.tsv_content,
    summary = EXCLUDED.summary,
    category = EXCLUDED.category,
    pages = EXCLUDED.pages;
""", document.file_id, file_name, tsv_content, summary, category, pages)

                logger.info(f"📚 Indexed book: {file_name}")
            except Exception as e:
                logger.error(f"❌ Error indexing book: {e}")

# ===============================================
# البحث المباشر مع الصفحات
# ===============================================
BOOKS_PER_PAGE = 10

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "channel":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    try:
        books = await conn.fetch("""
SELECT id, file_id, file_name, summary, category, pages
FROM books
WHERE file_name ILIKE '%' || $1 || '%'
   OR tsv_content @@ plainto_tsquery('arabic_simple', $1)
ORDER BY uploaded_at DESC;
""", query)
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
    try:
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
            context.bot_data[f"file_{key}"] = b
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
        await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"❌ Error in send_books_page: {e}")

# ===============================================
# أزرار الملفات
# ===============================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        book = context.bot_data.get(f"file_{key}")
        if book:
            caption = f"📄 عدد الصفحات: {book['pages']}\n🏷️ التصنيف: {book['category']}\n📝 الملخص: {book['summary']}\n\nتم التنزيل بواسطة @Boooksfree1bot"
            await query.message.reply_document(document=book['file_id'], caption=caption)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

# ===============================================
# أوامر أساسية
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في 📚 *مكتبة المعرفة*\n"
        "ابحث عن أي كتاب ببساطة عبر كتابة اسمه هنا.",
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # لوحة الإدارة
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
        logger.info("⚠️ WEB_HOST not available. Running in polling mode.")
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
