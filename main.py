import os
import asyncio
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, PicklePersistence, CallbackQueryHandler
)
from admin_panel import register_admin_handlers

# ===============================================
#       إعداد قاعدة البيانات
# ===============================================

async def init_db(conn_str):
    try:
        conn = await asyncpg.connect(conn_str)
        print("✅ Connected to database.")

        # إنشاء الامتدادات والجداول
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
        return conn
    except Exception as e:
        print(f"❌ Database setup error: {e}")
        return None

async def close_db(conn):
    if conn:
        await conn.close()
        print("✅ Database connection closed.")

# ===============================================
#       تشغيل البوت
# ===============================================

async def main():
    token = os.getenv("BOT_TOKEN")
    db_url = os.getenv("DATABASE_URL")
    if not token:
        print("🚨 BOT_TOKEN not found in environment.")
        return
    if not db_url:
        print("🚨 DATABASE_URL not found in environment.")
        return

    # إنشاء اتصال قاعدة البيانات
    conn = await init_db(db_url)
    if not conn:
        print("❌ Database connection failed. Exiting.")
        return

    app = Application.builder() \
        .token(token) \
        .persistence(PicklePersistence(filepath="bot_data.pickle")) \
        .build()

    # ربط الاتصال بالبوت
    app.bot_data["db_conn"] = conn

    # إضافة لوحة الإدارة
    register_admin_handlers(app, None)

    # هنا يمكن إضافة جميع الهاندلرز مثل start و callback و PDF و search

    print("⚡ Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
