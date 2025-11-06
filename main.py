import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
DATABASE_URL = os.getenv("DATABASE_URL")

# ----------------- قاعدة البيانات -----------------
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL
        )
    """)
    return conn

# ----------------- حفظ الكتاب -----------------
async def save_book(conn, file_id, file_name):
    await conn.execute(
        "INSERT INTO books(file_id, file_name) VALUES($1, $2)",
        file_id, file_name
    )

# ----------------- البحث عن كتاب -----------------
async def search_book(conn, book_name):
    rows = await conn.fetch(
        "SELECT file_id, file_name FROM books WHERE LOWER(file_name) LIKE $1",
        f"%{book_name.lower()}%"
    )
    return rows

# ----------------- استلام الملفات -----------------
async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document:
        file = update.channel_post.document
        file_id = file.file_id
        file_name = file.file_name
        # حفظ الكتاب في قاعدة البيانات
        await save_book(context.bot_data["db_conn"], file_id, file_name)
        print(f"تم فهرسة الكتاب: {file_name}")

# ----------------- أمر البحث -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! أرسل اسم الكتاب للبحث عنه.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text
    results = await search_book(context.bot_data["db_conn"], book_name)
    if not results:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
        return
    for row in results:
        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=row['file_id'],
            filename=row['file_name']
        )

# ----------------- تشغيل البوت -----------------
async def main():
    db_conn = await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.bot_data["db_conn"] = db_conn

    # استقبال الرسائل من القناة
    app.add_handler(MessageHandler(filters.Document.ALL & filters.Chat(CHANNEL_USERNAME), handle_channel_message))

    # أوامر المستخدمين
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
