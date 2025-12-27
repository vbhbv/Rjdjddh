import os
import asyncpg
import logging
import hashlib
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

# استيراد الدوال من ملفاتك الأخرى
from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks
from index_handler import show_index, search_by_index, navigate_index_pages

# ===============================================
# إعدادات اللوج
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# قاعدة البيانات
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL is missing!")
            return

        conn = await asyncpg.connect(db_url)
        
        # التأكد من وجود الجداول اللازمة لعمل العداد والفهرس
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS downloads (
            id SERIAL PRIMARY KEY,
            book_id INT REFERENCES books(id),
            user_id BIGINT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        );
        """)
        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")

async def close_db(app: Application):
    conn = app.bot_data.get("db_conn")
    if conn:
        await conn.close()
        logger.info("✅ Database connection closed.")

# ===============================================
# نظام التحقق والاشتراك
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ===============================================
# معالجة ضغطات الأزرار (Callback)
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = context.bot_data.get("db_conn")

    # 1. التحقق من الاشتراك
    if data == "check_subscription":
        await query.answer()
        if await check_subscription(query.from_user.id, context.bot):
            await start(update, context)
        else:
            await query.message.edit_text("⚠️ يجب الانضمام للقناة أولاً ثم الضغط على تحقق.")

    # 2. الفهرس الرئيسي (العربي والإنجليزي)
    elif data in ["show_index", "home_index"]:
        await show_index(update, context) # تستدعي دالة الفهرس العربي
    
    elif data == "show_index_en":
        from index_handler import show_index_en
        await show_index_en(update, context)

    # 3. معالجة الفهرس الداخلي (التصنيفات) - متوافق مع index_handler
    elif data.startswith("index:"):
        await search_by_index(update, context)

    # 4. الملاحة بين صفحات الفهارس
    elif data.startswith("index_page:"):
        await navigate_index_pages(update, context)

    # 5. تسجيل عدد التحميلات وإرسال الملف
    elif data.startswith("file:"):
        await query.answer()
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")

        if file_id and conn:
            try:
                # تسجيل فوري في جدول التنزيلات ليعمل العداد الأسبوعي
                await conn.execute("""
                    INSERT INTO downloads (book_id, user_id)
                    SELECT id, $1 FROM books WHERE file_id = $2 LIMIT 1
                """, query.from_user.id, file_id)
                logger.info(f"📊 Registered download for user {query.from_user.id}")
            except Exception as e:
                logger.error(f"❌ Stats error: {e}")
        
        # استدعاء دالة الإرسال الأصلية من search_handler
        await handle_callbacks(update, context)

    # 6. قائمة الأكثر تحميلاً
    elif data == "top_downloads_week":
        await query.answer()
        await show_top_downloads_week(update, context)

    # 7. التنقل في نتائج البحث (صفحة تالية/سابقة)
    elif data in ["next_page", "prev_page"]:
        await handle_callbacks(update, context)

# ===============================================
# أمر /start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = context.bot_data.get("db_conn")
    
    if conn:
        await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)

    keyboard_main = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 الفهرس العربي", callback_data="show_index"),
         InlineKeyboardButton("📚 English Index", callback_data="show_index_en")],
        [InlineKeyboardButton("🔥 الأكثر تحميلاً هذا الأسبوع", callback_data="top_downloads_week")],
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")]
    ])

    if not await check_subscription(user_id, context.bot):
        keyboard_sub = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ انضم للقناة الآن", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        text = "🌿 أهلًا بك! يرجى الاشتراك في القناة أولاً لتتمكن من استخدام البوت."
        if update.message: await update.message.reply_text(text, reply_markup=keyboard_sub)
        else: await update.callback_query.message.edit_text(text, reply_markup=keyboard_sub)
        return

    text = "👋 **مرحباً بك في مكتبة الكتب المجانية**\n\nأرسل اسم الكتاب الذي تبحث عنه أو تصفح الأقسام من خلال الفهرس."
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard_main, parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=keyboard_main, parse_mode="Markdown")

# ===============================================
# عداد التحميلات الأسبوعي
# ===============================================
async def show_top_downloads_week(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if not conn: return

    one_week_ago = datetime.now() - timedelta(days=7)
    rows = await conn.fetch("""
        SELECT b.file_id, b.file_name, COUNT(d.book_id) AS total
        FROM downloads d
        JOIN books b ON b.id = d.book_id
        WHERE d.downloaded_at >= $1
        GROUP BY b.file_id, b.file_name
        ORDER BY total DESC LIMIT 10;
    """, one_week_ago)

    if not rows:
        await update.callback_query.message.edit_text("⚠️ لا توجد سجلات تحميل لهذا الأسبوع.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="home_index")]]))
        return

    keyboard = []
    for r in rows:
        # تشفير الـ file_id ليتوافق مع نظام أزرار البحث (MD5)
        key = hashlib.md5(r['file_id'].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = r['file_id']
        
        display_name = (r['file_name'][:40] + "..") if len(r['file_name']) > 40 else r['file_name']
        keyboard.append([InlineKeyboardButton(f"📖 {display_name} ({r['total']})", callback_data=f"file:{key}")])

    keyboard.append([InlineKeyboardButton("🔙 عودة للقائمة الرئيسية", callback_data="home_index")])
    await update.callback_query.message.edit_text("🔥 **الكتب الأكثر تحميلاً خلال آخر 7 أيام:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ===============================================
# معالجة رسائل البحث النصية
# ===============================================
async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text(f"🚫 اشترك أولاً في {CHANNEL_USERNAME} لتتمكن من البحث.")
        return
    await search_books(update, context)

# ===============================================
# تشغيل البوت
# ===============================================
def run():
    token = os.getenv("BOT_TOKEN")
    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # معالجة ملفات القنوات (الأرشفة)
    from main import handle_pdf
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run()
