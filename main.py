import os
import asyncio
import asyncpg
from telegram import Update, Document
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

DB_URL = os.environ.get("DATABASE_URL")

# ---------- قاعدة البيانات ----------
async def init_db():
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            file_id TEXT,
            title TEXT
        )
    """)
    return conn

# ---------- أوامر البوت ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً! سأقوم بفهرسة أي كتاب PDF يتم إرساله أو إعادة توجيهه إلى هذه القناة.")

# ---------- التعامل مع ملفات PDF ----------
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    doc: Document = update.message.document
    # قد يكون المستند ملف PDF
    if doc and doc.file_name.lower().endswith(".pdf"):
        title = doc.file_name
        file_id = doc.file_id
        chat_id = update.message.chat_id

        # تحقق إن كان الكتاب موجودًا مسبقًا
        exists = await context.bot_data["db"].fetchval(
            "SELECT 1 FROM books WHERE chat_id=$1 AND file_id=$2",
            chat_id, file_id
        )
        if exists:
            return  # لا تضيفه مرتين

        # حفظ في قاعدة البيانات
        await context.bot_data["db"].execute(
            "INSERT INTO books(chat_id, file_id, title) VALUES($1, $2, $3)",
            chat_id, file_id, title
        )
        await update.message.reply_text(f"تم فهرسة الكتاب: {title}")

# ---------- البحث ----------
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    query = update.message.text.lower()
    rows = await context.bot_data["db"].fetch(
        "SELECT file_id, title FROM books WHERE LOWER(title) LIKE $1 LIMIT 1",
        f"%{query}%"
    )
    if not rows:
        await update.message.reply_text("لم أجد الكتاب.")
        return
    file_id, title = rows[0]["file_id"], rows[0]["title"]
    await update.message.reply_document(file_id, caption=title)

# ---------- التشغيل ----------
async def main():
    db_conn = await init_db()

    app = ApplicationBuilder().token(os.environ.get("BOT_TOKEN")).build()
    app.bot_data["db"] = db_conn

    app.add_handler(CommandHandler("start", start))
    # أي مستند PDF يتم استقباله أو إعادة توجيهه
    app.add_handler(MessageHandler(filters.Document.FileExtension("pdf") | filters.FORWARDED, handle_pdf))
    # البحث عن الكتب
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("البوت يعمل الآن على فهرسة جميع ملفات PDF تلقائيًا!")
    await app.updater.idle()
    await app.stop()
    await app.shutdown()
    await db_conn.close()

# ---------- حل مشكلة حلقة الأحداث ----------
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = None

if loop and loop.is_running():
    asyncio.ensure_future(main())
else:
    asyncio.run(main())
