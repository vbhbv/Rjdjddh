import os
import asyncio
import asyncpg
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from admin_system import register_admin_handlers  # ملف المشرفين المنفصل

# ==============================================
# إعدادات البيئة
# ==============================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))  # قناة الفهرسة
DATABASE_URL = os.environ.get("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise ValueError("❌ تأكد من ضبط متغيرات البيئة: BOT_TOKEN و DATABASE_URL")

# ==============================================
# الاتصال بقاعدة البيانات
# ==============================================
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW(),
            tsv_content tsvector
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_books_tsv ON books USING GIN(tsv_content);
    """)
    return conn

# ==============================================
# فهرسة الكتب القادمة من القناة
# ==============================================
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post

    if not message.document:
        return  # فقط ملفات PDF أو كتب

    file = message.document
    file_id = file.file_id
    file_name = file.file_name or "كتاب بدون اسم"

    conn = context.bot_data.get("db_conn")
    if not conn:
        print("⚠️ قاعدة البيانات غير متصلة")
        return

    try:
        await conn.execute("""
            INSERT INTO books (file_id, file_name, tsv_content)
            VALUES ($1, $2, to_tsvector('simple', $2))
            ON CONFLICT (file_id) DO NOTHING;
        """, file_id, file_name)
        print(f"✅ تمت فهرسة الكتاب: {file_name}")
    except Exception as e:
        print(f"❌ خطأ أثناء الفهرسة: {e}")

# ==============================================
# البحث عن كتاب
# ==============================================
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔎 أرسل اسم الكتاب بعد الأمر. مثال:\n`/search رواية`,", parse_mode="Markdown")
        return

    query = " ".join(context.args)
    conn = context.bot_data.get("db_conn")

    if not conn:
        await update.message.reply_text("⚠️ قاعدة البيانات غير متصلة.")
        return

    try:
        rows = await conn.fetch("""
            SELECT file_id, file_name 
            FROM books 
            WHERE to_tsvector('simple', file_name) @@ plainto_tsquery($1)
            ORDER BY uploaded_at DESC
            LIMIT 10;
        """, query)
        
        if not rows:
            await update.message.reply_text("❌ لم يتم العثور على أي كتاب بهذا الاسم.")
            return
        
        await update.message.reply_text(f"📚 تم العثور على {len(rows)} كتاب:")
        for row in rows:
            await update.message.reply_document(document=row["file_id"], caption=row["file_name"])
    except Exception as e:
        await update.message.reply_text(f"⚠️ خطأ أثناء البحث: {e}")

# ==============================================
# عرض جميع الكتب المفهرسة
# ==============================================
async def list_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("⚠️ قاعدة البيانات غير متصلة.")
        return

    rows = await conn.fetch("SELECT file_name FROM books ORDER BY uploaded_at DESC LIMIT 50;")
    if not rows:
        await update.message.reply_text("📚 لا توجد كتب مفهرسة بعد.")
        return

    text = "\n".join([f"• {r['file_name']}" for r in rows])
    await update.message.reply_text(f"📚 قائمة أحدث الكتب:\n\n{text}")

# ==============================================
# أمر البدء
# ==============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = context.bot_data.get("db_conn")
    if conn and user:
        await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING;", user.id)
    await update.message.reply_text("👋 أهلاً بك! أرسل اسم كتاب للبحث أو استخدم /list لعرض الفهرس.")

# ==============================================
# نقطة الدخول الرئيسية
# ==============================================
async def main():
    print("🚀 بدء تشغيل البوت...")
    conn = await init_db()
    print("✅ تم الاتصال بقاعدة البيانات بنجاح.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.bot_data["db_conn"] = conn

    # أوامر المستخدم
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_books))
    app.add_handler(CommandHandler("search", search_book))

    # استقبال الكتب من القناة
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_channel_post))

    # نظام المشرفين
    register_admin_handlers(app, start)

    print("✅ البوت جاهز الآن.")
    await app.run_polling(close_loop=False)

if __name__ == "__main__":
    asyncio.run(main())
