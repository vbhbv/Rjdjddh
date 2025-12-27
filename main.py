import os
import asyncpg
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)
import hashlib

from admin_panel import register_admin_handlers

# ----------------------------
# إعداد اللوج
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------
# إعداد قاعدة البيانات
# ----------------------------
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trgm_books ON books USING gin (file_name gin_trgm_ops);")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            book_id INT REFERENCES books(id),
            user_id BIGINT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        );
        """)

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database ready.")
    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ----------------------------
# استقبال ملفات PDF
# ----------------------------
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        if not conn:
            return
        await conn.execute("""
        INSERT INTO books(file_id, file_name)
        VALUES($1, $2)
        ON CONFLICT (file_id) DO UPDATE SET file_name = EXCLUDED.file_name;
        """, document.file_id, document.file_name)
        logger.info(f"📚 Indexed book: {document.file_name}")

# ----------------------------
# الاشتراك الإجباري
# ----------------------------
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ----------------------------
# عداد المستخدمين
# ----------------------------
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if conn and update.effective_user:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            update.effective_user.id
        )

# ----------------------------
# بيانات الفهرس العربي والإنجليزي
# ----------------------------
INDEXES_AR = [
    ("الروايات", "novels", ["رواية"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال"]),
    ("الشعر", "poetry", ["شعر", "قصيدة"]),
    ("الفيزياء", "physics", ["فيزياء", "طاقة"]),
    ("الرياضيات", "math", ["رياضيات", "هندسة"]),
    ("البرمجة", "programming", ["برمجة", "python"]),
]

INDEXES_EN = [
    ("Novels", "novels_en", ["novel"]),
    ("Children Stories", "children_stories_en", ["children", "story"]),
    ("Poetry", "poetry_en", ["poem"]),
    ("Physics", "physics_en", ["physics"]),
    ("Mathematics", "math_en", ["math", "geometry"]),
    ("Programming", "programming_en", ["programming", "python"]),
]

INDEXES_PER_PAGE = 5

# ----------------------------
# دوال الفهرس
# ----------------------------
async def show_index_page(update, context: ContextTypes.DEFAULT_TYPE, indexes, page: int = 0, index_type="ar"):
    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    current_indexes = indexes[start:end]

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page-1}:{index_type}"))
    if end < len(indexes):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}:{index_type}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📚 اختر الفهرس (صفحة {page+1}/{(len(indexes)-1)//INDEXES_PER_PAGE+1}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "ar"
    await show_index_page(update, context, INDEXES_AR, page, "ar")

async def show_index_en(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "en"
    await show_index_page(update, context, INDEXES_EN, page, "en")

async def navigate_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        parts = query.data.split(":")
        page = int(parts[1])
        index_type = parts[2] if len(parts) > 2 else "ar"
    except:
        await query.message.reply_text("❌ خطأ في تحديد الصفحة.")
        return

    if index_type == "en":
        await show_index_en(update, context, page)
    else:
        await show_index(update, context, page)

async def search_by_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index_key = query.data.replace("index:", "")

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    if any(key == index_key for _, key, _ in INDEXES_EN):
        keywords_list = INDEXES_EN
        context.user_data["current_index_type"] = "en"
    else:
        keywords_list = INDEXES_AR
        context.user_data["current_index_type"] = "ar"

    keywords = []
    for name, key, kws in keywords_list:
        if key == index_key:
            keywords = kws
            break

    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية لهذا الفهرس.")
        return

    # بناء شرط SQL صارم
    sql_condition = " OR ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])

    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {sql_condition}
            ORDER BY uploaded_at DESC;
        """)
    except Exception:
        await query.message.reply_text("❌ حدث خطأ أثناء البحث عن الكتب.")
        return

    if not books:
        await query.message.reply_text("❌ لم يتم العثور على أي كتب ضمن هذا الفهرس.")
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"فهرس: {index_key}"
    context.user_data["is_index"] = True
    context.user_data["index_key"] = index_key

    # زر العودة للفهرس
    await send_books_page(update, context, include_index_home=True)

# ----------------------------
# دوال البحث وعرض الكتب
# ----------------------------
BOOKS_PER_PAGE = 5

def normalize_query(text: str) -> str:
    if not text: return ""
    text = text.lower().strip()
    repls = str.maketrans("أإآةى", "اااوه")
    text = text.translate(repls)
    return ' '.join(text.split())

async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip()
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    norm_q = normalize_query(query_text)
    rows = await conn.fetch("""
        SELECT id, file_id, file_name FROM books
        WHERE file_name ILIKE $1
        ORDER BY uploaded_at DESC
        LIMIT 500
    """, f"%{norm_q}%")

    if not rows:
        await update.message.reply_text("❌ لم يتم العثور على كتب مشابهة.")
        return

    context.user_data["search_results"] = [dict(r) for r in rows]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "نتائج البحث"
    context.user_data["is_index"] = False

    await send_books_page(update, context)

async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home=False):
    results = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_batch = results[start:end]

    text = f"📚 **{context.user_data.get('search_stage','الكتب')}**\nصفحة {page+1} من {(len(results)-1)//BOOKS_PER_PAGE + 1}\n\n"

    keyboard = []
    for b in current_batch:
        display_name = b["file_name"] if len(b["file_name"]) < 50 else b["file_name"][:47] + "..."
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📖 {display_name}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(results):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    if include_index_home:
        index_type = context.user_data.get("current_index_type","ar")
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data=f"show_index_{index_type}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(
                document=file_id,
                caption="تم التنزيل بواسطة @Boooksfreee1bot"
            )
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context, include_index_home=context.user_data.get("is_index", False))
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context, include_index_home=context.user_data.get("is_index", False))
    elif data.startswith("index:"):
        await search_by_index(update, context)
    elif data.startswith("index_page:"):
        await navigate_index_pages(update, context)
    elif data.startswith("show_index_ar"):
        await show_index(update, context)
    elif data.startswith("show_index_en"):
        await show_index_en(update, context)
    elif data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            await start_user_message(query.from_user.id, context)
        else:
            await query.message.edit_text("يرجى الاشتراك أولاً.")

# ----------------------------
# رسالة البدء
# ----------------------------
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await register_user(update, context)
    user_id = update.effective_user.id
    if not await check_subscription(user_id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "🌿 أهلًا بك!\nللوصول إلى مكتبة الكتب الكاملة، يرجى الاشتراك.",
            reply_markup=keyboard
        )
        return

    await start_user_message(user_id, context)

async def start_user_message(user_id, context):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")],
        [InlineKeyboardButton("📚 عرض الفهرس العربي", callback_data="show_index_ar")],
        [InlineKeyboardButton("📚 عرض الفهرس الإنجليزي", callback_data="show_index_en")]
    ])
    text = (
        "👋 **أهلاً بك في المكتبة الرقمية**\n\n"
        "📖 **تعليمات الاستخدام:**\n"
        "1️⃣ أرسل اسم الكتاب أو المؤلف للبحث.\n"
        "2️⃣ استخدم الفهارس لتصفح الكتب حسب التصنيف.\n\n"
        "⚖️ **حقوق الملكية الفكرية:**\n"
        "إذا كنت صاحب حق وترغب في إزالة محتوى، تواصل معنا."
    )
    await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")

# ----------------------------
# تشغيل البوت
# ----------------------------
def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        logger.error("🚨 BOT_TOKEN not found in environment.")
        return

    app = Application.builder() \
        .token(token) \
        .post_init(init_db) \
        .post_shutdown(close_db) \
        .persistence(PicklePersistence(filepath="bot_data.pickle")) \
        .build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(CommandHandler("start", start))

    register_admin_handlers(app, start)

    if base_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"https://{base_url}/{token}"
        )
    else:
        app.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    run_bot()
