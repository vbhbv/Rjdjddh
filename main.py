import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

CHANNEL_ID = os.getenv("CHANNEL_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا! أرسل اسم الكتاب وسأبحث عنه لك.")

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    found = False

    async for message in context.bot.get_chat(CHANNEL_ID).iter_history(limit=1000):
        if message.document and query in (message.document.file_name.lower()):
            await context.bot.send_document(chat_id=update.message.chat_id, document=message.document.file_id)
            found = True
            break

    if not found:
        await update.message.reply_text("عذرًا، لم يتم العثور على الكتاب.")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

app.run_polling()
