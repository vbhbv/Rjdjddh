import os
import asyncio
from telethon import TelegramClient
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import nest_asyncio

nest_asyncio.apply()

# ===== إعداد المتغيرات =====
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
SESSION_FILE = "user_session.session"

# قناة المكتبة العامة
CHANNEL = "https://t.me/freebooksf"

# إنشاء عميل المستخدم (Userbot)
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)


# ===== تشغيل Userbot =====
async def start_userbot():
    await client.start()
    print("✅ Userbot جاهز ومتصل.")


# ===== البحث عن الكتاب وإرساله =====
async def fetch_and_send(book_query: str, telegram_bot, user_chat_id: int, limit: int = 1500):
    book_query = book_query.lower().strip()
    found = False

    print(f"🔍 جاري البحث عن: {book_query}")

    async for msg in client.iter_messages(CHANNEL, limit=limit):
        text_content = ""
        if getattr(msg, "message", None):
            text_content += msg.message.lower()
        if getattr(msg, "caption", None):
            text_content += msg.caption.lower()

        filename = ""
        if msg.document and getattr(msg.document, "attributes", None):
            try:
                filename = msg.file.name.lower()
            except Exception:
                filename = ""

        # المطابقة
        if book_query in text_content or book_query in filename:
            found = True
            tmp_name = f"/tmp/{msg.id}_{filename or 'book.pdf'}".replace("/", "_")
            path = await client.download_media(msg, file=tmp_name)
            print(f"📚 تم العثور على {filename}, يتم الإرسال للمستخدم...")
            try:
                with open(path, "rb") as f:
                    await telegram_bot.send_document(chat_id=user_chat_id, document=f)
                return True
            except Exception as e:
                print(f"⚠️ خطأ أثناء الإرسال: {e}")
            finally:
                if os.path.exists(path):
                    os.remove(path)
    return found


# ===== أوامر البوت الرسمي =====
async def start(update, context):
    await update.message.reply_text("مرحبًا في مكتبة البوت 📚\nأرسل اسم الكتاب وسأبحث عنه في قناة FreeBooksF.")

async def search_book(update, context):
    book_name = update.message.text
    await update.message.reply_text(f"🔎 جاري البحث عن: {book_name}")
    found = await fetch_and_send(book_name, context.bot, update.message.chat_id)
    if not found:
        await update.message.reply_text("❌ لم يتم العثور على هذا الكتاب، حاول كتابة الاسم الكامل أو بلغة أخرى.")


# ===== التشغيل المتزامن للبوتين =====
async def main():
    await start_userbot()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))

    bot_task = asyncio.create_task(app.run_polling())
    userbot_task = asyncio.create_task(client.run_until_disconnected())

    await asyncio.gather(bot_task, userbot_task)


if __name__ == "__main__":
    asyncio.run(main())
