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

# إنشاء عميل Telethon
client = TelegramClient('session_name', API_ID, API_HASH)

# البحث في القناة باستخدام Telethon
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

async def main():
    # بدء Telethon
    await client.start()
    
    # بدء بوت Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
