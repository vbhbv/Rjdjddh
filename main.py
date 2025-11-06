import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncpg

# متغيرات البيئة
TOKEN = os.environ.get("BOT_TOKEN")
DB_URL = os.environ.get("DATABASE_URL")  # مثال: postgresql://postgres:password@host:5432/railway

# قاعدة البيانات
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    # إنشاء جدول إذا لم يكن موجودًا
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            book_name TEXT,
            file_id TEXT,
            chat_id BIGINT
        )
    """)
    return conn

# إضافة كتاب
async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        await update.message.reply_text("الرجاء إرسال ملف بصيغة PDF.")
        return

    document = update.message.document
    book_name = update.message.caption or document.file_name

    # حفظ في قاعدة البيانات
    try:
        conn = await init_db()
        await conn.execute(
            "INSERT INTO books(book_name, file_id, chat_id) VALUES($1, $2, $3)",
            book_name, document.file_id, update.message.chat_id
        )
        await conn.close()
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء حفظ الكتاب: {e}")
        return

    await update.message.reply_text(f"✅ تم فهرسة الكتاب: {book_name}")

# البحث عن كتاب
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الرجاء كتابة اسم الكتاب بعد الأمر /search")
        return

    query = " ".join(context.args).lower()
    try:
        conn = await init_db()
        rows = await conn.fetch("SELECT book_name, file_id, chat_id FROM books WHERE LOWER(book_name) LIKE $1", f"%{query}%")
        await conn.close()
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء البحث: {e}")
        return

    if not rows:
        await update.message.reply_text("❌ لم يتم العثور على الكتاب.")
        return

    for row in rows:
        await context.bot.send_document(chat_id=update.message.chat_id, document=row["file_id"], caption=row["book_name"])

# بدء البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل لي ملفات PDF لأقوم بفهرستها. للبحث عن كتاب استخدم /search <اسم الكتاب>")

# الإعدادات الرئيسية
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.ALL, add_book))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
