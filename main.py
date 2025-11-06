import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# تحميل متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
BOOKS_FILE = "books.json"

# تحميل قاعدة البيانات أو إنشاء جديدة
if os.path.exists(BOOKS_FILE):
    with open(BOOKS_FILE, "r", encoding="utf-8") as f:
        books_db = json.load(f)
else:
    books_db = {}

# أمر البدء
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 أهلاً بك في مكتبة الكتب!\n"
        "أرسل اسم الكتاب الذي تبحث عنه وسأرسله لك إذا كان متوفرًا."
    )

# مراقبة القناة عند وصول كتاب جديد
async def channel_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return

    # الحصول على اسم الكتاب من caption أو نص الرسالة
    book_name = (message.caption or message.text or "").strip()
    if not book_name:
        return

    # حفظ في قاعدة البيانات مع file_id
    books_db[book_name.lower()] = message.document.file_id if message.document else None
    with open(BOOKS_FILE, "w", encoding="utf-8") as f:
        json.dump(books_db, f, ensure_ascii=False, indent=2)

# البحث عن الكتاب عند الطلب
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().lower()
    file_id = books_db.get(query)
    if file_id:
        await update.message.reply_document(document=file_id)
    else:
        await update.message.reply_text("❌ لم أجد هذا الكتاب في المكتبة.")

# إعداد التطبيق والبوت
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    # مراقبة الرسائل الجديدة في القناة
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_listener))
    # البحث عند إرسال اسم كتاب
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    app.run_polling()

if __name__ == "__main__":
    main()
