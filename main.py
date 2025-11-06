# main.py
import os
import asyncio
import nest_asyncio
import asyncpg
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ===================== إعدادات =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ضع توكن البوت هنا في متغير البيئة
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # الرقم الرقمي للقناة بدون @
DATABASE_URL = os.getenv("DATABASE_URL")  # رابط قاعدة البيانات PostgreSQL

nest_asyncio.apply()  # لتجنب مشاكل حلقة asyncio في Railway/Colab

# ===================== قاعدة البيانات =====================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            caption TEXT,
            added_by BIGINT
        )
    """)
    return conn

# ===================== أوامر البوت =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحباً! أرسل /add لإضافة كتاب أو ابحث باسم الكتاب.")

# ===================== إضافة الكتب =====================
async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("الرجاء إرسال ملف بصيغة PDF.")
        return

    document = update.message.document
    file_id = document.file_id
    file_name = document.file_name
    caption = update.message.caption or file_name

    async with context.bot_data["db"].transaction():
        await context.bot_data["db"].execute(
            "INSERT INTO books(file_id, file_name, caption, added_by) VALUES($1,$2,$3,$4)",
            file_id, file_name, caption, update.message.from_user.id
        )
    await update.message.reply_text(f"تمت إضافة الكتاب: {file_name}")

# ===================== البحث عن الكتب =====================
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("اكتب اسم الكتاب بعد /search")
        return

    rows = await context.bot_data["db"].fetch(
        "SELECT file_id, file_name FROM books WHERE caption ILIKE $1", f"%{query}%"
    )
    if not rows:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
        return

    for row in rows:
        await context.bot.send_document(chat_id=update.message.chat_id, document=row["file_id"], caption=row["file_name"])

# ===================== دالة تشغيل البوت =====================
async def main():
    db_conn = await init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.bot_data["db"] = db_conn

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_book))
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.PDF, add_book))  # لإضافة الكتب مباشرة بصيغة PDF

    # تشغيل البوت بشكل صحيح داخل حلقة asyncio الحالية
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

# ===================== تشغيل البوت =====================
asyncio.get_event_loop().run_until_complete(main())
