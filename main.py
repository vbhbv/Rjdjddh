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
from search_handler import search_books, handle_callbacks  # البحث العادي
from index_handler import show_index, search_by_index, navigate_index_pages  # الفهرس العربي

# ===============================================
# إعداد اللوج
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# إعداد قاعدة البيانات (المطورة بالفهارس)
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            logger.info("✅ Extensions (unaccent, pg_trgm) ensured.")
        except Exception as e:
            logger.warning(f"⚠️ Could not create extensions: {e}")

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

        # جدول عداد التنزيلات
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
# التعامل مع أزرار callback
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
                [InlineKeyboardButton("📚 عرض الفهرس العربي", callback_data="show_index")],
                [InlineKeyboardButton("📚 عرض الفهرس الإنجليزي", callback_data="show_index_en")],
                [InlineKeyboardButton("🔥 أكثر الكتب تحميلاً", callback_data="top_downloads_week")]
            ])
            instructions = (
                "👋 **أهلاً بك في المكتبة الرقمية**\n\n"
                "📖 **تعليمات الاستخدام:**\n"
                "1️⃣ أرسل اسم الكتاب أو اسم المؤلف مباشرة للبحث.\n"
                "2️⃣ يفضل كتابة كلمات محددة (مثال: فن اللامبالاة بدلاً من كتاب فن).\n"
                "3️⃣ يمكنك استخدام الفهارس لتصفح الكتب حسب التصنيف.\n\n"
                "⚖️ **حقوق الملكية الفكرية:**\n"
                "إدارة المكتبة تحترم حقوق الملكية الفكرية للمؤلفين ودور النشر. "
                "إذا كنت صاحب حق وترغب في إزالة محتوى معين، يرجى التواصل معنا عبر الزر أدناه."
            )
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=instructions,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.message.edit_text(
                "😊 لم نتمكن من التحقق من اشتراكك بعد.\n\n"
                "بعد الانضمام إلى القناة، اضغط على «تحقق من الاشتراك» للمتابعة."
            )

    elif data in ["show_index", "home_index"]:
        await show_index(update, context)
    elif data == "show_index_en":
        from index_handler import show_index_en
        await show_index_en(update, context)
    elif data == "top_downloads_week":
        await show_top_downloads_week(update, context)
    elif data.startswith("index:"):
        await search_by_index(update, context)
    elif data.startswith("index_page:"):
        await navigate_index_pages(update, context)
    elif data.startswith("file:") or data in ["next_page", "prev_page", "search_similar"]:
        await handle_callbacks(update, context)

# ===============================================
# رسالة البدء /start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await register_user(update, context)
    channel_username = CHANNEL_USERNAME.lstrip('@')

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{channel_username}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            "🌿 أهلًا بك!\n\n"
            "للوصول إلى مكتبة الكتب الكاملة والاستفادة من البحث الذكي، يرجى الانضمام إلى قناتنا الرسمية.",
            reply_markup=keyboard
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/HMDALataar")],
        [InlineKeyboardButton("📚 عرض الفهرس العربي", callback_data="show_index")],
        [InlineKeyboardButton("📚 عرض الفهرس الإنجليزي", callback_data="show_index_en")],
        [InlineKeyboardButton("🔥 أكثر الكتب تحميلاً", callback_data="top_downloads_week")]
    ])
    
    instructions = (
        "👋 **أهلاً بك في المكتبة الرقمية**\n\n"
        "📖 **تعليمات الاستخدام:**\n"
        "1️⃣ أرسل اسم الكتاب أو اسم المؤلف مباشرة للبحث.\n"
        "2️⃣ يفضل كتابة كلمات محددة (مثال: فن اللامبالاة بدلاً من كتاب فن).\n"
        "3️⃣ يمكنك استخدام الفهارس لتصفح الكتب حسب التصنيف.\n\n"
        "⚖️ **حقوق الملكية الفكرية:**\n"
        "إدارة المكتبة تحترم حقوق الملكية الفكرية للمؤلفين ودور النشر. "
        "إذا كنت صاحب حق وترغب في إزالة محتوى معين، يرجى التواصل معنا عبر الزر أدناه."
    )
    
    await update.message.reply_text(
        instructions,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

# ===============================================
# أكثر الكتب تحميلاً خلال الأسبوع
# ===============================================
async def show_top_downloads_week(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.callback_query.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    one_week_ago = datetime.now() - timedelta(days=7)
    sql = """
    SELECT b.file_id, b.file_name, COUNT(d.book_id) AS downloads_count
    FROM downloads d
    JOIN books b ON b.id = d.book_id
    WHERE d.downloaded_at >= $1
    GROUP BY b.id
    ORDER BY downloads_count DESC
    LIMIT 10;
    """
    rows = await conn.fetch(sql, one_week_ago)

    if not rows:
        await update.callback_query.message.reply_text("⚠️ لا توجد بيانات تحميل للأسبوع الحالي.")
        return

    text = "🔥 **أكثر الكتب تحميلاً هذا الأسبوع:**\n\n"
    keyboard = []
    for r in rows:
        key = r["file_id"]
        display_name = (r["file_name"][:50] + "..") if len(r["file_name"]) > 50 else r["file_name"]
        keyboard.append([InlineKeyboardButton(f"📖 {display_name} ({r['downloads_count']})", callback_data=f"file:{key}")])

    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ===============================================
# تعديل: التحقق من الاشتراك قبل البحث
# ===============================================
async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text(
            "🚫 لا يمكنك البحث قبل الاشتراك في القناة.\n"
            f"يرجى الانضمام إلى {CHANNEL_USERNAME} أولاً."
        )
        return
    await search_books(update, context)

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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
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
