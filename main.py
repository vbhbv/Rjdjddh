# main.py
import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PicklePersistence

# استدعاء نظام المشرفين
from admin_panel import register_admin_handlers 

# ==============================
#       إعداد قاعدة البيانات
# ==============================

async def init_db(app_context: ContextTypes):
    """Initializes DB connection and sets up FTS infrastructure robustly."""
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing. Cannot connect to DB.")
            return

        conn = await asyncpg.connect(db_url)

        # --- 1. CREATE EXTENSIONS & TEXT SEARCH CONFIG ---
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        # PostgreSQL لا يدعم IF NOT EXISTS هنا لذا استخدم DO block
        await conn.execute("""
        DO $$
        BEGIN
           IF NOT EXISTS (
              SELECT 1 FROM pg_ts_config WHERE cfgname = 'arabic_simple'
           ) THEN
              CREATE TEXT SEARCH CONFIGURATION arabic_simple (PARSER = default);
           END IF;
        END
        $$;
        """)
        await conn.execute("""
        ALTER TEXT SEARCH CONFIGURATION arabic_simple 
        ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
        WITH unaccent, simple;
        """)

        # --- 2. CREATE TABLES ---
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

        # --- 3. CLEANUP & FTS INDEX ---
        await conn.execute("DROP TRIGGER IF EXISTS tsv_update_trigger ON books;")
        await conn.execute("DROP FUNCTION IF EXISTS update_books_tsv();")
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data['db_conn'] = conn
        print("✅ Database connection and FTS setup complete.")
    except Exception as e:
        print(f"❌ Database setup error: {e}")

# ==============================
#       إغلاق الاتصال عند الإيقاف
# ==============================

async def close_db(app: Application):
    conn = app.bot_data.get('db_conn')
    if conn:
        await conn.close()
        print("✅ Database connection closed.")

# ==============================
#       التعامل مع PDF
# ==============================

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                file_name = document.file_name
                tsv_content = await conn.fetchval("SELECT to_tsvector('arabic_simple', $1);", file_name)
                await conn.execute(
                    "INSERT INTO books(file_id, file_name, tsv_content) VALUES($1,$2,$3) "
                    "ON CONFLICT (file_id) DO UPDATE SET file_name=EXCLUDED.file_name, tsv_content=EXCLUDED.tsv_content",
                    document.file_id, file_name, tsv_content
                )
                print(f"📖 Indexed book: {file_name}")
            except Exception as e:
                print(f"❌ Error indexing book: {e}")

# ==============================
#       البحث عن الكتب
# ==============================

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "channel":
        return
    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return

    search_term = " ".join(context.args).strip()
    conn = context.bot_data.get('db_conn')
    if conn:
        query_text = search_term.replace(' ', ' & ')
        results = await conn.fetch(
            "SELECT file_id, file_name FROM books WHERE tsv_content @@ to_tsquery('arabic_simple', $1) "
            "ORDER BY file_name ASC LIMIT 10;",
            query_text
        )

        if not results:
            await update.message.reply_text(f"❌ لم يتم العثور على كتاب يطابق '{search_term}'.")
            return

        if len(results) == 1:
            try:
                await update.message.reply_document(document=results[0]['file_id'],
                                                    caption=f"✅ تم العثور على الكتاب: **{results[0]['file_name']}**")
            except:
                await update.message.reply_text("❌ لم أتمكن من إرسال الملف.")
        else:
            message_text = f"📚 تم العثور على **{len(results)}** كتاب يطابق بحثك '{search_term}':\n\n" \
                           "اختر النسخة المطلوبة:"
            keyboard = [[InlineKeyboardButton(f"🔗 {r['file_name']}", callback_data=f"file:{r['file_id'][:50]}")] for r in results]
            await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard),
                                            parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات حالياً.")

# ==============================
#       /start
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا بك في مكتبة البوت! 📚\n"
                                    "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب")

# ==============================
#       Main Bot Runner
# ==============================

def run_bot():
    token = os.getenv("BOT_TOKEN")
    port = int(os.environ.get('PORT', 8080))
    base_url = os.environ.get('WEB_HOST')

    if not token:
        print("🚨 BOT_TOKEN is missing.")
        return

    app = (Application.builder()
           .token(token)
           .post_init(init_db)
           .post_shutdown(close_db)
           .persistence(PicklePersistence(filepath="bot_data.pickle"))
           .build())

    original_start_handler = start
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    register_admin_handlers(app, original_start_handler)

    if base_url:
        webhook_url = f'https://{base_url}'
        print(f"🤖 Running bot via Webhook: {webhook_url}:{port}")
        app.run_webhook(listen="0.0.0.0", port=port, url_path=token, webhook_url=f"{webhook_url}/{token}")
    else:
        print("⚠️ WEB_HOST not available. Falling back to Polling.")
        app.run_polling(poll_interval=1.0)


if __name__ == "__main__":
    run_bot()
