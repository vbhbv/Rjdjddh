import os
import asyncio
from telethon import TelegramClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import asyncpg

# ---- إعدادات البيئة ----
BOT_TOKEN = os.environ['BOT_TOKEN']
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
CHANNEL_USERNAME = "books921383837"  # القناة التي يكون البوت أدمن فيها
DB_URL = os.environ['DATABASE_URL']  # قاعدة البيانات على Railway

# ---- قاعدة البيانات ----
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            title TEXT NOT NULL
        );
    """)
    return conn

# ---- Telethon client ----
client = TelegramClient('user_session', API_ID, API_HASH)

async def index_books():
    """فهرسة الكتب من القناة إلى قاعدة البيانات"""
    conn = await init_db()
    async for message in client.iter_messages(CHANNEL_USERNAME, limit=None):
        if message.document:
            title = message.file.name if not message.caption else message.caption
            await conn.execute(
                "INSERT INTO books(file_id, title) VALUES($1, $2) ON CONFLICT DO NOTHING",
                message.document.id,
                title
            )
    await conn.close()

# ---- بوت تليجرام ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب للبحث.")

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text.strip()
    conn = await init_db()
    row = await conn.fetchrow("SELECT file_id, title FROM books WHERE LOWER(title) LIKE $1 LIMIT 1", f"%{book_name.lower()}%")
    if row:
        await context.bot.send_document(chat_id=update.message.chat_id, document=row['file_id'], caption=row['title'])
    else:
        await update.message.reply_text("لم أجد الكتاب المطلوب.")
    await conn.close()

# ---- main ----
async def main():
    await client.start()
    # فهرسة الكتب عند بدء التشغيل
    await index_books()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
