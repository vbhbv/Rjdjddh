import os
import asyncio
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from PyPDF2 import PdfReader

DB_PATH = "books.db"
BOT_TOKEN = "ضع_هنا_توكن_البوت"

# --- قاعدة البيانات ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT UNIQUE,
            path TEXT
        )
    ''')
    conn.commit()
    conn.close()

def index_books():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    book_dir = "books"  # مجلد الكتب
    for filename in os.listdir(book_dir):
        if filename.endswith(".pdf"):
            path = os.path.join(book_dir, filename)
            try:
                c.execute("INSERT OR IGNORE INTO books (title, path) VALUES (?, ?)", (filename, path))
                print(f"📚 Indexed book: {filename}")
            except Exception as e:
                print("Error indexing:", filename, e)
    conn.commit()
    conn.close()

# --- دوال مساعدة ---
def get_book_info(path):
    try:
        reader = PdfReader(path)
        num_pages = len(reader.pages)
        # التصنيف (ابتكاري): حسب اسم الكتاب
        if "بحث" in path:
            category = "علمي"
        elif "رواية" in path:
            category = "رواية"
        else:
            category = "عام"
        # نبذة: يمكن تطويرها لاحقاً بالملخص الذكي
        summary = f"عدد صفحات الكتاب: {num_pages}\nتصنيف الكتاب: {category}\nنبذة عن الكتاب: ملخص تلقائي."
        return summary
    except:
        return "معلومات الكتاب غير متوفرة."

# --- أوامر البوت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبا! أرسل اسم الكتاب للبحث عنه مباشرة."
    )

async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT title, path FROM books WHERE title LIKE ?", ('%' + query + '%',))
    results = c.fetchall()
    conn.close()
    
    if not results:
        await update.message.reply_text("لم يتم العثور على أي كتاب.")
        return
    
    for title, path in results:
        summary = get_book_info(path)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("شارك الملف", switch_inline_query=title)]
        ])
        caption = f"{summary}\nتم التنزيل بواسطة @Boooksfree1bot"
        await update.message.reply_document(document=open(path, "rb"), caption=caption, reply_markup=keyboard)

# --- تشغيل البوت ---
async def main():
    init_db()
    index_books()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_book))
    
    print("⚡ Bot is running...")
    await app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    asyncio.run(main())
