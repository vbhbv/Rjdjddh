import asyncio
import os
import asyncpg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# إعداد متغيرات البيئة
DB_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ---- قاعدة البيانات ----
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            file_id TEXT NOT NULL
        )
    """)
    return conn

async def save_to_db(conn, name, file_id):
    await conn.execute("INSERT INTO books(name, file_id) VALUES($1, $2)", name, file_id)

async def search_book_db(conn, name):
    rows = await conn.fetch("SELECT file_id, name FROM books WHERE name ILIKE $1", f"%{name}%")
    return rows

# ---- أوامر البوت ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل اسم الكتاب للبحث عنه.")

async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.document:
        await msg.reply_text("الرجاء إرسال ملف بصيغة PDF.")
        return

    file_name = msg.document.file_name
    if not file_name.lower().endswith('.pdf'):
        await msg.reply_text("الملف ليس بصيغة PDF.")
        return

    book_name = msg.caption if msg.caption else file_name
    file_id = msg.document.file_id

    await save_to_db(context.bot_data['conn'], book_name, file_id)
    await msg.reply_text(f"✅ تم فهرسة الكتاب: {book_name}")

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب بعد الأمر /search")
        return

    book_name = " ".join(context.args)
    rows = await search_book_db(context.bot_data['conn'], book_name)
    if not rows:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
        return

    for row in rows:
        await context.bot.send_document(chat_id=update.effective_chat.id, document=row['file_id'], caption=row['name'])

# ---- تشغيل البوت ----
async def main():
    conn = await init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.bot_data['conn'] = conn

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.PDF, add_book))

    print("البوت يعمل الآن ...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
