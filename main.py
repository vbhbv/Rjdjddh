import os
import asyncpg
import hashlib
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PicklePersistence, CallbackQueryHandler
)

from admin_panel import register_admin_handlers  # لوحة التحكم

# ===============================================
#       إعداد قاعدة البيانات
# ===============================================

async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing.")
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
        await conn.execute(
            "ALTER TEXT SEARCH CONFIGURATION arabic_simple ALTER MAPPING "
            "FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart "
            "WITH unaccent, simple;"
        )

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                tsv_content tsvector
            );
        """)
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, joined_at TIMESTAMP DEFAULT NOW());")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);")

        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data["db_conn"] = conn
        print("✅ Database connection and setup complete.")
    except Exception as e:
        print(f"❌ Database setup error: {e}")

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        print("✅ Database connection closed.")

# ===============================================
#       استقبال ملفات PDF من القنوات
# ===============================================

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')

        if conn:
            try:
                file_name = document.file_name
                tsv_content = await conn.fetchval("SELECT to_tsvector('arabic_simple', $1);", file_name)
                await conn.execute("""
                    INSERT INTO books(file_id, file_name, tsv_content)
                    VALUES($1, $2, $3)
                    ON CONFLICT (file_id) DO UPDATE
                        SET file_name = EXCLUDED.file_name,
                            tsv_content = EXCLUDED.tsv_content
                """, document.file_id, file_name, tsv_content)
                print(f"📚 Indexed book: {file_name}")
            except Exception as e:
                print(f"❌ Error indexing book: {e}")

# ===============================================
#       البحث التلقائي عن الكتب
# ===============================================

BOOKS_PER_PAGE = 10

async def auto_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "channel":
        return

    query = update.message.text.strip()
    if len(query) < 2:
        return  # تجاهل الرسائل القصيرة جداً

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    books = await conn.fetch("""
        SELECT id, file_id, file_name
        FROM books
        WHERE file_name ILIKE '%' || $1 || '%'
        ORDER BY uploaded_at DESC;
    """, query)

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
        keyboard.append([InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ===============================================
#       معالجات الأزرار
# ===============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(document=file_id)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

# ===============================================
#       أوامر أساسية
# ===============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في 📚 *مكتبة المعرفة*\n"
        "اكتب اسم أي كتاب مباشرة لأبحث لك عنه!",
        parse_mode="Markdown"
    )

# ===============================================
#       تشغيل البوت
# ===============================================

def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        print("🚨 BOT_TOKEN not found in environment.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    # الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_search))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))

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
        print("⚠️ WEB_HOST not available. Running in polling mode.")
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
