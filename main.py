import os
import asyncpg
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)
from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks, send_books_page

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
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        logger.info("✅ Extensions (unaccent, pg_trgm) ensured.")

        # جدول الكتب
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            name_normalized TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_fts_books ON books USING gin (to_tsvector('arabic', file_name));")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trgm_books ON books USING gin (file_name gin_trgm_ops);")

        # جدول المستخدمين
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # جدول التنزيلات
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            book_id INT REFERENCES books(id),
            user_id BIGINT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # جدول الإعدادات
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)

        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database connection and high-performance indexing complete.")
    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ===============================================
# استقبال ملفات PDF من القنوات
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        if not conn:
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
# الاشتراك الإجباري
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===============================================
# عداد المستخدمين
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if conn and update.effective_user:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            update.effective_user.id
        )

# ===============================================
# الفهارس المدمجة داخل الملف الرئيسي
# ===============================================
INDEXES_AR = [
    ("روايات", "novels", ["رواية"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال"]),
    ("الشعر", "poetry", ["شعر", "قصيدة"]),
    ("التاريخ", "history", ["تاريخ", "حضارة"]),
    ("الفلسفة", "philosophy", ["فلسفة", "منطق"]),
    ("العلوم", "science", ["علوم", "تجارب"]),
    ("الرياضيات", "math", ["رياضيات", "جبر"]),
    ("البرمجة", "programming", ["برمجة", "python"]),
    ("الهندسة", "engineering", ["هندسة", "ميكانيكا"]),
    ("الطب", "medicine", ["طب", "دواء"])
]

INDEXES_EN = [
    ("Novels", "novels_en", ["novel"]),
    ("Children Stories", "children_stories_en", ["children", "story"]),
    ("Poetry", "poetry_en", ["poem", "poetry"]),
    ("History", "history_en", ["history", "civilization"]),
    ("Philosophy", "philosophy_en", ["philosophy", "logic"]),
    ("Science", "science_en", ["science", "experiment"]),
    ("Mathematics", "math_en", ["math", "algebra"]),
    ("Programming", "programming_en", ["programming", "python"]),
    ("Engineering", "engineering_en", ["engineering", "mechanics"]),
    ("Medicine", "medicine_en", ["medicine", "health"])
]

INDEXES_PER_PAGE = 5

# ===========================
# دوال الفهرس
# ===========================
def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    if not text: return ""
    for word in ["كتاب", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

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

    keyboard.append([InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")])

    text = f"📚 اختر الفهرس الذي تريد استعراضه (عدد الفهارس: {len(indexes)}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "ar"
    await show_index_page(update, context, INDEXES_AR, page, index_type="ar")

async def show_index_en(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "en"
    await show_index_page(update, context, INDEXES_EN, page, index_type="en")

async def navigate_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        parts = query.data.split(":")
        page = int(parts[1])
        index_type = parts[2] if len(parts) > 2 else "ar"
    except Exception:
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

    keywords_list = INDEXES_EN if any(k==index_key for _, k, _ in INDEXES_EN) else INDEXES_AR
    keywords = []
    for name, key, kws in keywords_list:
        if key == index_key:
            keywords = kws
            break

    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية لهذا الفهرس.")
        return

    keywords = [normalize_text(remove_common_words(k)) for k in keywords]

    if index_key in ["novels", "novels_en"]:
        sql_condition = " AND ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])
    else:
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

    await send_books_page(update, context, include_index_home=True)

# ===============================================
# باقي كود البوت (start, handle_start_callbacks, show_top_downloads_week, search_books_with_subscription, run_bot)
# هذا يبقى كما هو
# ===============================================
