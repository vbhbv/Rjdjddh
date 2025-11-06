import os
import asyncpg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================
# 1️⃣ متغيرات البيئة
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN")              # توكن البوت
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # اسم القناة: @books921383837
DB_URL = os.getenv("DATABASE_URL")              # رابط قاعدة البيانات PostgreSQL من Railway

# ==========================
# 2️⃣ إنشاء جدول قاعدة البيانات
# ==========================
async def init_db():
    """
    إنشاء اتصال بقاعدة البيانات PostgreSQL
    وإنشاء جدول الكتب إذا لم يكن موجودًا
    """
    conn = await asyncpg.connect(DB_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_name TEXT PRIMARY KEY,
            file_id TEXT NOT NULL
        )
    """)
    return conn

# ==========================
# 3️⃣ أمر /start
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 أهلاً بك في مكتبة الكتب!\n"
        "أرسل اسم الكتاب الذي تبحث عنه وسأرسله لك إذا كان متوفرًا."
    )

# ==========================
# 4️⃣ مراقبة القناة عند وصول كتاب جديد
# ==========================
async def channel_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    message = update.channel_post
    if not message or not message.document:
        return

    # اسم الكتاب: caption إذا موجود أو اسم الملف
    book_name = (message.caption or message.document.file_name or "").strip()
    if not book_name:
        return

    file_id = message.document.file_id

    # حفظ أو تحديث الكتاب في قاعدة البيانات
    await conn.execute("""
        INSERT INTO books(book_name, file_id) 
        VALUES($1, $2)
        ON CONFLICT (book_name) DO UPDATE
        SET file_id = EXCLUDED.file_id
    """, book_name.lower(), file_id)

    print(f"✅ تم فهرسة الكتاب: {book_name}")

# ==========================
# 5️⃣ البحث عن الكتاب عند الطلب
# ==========================
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    query = update.message.text.strip().lower()
    row = await conn.fetchrow("SELECT file_id FROM books WHERE book_name = $1", query)
    if row:
        await update.message.reply_document(document=row["file_id"])
    else:
        await update.message.reply_text("❌ لم أجد هذا الكتاب في المكتبة.")

# ==========================
# 6️⃣ تشغيل البوت
# ==========================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # اتصال قاعدة البيانات
    db_conn = await init_db()
    app.bot_data["db_conn"] = db_conn

    # إضافة الـ handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_listener))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

    # تشغيل البوت
    await app.run_polling()

# ==========================
# 7️⃣ تشغيل البرنامج
# ==========================
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
