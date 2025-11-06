import os
import asyncio
from telethon import TelegramClient
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
CHANNEL = os.getenv("CHANNEL_ID")  # @books921383837

# إنشاء Telethon للبوت
client = TelegramClient('bot_session', API_ID, API_HASH)

# البحث في القناة
async def search_book_telethon(book_name):
    book_name = book_name.lower()
    async for message in client.iter_messages(CHANNEL, limit=1000):
        if message.document and book_name in message.file.name.lower():
            return message.document
    return None

# تفاعل البوت مع المستخدم
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب وسأبحث عنه لك.")

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    book_name = update.message.text
    await update.message.reply_text("جاري البحث عن الكتاب... ⏳")
    document = await search_book_telethon(book_name)
    if document:
        await context.bot.send_document(chat_id=update.message.chat_id, document=document)
    else:
        await update.message.reply_text("عذرًا، لم يتم العثور على الكتاب.")

# تشغيل البوت
async def start_bot():
    # تشغيل Telethon كبوت
    await client.start(bot_token=BOT_TOKEN)
    
    # إنشاء البوت على Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    
    # تشغيل polling بشكل آمن في أي event loop
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await client.run_until_disconnected()  # Telethon يبقى متصلاً

# هذا الجزء يعمل في أي حلقة موجودة مسبقًا
loop = asyncio.get_event_loop()
loop.create_task(start_bot())

# لا ننهي الحلقة لأن Railway يحافظ عليها مفتوحة
loop.run_forever()
