import os
import asyncio
import asyncpg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# قراءة المتغيرات من البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # تأكد من وضع الرقم فقط بدون @
DATABASE_URL = os.getenv("DATABASE_URL")

# التأكد من وجود المتغيرات
if not all([BOT_TOKEN, CHANNEL_ID, DATABASE_URL]):
    raise ValueError("تأكد من تعيين BOT_TOKEN وCHANNEL_ID وDATABASE_URL في متغيرات البيئة")

# تهيئة قاعدة البيانات
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        );
    """)
    return conn

# إضافة كتاب إلى قاعدة البيانات
async def add_book_to_db(conn, title, file_id):
    await conn.execute("INSERT INTO books(title, file_id) VALUES($1, $2)", title, file_id)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب للبحث عنه.")

# استقبال الكتب من المستخدم أو القناة وإدخالها في قاعدة البيانات
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        await update.message.reply_text("الرجاء إرسال ملف بصيغة PDF.")
        return

    document = update.message.document
    title = document.file_name
    file_id = document.file_id

    # الاتصال بقاعدة البيانات
    conn = await init_db()
    await add_book_to_db(conn, title, file_id)
    await conn.close()

    await update.message.reply_text(f"تم فهرسة الكتاب: {title}")

# البحث عن كتاب
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("اكتب اسم الكتاب بعد الأمر /search")
        return

    query = " ".join(context.args).lower()
    conn = await init_db()
    rows = await conn.fetch("SELECT title, file_id FROM books WHERE LOWER(title) LIKE $1", f"%{query}%")
    await conn.close()

    if not rows:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
        return

    for row in rows:
        await context.bot.send_document(chat_id=update.message.chat_id, document=row["file_id"], caption=row["title"])

# إنشاء التطبيق وتشغيل البوت
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("البوت جاهز للعمل...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
