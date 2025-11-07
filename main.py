import os
import asyncpg
import hashlib
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    PicklePersistence,
)
from admin_panel import register_admin_handlers
from search import register_search_handlers  # استدعاء ملف البحث الجديد

# ===============================================
#       قاعدة البيانات والإعداد
# ===============================================

async def init_db(app_context: ContextTypes):
    """تهيئة الاتصال بقاعدة البيانات وإنشاء الجداول."""
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing. Cannot connect to DB.")
            return

        conn = await asyncpg.connect(db_url)

        # إعداد اللغة العربية للبحث
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
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
        await conn.execute(
            "ALTER TEXT SEARCH CONFIGURATION arabic_simple ALTER MAPPING "
            "FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part "
            "WITH unaccent, simple;"
        )

        # الجداول
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

        await conn.execute("DROP TRIGGER IF EXISTS tsv_update_trigger ON books;")
        await conn.execute("DROP FUNCTION IF EXISTS update_books_tsv();")
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data["db_conn"] = conn
        print("✅ Database connection and setup complete.")
    except Exception as e:
        print(f"❌ Database setup error: {e}")


async def close_db(app: Application):
    """إغلاق الاتصال بقاعدة البيانات."""
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        print("✅ Database connection closed.")


# ===============================================
#       استقبال ملفات PDF من القناة
# ===============================================

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فهرسة ملفات PDF الجديدة من القناة."""
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get("db_conn")

        if conn:
            try:
                file_name = document.file_name
                tsv_content_query = "SELECT to_tsvector('arabic_simple', $1);"
                tsv_content = await conn.fetchval(tsv_content_query, file_name)

                await conn.execute(
                    """
                    INSERT INTO books(file_id, file_name, tsv_content)
                    VALUES($1, $2, $3)
                    ON CONFLICT (file_id) DO UPDATE
                        SET file_name = EXCLUDED.file_name,
                            tsv_content = EXCLUDED.tsv_content
                    """,
                    document.file_id,
                    file_name,
                    tsv_content
                )
                print(f"📚 Book indexed: {file_name}")
            except Exception as e:
                print(f"❌ Error indexing book: {e}")


# ===============================================
#       /start
# ===============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة الذكاء الاصطناعي 📚\n\n"
        "🔍 للبحث عن كتاب استخدم الأمر:\n"
        "`/search اسم الكتاب`\n\n"
        "👑 للدخول إلى لوحة التحكم (للمشرف فقط): /admin",
        parse_mode="Markdown"
    )


# ===============================================
#       التشغيل الرئيسي
# ===============================================

def run_bot():
    token = os.getenv("BOT_TOKEN")
    port = int(os.getenv("PORT", 8080))
    base_url = os.getenv("WEB_HOST")

    if not token:
        print("🚨 BOT_TOKEN missing in environment variables.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    original_start_handler = start

    # أوامر أساسية
    app.add_handler(CommandHandler("start", original_start_handler))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))

    # لوحة التحكم + البحث الجديد
    register_admin_handlers(app, original_start_handler)
    register_search_handlers(app)

    # تشغيل البوت
    if base_url:
        webhook_url = f"https://{base_url}"
        print(f"🤖 Running via Webhook on {webhook_url}:{port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}",
            secret_token=os.getenv("WEBHOOK_SECRET")
        )
    else:
        print("⚠️ WEB_HOST not available. Running in Polling mode.")
        app.run_polling(poll_interval=1.0)


if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"Fatal error: {e}")
