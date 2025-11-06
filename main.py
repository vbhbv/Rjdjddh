import os
import asyncio
from telethon import TelegramClient
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ======================================
# 1️⃣ متغيرات البيئة
# تأكد من ضبط هذه المتغيرات في Railway
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL_ID"]  # مثال: "@books921383837"

# اسم ملف session
SESSION_FILE = "user_session.session"
# ======================================

# ======================================
# 2️⃣ إعداد Userbot
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def start_userbot():
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ حساب Userbot غير مفعل! تحقق من ملف session.")
    else:
        print("✅ Userbot جاهز للعمل")
# ======================================

# ======================================
# 3️⃣ دالة البحث وإرسال الكتاب
async def fetch_and_send(book_query: str, telegram_bot: Bot, user_chat_id: int, limit: int = 1000):
    book_query = book_query.lower().strip()

    async for msg in client.iter_messages(CHANNEL, limit=limit):
        doc = msg.document
        fname = msg.file.name.lower() if doc and msg.file.name else ""
        caption = msg.caption.lower() if msg.caption else ""

        if (fname and book_query in fname) or (caption and book_query in caption):
            tmp_name = f"/tmp/{msg.id}_{(doc.name or 'file')}".replace("/", "_")
            path = await client.download_media(msg, file=tmp_name)
            try:
                with open(path, "rb") as f:
                    await telegram_bot.send_document(chat_id=user_chat_id, document=f)
                return True
            finally:
                try:
                    os.remove(path)
                except Exception:
                    pass
    return False
# ======================================

# ======================================
# 4️⃣ بوت التليجرام الرسمي
async def start(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب وسأبحث عنه لك.")

async def search_book(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text
    await update.message.reply_text("جاري البحث عن الكتاب... ⏳")
    found = await fetch_and_send(book_name, context.bot, update.message.chat_id)
    if not found:
        await update.message.reply_text("لم يتم العثور على الكتاب.")
# ======================================

# ======================================
# 5️⃣ تشغيل البوت + Userbot
async def start_bot():
    await start_userbot()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("✅ البوت بدأ العمل!")
    
    await client.run_until_disconnected()

# تشغيل البوت على أي بيئة (Railway أو VPS)
asyncio.run(start_bot())
# ======================================
