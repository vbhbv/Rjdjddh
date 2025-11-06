import os
import asyncio
import asyncpg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# --- إعداد متغيرات البيئة ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DB_URL = os.environ.get("DATABASE_URL")

# --- قاعدة البيانات ---
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    # إنشاء جدول إذا لم يكن موجودًا
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            file_id TEXT NOT NULL
        )
    """)
    return conn

# --- أوامر البوت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! أرسل اسم الكتاب للبحث عنه.")

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    book_name = " ".join(context.args) if context.args else update.message.text
    if not book_name:
        await update.message.reply_text("الرجاء كتابة اسم الكتاب بعد الأمر أو في الرسالة.")
        return

    await update.message.reply_text(f"جاري البحث عن: {book_name}...")

    conn = await init_db()
    row = await conn.fetchrow("SELECT file_id FROM books WHERE name ILIKE $1 LIMIT 1", book_name)
    if row:
        file_id = row["file_id"]
        await context.bot.send_document(chat_id=update.message.chat_id, document=file_id)
    else:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
    await conn.close()

async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("الرجاء إرسال مستند لإضافته.")
        return

    book_name = update.message.caption if update.message.caption else update.message.document.file_name
    file_id = update.message.document.file_id

    conn = await init_db()
    await conn.execute("INSERT INTO books(name, file_id) VALUES($1, $2)", book_name, file_id)
    await conn.close()
    await update.message.reply_text(f"تم فهرسة الكتاب: {book_name}")

# --- تشغيل البوت ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.ALL, add_book))

    # تشغيل البوت
    app.run_polling()

if __name__ == "__main__":
    main()
