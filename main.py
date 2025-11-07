import os
import asyncpg
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes
)
from datetime import datetime

# ------------------ تهيئة قاعدة البيانات ------------------

async def execute_db_commands(conn, commands):
    """تنفيذ سلسلة أوامر SQL بأمان"""
    for command in commands:
        try:
            await conn.execute(command)
        except Exception as e:
            print(f"❌ SQL Execution Error on command: {command[:60]}... Error: {e}")

async def init_db(app_context: ContextTypes):
    """إعداد قاعدة البيانات وتهيئة البحث النصي الكامل"""
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)

        # --- 1. الإضافات ---
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")

        # --- 2. إنشاء text search config آمن ---
        create_fts_config = """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = 'arabic_simple'
            ) THEN
                CREATE TEXT SEARCH CONFIGURATION arabic_simple (PARSER = default);
            END IF;
        END$$;
        """
        await conn.execute(create_fts_config)

        # --- 3. ضبط إعدادات البحث ---
        await conn.execute("""
        ALTER TEXT SEARCH CONFIGURATION arabic_simple
        ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
        WITH unaccent, simple;
        """)

        # --- 4. إنشاء الجداول ---
        table_commands = [
            """
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                tsv_content tsvector
            );
            """,
            "CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, joined_at TIMESTAMP DEFAULT NOW());",
        ]
        await execute_db_commands(conn, table_commands)

        # --- 5. عمود البحث النصي ---
        await conn.execute("ALTER TABLE books ADD COLUMN IF NOT EXISTS tsv_content tsvector;")

        # --- 6. فهرس البحث ---
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data["db_conn"] = conn
        print("✅ Database connection and FTS setup complete and stable.")

    except Exception as e:
        print(f"❌ Database init error: {e}")


# ------------------ وظائف البوت ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! أرسل اسم أي كتاب وسأجده لك 🔍📚")


async def index_new_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عند وصول كتاب جديد في القناة"""
    if not update.channel_post or not update.channel_post.document:
        return

    document = update.channel_post.document
    file_name = document.file_name
    file_id = document.file_id

    conn = context.bot_data.get("db_conn")
    if not conn:
        print("⚠️ No DB connection. Skipping index.")
        return

    try:
        await conn.execute(
            """
            INSERT INTO books (file_id, file_name, tsv_content)
            VALUES ($1, $2, to_tsvector('arabic_simple', $2))
            ON CONFLICT (file_id) DO NOTHING;
            """,
            file_id, file_name
        )
        print(f"📘 Indexed new book: {file_name}")
    except Exception as e:
        print(f"❌ Error indexing book: {e}")


async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بحث عن كتاب وإرساله"""
    query = update.message.text.strip()
    if not query:
        return await update.message.reply_text("❗ أرسل اسم الكتاب الذي تبحث عنه.")

    conn = context.bot_data.get("db_conn")
    if not conn:
        return await update.message.reply_text("🚨 قاعدة البيانات غير متصلة حالياً.")

    try:
        row = await conn.fetchrow(
            """
            SELECT file_id, file_name FROM books
            WHERE tsv_content @@ plainto_tsquery('arabic_simple', $1)
            ORDER BY uploaded_at DESC LIMIT 1;
            """,
            query
        )

        if row:
            await update.message.reply_document(document=row["file_id"], caption=f"📘 {row['file_name']}")
        else:
            await update.message.reply_text("😔 لم أجد كتاباً بهذا الاسم في المكتبة.")
    except Exception as e:
        print(f"❌ Error searching book: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث.")


# ------------------ تشغيل التطبيق ------------------

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("🚨 BOT_TOKEN environment variable is missing!")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, index_new_book))

    app.post_init = init_db
    print("🚀 Bot is starting...")

    app.run_polling()


if __name__ == "__main__":
    main()
