import os
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------
# تحميل متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")  # ضع التوكن هنا أو في متغيرات البيئة
CHANNEL_ID = os.getenv("CHANNEL_ID")  # ضع الرقم الرقمي للقناة فقط: -100XXXXXXXXX
# ---------------------------------------------

# ----------- دوال البوت -----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "مرحبًا! أرسل لي ملف PDF لأضيفه إلى القناة."
        )

async def add_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # حماية ضد NoneType
    if update.message and update.message.document:
        document = update.message.document
        if document.mime_type == "application/pdf":
            # تحميل الملف
            file_path = f"./{document.file_name}"
            await document.get_file().download_to_drive(file_path)
            
            # إرسال الملف إلى القناة
            await context.bot.send_document(chat_id=int(CHANNEL_ID), document=open(file_path, "rb"))
            
            await update.message.reply_text(f"✅ تم إرسال الملف: {document.file_name}")
        else:
            await update.message.reply_text("❌ هذا ليس ملف PDF، الرجاء إرسال PDF فقط.")
    else:
        if update.message:
            await update.message.reply_text("❌ الرجاء إرسال ملف PDF.")

# ------------------------------------

async def main():
    # إنشاء التطبيق
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة الهاندلرز
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, add_book))

    # تهيئة وتشغيل البوت
    await app.initialize()
    await app.start()
    print("✅ البوت يعمل الآن...")

    # إبقاء البوت شغالًا
    await asyncio.Event().wait()

# ----------- تشغيل البوت -----------
if __name__ == "__main__":
    asyncio.run(main())
