import os
import asyncio
from telethon import TelegramClient
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import nest_asyncio

nest_asyncio.apply()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ["CHANNEL_ID"]
SESSION_FILE = "user_session.session"

# Userbot
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

async def start_userbot():
    await client.start()
    print("✅ Userbot جاهز!")

# البحث وإرسال الكتاب
async def fetch_and_send(book_query: str, telegram_bot, user_chat_id: int, limit: int = 1000):
    book_query = book_query.lower().strip()
    async for msg in client.iter_messages(CHANNEL, limit=limit):
        doc = msg.document
        fname = doc.name.lower() if doc and getattr(doc, "name", None) else ""
        caption = getattr(msg, "message", "")
        caption = caption.lower() if caption else ""
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

# البوت الرسمي
async def start(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب وسأبحث عنه لك.")

async def search_book(update: ContextTypes.DEFAULT_TYPE, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text
    await update.message.reply_text("جاري البحث عن الكتاب... ⏳")
    found = await fetch_and_send(book_name, context.bot, update.message.chat_id)
    if not found:
        await update.message.reply_text("لم يتم العثور على الكتاب.")

# تشغيل البوت + Userbot معًا
async def main():
    await start_userbot()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

    # إنشاء مهمة asyncio للبوت الرسمي
    bot_task = asyncio.create_task(app.run_polling())
    # إنشاء مهمة asyncio لتشغيل Userbot في الخلفية
    userbot_task = asyncio.create_task(client.run_until_disconnected())

    # انتظار كل المهام معًا
    await asyncio.gather(bot_task, userbot_task)

# تشغيل كل شيء
asyncio.run(main())
