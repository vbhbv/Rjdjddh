import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncpg
from PyPDF2 import PdfReader

# -------------------------------
# إعدادات اللوج
# -------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# -------------------------------
# متغيرات البيئة
# -------------------------------
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # فقط الرقم بدون @
DATABASE_URL = os.getenv("DATABASE_URL")

# -------------------------------
# إنشاء الاتصال بقاعدة البيانات
# -------------------------------
async def create_db_pool():
    return await asyncpg.create_pool(DATABASE_URL)

db_pool = None  # سيتم تهيئته لاحقاً

# -------------------------------
# أوامر البوت
# -------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا بك في مكتبة البوت! أرسل لي أي ملف PDF لأتمكن من فهرسته.")

# -------------------------------
# فهرسة الملفات
# -------------------------------
async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("الرجاء إرسال ملف بصيغة PDF.")
        return

    file = update.message.document
    if not file.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("هذا الملف ليس PDF. أرسل ملف بصيغة PDF.")
        return

    # تحميل الملف مؤقتًا
    file_path = f"/tmp/{file.file_name}"
    await file.get_file().download_to_drive(file_path)

    # قراءة محتوى الـ PDF
    try:
        reader = PdfReader(file_path)
        text_content = ""
        for page in reader.pages:
            text_content += page.extract_text() or ""
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء قراءة الملف.")
        logging.error(e)
        return

    # حفظ البيانات في قاعدة البيانات
    async with db_pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO books(name, content) VALUES($1, $2)",
            file.file_name, text_content
        )

    await update.message.reply_text(f"تم فهرسة الكتاب: {file.file_name}")

# -------------------------------
# تشغيل البوت
# -------------------------------
async def main():
    global db_pool
    db_pool = await create_db_pool()

    # إنشاء التطبيق
    app = ApplicationBuilder().token(TOKEN).build()

    # إضافة الهاندلرز
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, add_book))

    # تشغيل البوت على Polling
    await app.run_polling()

# -------------------------------
# نقطة البداية
# -------------------------------
if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
