import os
import asyncio
import hashlib
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, PicklePersistence, filters
)
from admin_panel import register_admin_handlers

# ===============================================
#       إعداد قاعدة البيانات
# ===============================================

async def init_db_pool(db_url):
    try:
        pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=5)
        async with pool.acquire() as conn:
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
        print("✅ Database setup complete.")
        return pool
    except Exception as e:
        print(f"❌ Database setup error: {e}")
        return None

# ===============================================
#       استقبال ملفات PDF من القنوات
# ===============================================

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.channel_post.document if update.channel_post else None
    if document and document.mime_type == "application/pdf":
        pool = context.bot_data.get("db_pool")
        if pool:
            async with pool.acquire() as conn:
                tsv_content = await conn.fetchval("SELECT to_tsvector('arabic_simple', $1);", document.file_name)
                await conn.execute("""
                    INSERT INTO books(file_id, file_name, tsv_content)
                    VALUES($1, $2, $3)
                    ON CONFLICT(file_id) DO UPDATE
                        SET file_name = EXCLUDED.file_name,
                            tsv_content = EXCLUDED.tsv_content;
                """, document.file_id, document.file_name, tsv_content)
                print(f"📚 Indexed book: {document.file_name}")

# ===============================================
#       البحث عن الكتب
# ===============================================

BOOKS_PER_PAGE = 10

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "channel":
        return

    query = update.message.text.strip()
    if not query:
        await update.message.reply_text("📖 أرسل اسم الكتاب للبحث عنه.")
        return

    pool = context.bot_data.get("db_pool")
    async with pool.acquire() as conn:
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
#       التعامل مع الأزرار
# ===============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(
                document=file_id,
                caption="تم التنزيل بواسطة @Boooksfree1bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 شارك الملف", switch_inline_query=file_id)]
                ])
            )
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
        "مرحبًا بك في 📚 *مكتبة المعرفة*\nابحث عن أي كتاب بإرسال اسمه مباشرة",
        parse_mode="Markdown"
    )

# ===============================================
#       تشغيل البوت
# ===============================================

async def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DB_URL = os.getenv("DATABASE_URL")
    if not BOT_TOKEN or not DB_URL:
        print("🚨 Missing BOT_TOKEN or DATABASE_URL in environment.")
        return

    db_pool = await init_db_pool(DB_URL)
    if not db_pool:
        print("❌ Could not initialize database. Exiting.")
        return

    app = Application.builder() \
        .token(BOT_TOKEN) \
        .persistence(PicklePersistence("bot_data.pickle")) \
        .build()

    app.bot_data["db_pool"] = db_pool

    # لوحة الإدارة
    register_admin_handlers(app, None)

    # أوامر البوت
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("⚡ Bot is running...")
    await app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    asyncio.run(main())
