import os
import asyncpg
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

# 💡 ملاحظة: يجب أن تكون هذه الملفات (booksai, admin_panel) موجودة في نفس مجلد التشغيل
from booksai import ai_search, ai_suggest_books
from admin_panel import register_admin_handlers

# رابط القناة مباشرة للاشتراك الإجباري
CHANNEL_USERNAME = "@iiollr"

# ===============================================
# إعداد اللوج
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# إعداد قاعدة البيانات
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        await conn.execute("""
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'arabic_simple') THEN
       CREATE TEXT SEARCH CONFIGURATION arabic_simple (PARSER = default);
   END IF;
END
$$;
""")
        await conn.execute("""
ALTER TEXT SEARCH CONFIGURATION arabic_simple ALTER MAPPING
FOR word, hword, hword_part, asciiword, asciihword, hword_asciipart
WITH unaccent, simple;
""")

        # الجداول
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
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database connection and setup complete.")
    except Exception as e:
        logger.error(f"❌ Database setup error: {e}")

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ===============================================
# الاشتراك الإجباري
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        # التحقق من أن الحالة هي عضو، إداري، أو منشئ
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"❌ Subscription check failed (Check Bot Admin Status): {e}")
        return False

# ===============================================
# استقبال ملفات PDF من القنوات
# ===============================================
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')

        if not conn:
            logger.error("❌ Database not connected.")
            return

        try:
            await conn.execute("""
INSERT INTO books(file_id, file_name)
VALUES($1, $2)
ON CONFLICT (file_id) DO UPDATE
SET file_name = EXCLUDED.file_name;
""", document.file_id, document.file_name)
            logger.info(f"📚 Indexed book: {document.file_name}")
        except Exception as e:
            logger.error(f"❌ Error indexing book: {e}")

# ===============================================
# البحث عن الكتب
# ===============================================
BOOKS_PER_PAGE = 10

async def search_books_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    # 💡 التحقق من الاشتراك قبل البحث
    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ])
        await update.message.reply_text(
            f"🚫 الاشتراك في القناة {CHANNEL_USERNAME} إلزامي للبحث.\nاضغط على الزر ثم أعد المحاولة.",
            reply_markup=keyboard
        )
        return

    mode = context.user_data.get("mode", "normal")
    query = update.message.text.strip()
    conn = context.bot_data.get('db_conn')

    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    books = []

    if mode == "normal":
        books = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE file_name ILIKE '%' || $1 || '%'
ORDER BY uploaded_at DESC;
""", query)
    elif mode == "keywords":
        # البحث الذكي باستخدام الكلمات المفتاحية عبر الذكاء الاصطناعي
        suggested_titles = await ai_search(query)
        if suggested_titles:
            books = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE file_name = ANY($1::text[])
ORDER BY uploaded_at DESC;
""", suggested_titles)
    elif mode == "ai":
        # البحث الذكي + وصف الكتاب
        suggested_titles = await ai_search(query)
        if suggested_titles:
            books = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE file_name = ANY($1::text[])
ORDER BY uploaded_at DESC;
""", suggested_titles)
    elif mode == "suggest":
        # اقتراح كتب بناء على الموضوع
        books = await ai_suggest_books(query, conn)

    if not books:
        await update.message.reply_text(f"❌ لم أجد أي كتب تطابق: {query}")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

async def send_books_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        # 💡 التعديل: استخدام ID الكتاب من قاعدة البيانات مباشرة (لضمان عمل الزر دائماً)
        book_id = b["id"]
        keyboard.append([
            InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"book_id:{book_id}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        # عند التنقل بين الصفحات، قم بتحرير الرسالة بدلاً من الرد برسالة جديدة
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# ===============================================
# أزرار القائمة الرئيسية ومعالج الاستدعاء
# ===============================================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 بحث عادي", callback_data="search_normal")],
        [InlineKeyboardButton("🤖 البحث بالذكاء الاصطناعي", callback_data="search_ai")],
        [InlineKeyboardButton("💡 اقتراح كتاب", callback_data="suggest_book")],
        [InlineKeyboardButton("📖 البحث بالكلمات المفتاحية", callback_data="search_keywords")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "👋 أهلاً بك! كيف تريد أن تبحث عن الكتاب؟"
    if update.callback_query:
        await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = context.bot_data.get('db_conn')

    # 1. معالجة أوضاع البحث
    if data == "search_normal":
        context.user_data["mode"] = "normal"
        await query.message.edit_text("✏️ وضع البحث العادي: اكتب اسم الكتاب أو المؤلف للبحث:")
    elif data == "search_ai":
        context.user_data["mode"] = "ai"
        await query.message.edit_text("🤖 وضع الذكاء الاصطناعي: اكتب اسم الكتاب ليقوم بجلب الوصف:")
    elif data == "suggest_book":
        context.user_data["mode"] = "suggest"
        await query.message.edit_text("💡 وضع الاقتراح: اكتب المجال الذي تريد اقتراح كتب فيه:")
    elif data == "search_keywords":
        context.user_data["mode"] = "keywords"
        await query.message.edit_text("📖 وضع الكلمات المفتاحية: اكتب كلمات مفتاحية عن الكتاب أو أحداثه:")

    # 2. معالجة زر طلب الملف (التعديل الذي يضمن عمل الزر)
    elif data.startswith("book_id:"):
        if not conn:
            await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
            return

        book_id = int(data.split(":")[1])
        try:
            # 💡 جلب الـ file_id من قاعدة البيانات باستخدام ID الكتاب
            result = await conn.fetchrow("SELECT file_id FROM books WHERE id = $1", book_id)
            file_id = result['file_id'] if result else None

            if file_id:
                caption = "📥 تم التنزيل بواسطة @Boooksfree1bot"
                await query.message.reply_document(document=file_id, caption=caption)
            else:
                await query.message.reply_text("❌ الملف غير متوفر حالياً.")
        except Exception as e:
            logger.error(f"❌ Error retrieving book file: {e}")
            await query.message.reply_text("❌ حدث خطأ أثناء جلب الملف.")

    # 3. معالجة أزرار التنقل
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

# ===============================================
# أوامر البوت
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 💡 تطبيق التحقق من الاشتراك الإجباري على أمر /start
    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ])
        await update.message.reply_text(
            f"🚫 الاشتراك في القناة {CHANNEL_USERNAME} إلزامي.\nاضغط على الزر ثم أعد إرسال الأمر.",
            reply_markup=keyboard
        )
        return
    await main_menu(update, context)

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        logger.error("🚨 BOT_TOKEN not found in environment.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    # الأوامر والمعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_handler))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    # 💡 التعديل: إزالة النمط المعقد لضمان عمل جميع الأزرار
    app.add_handler(CallbackQueryHandler(callback_handler))

    # تسجيل معالجات لوحة التحكم (يجب أن يكون ملف admin_panel.py موجوداً)
    register_admin_handlers(app, start)

    if base_url:
        webhook_url = f"https://{base_url}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}"
        )
    else:
        logger.info("⚠️ WEB_HOST not available. Running in polling mode.")
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
