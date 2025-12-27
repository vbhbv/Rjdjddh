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
# إعداد قاعدة البيانات
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except Exception as e:
            logger.warning(f"⚠️ Extensions warning: {e}")

        # الجداول الأساسية
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            file_id TEXT UNIQUE,
            file_name TEXT,
            name_normalized TEXT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS downloads (
            book_id INT REFERENCES books(id),
            user_id BIGINT,
            downloaded_at TIMESTAMP DEFAULT NOW()
        );
        """)
        app_context.bot_data["db_conn"] = conn
        logger.info("✅ Database connected.")
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
        if not conn: return
        try:
            await conn.execute("""
            INSERT INTO books(file_id, file_name)
            VALUES($1, $2) ON CONFLICT (file_id) DO UPDATE SET file_name = EXCLUDED.file_name;
            """, document.file_id, document.file_name)
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
# التعامل مع أزرار callback
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = context.bot_data.get("db_conn")

    # 1. معالجة الاشتراك
    if data == "check_subscription":
        await query.answer()
        if await check_subscription(query.from_user.id, context.bot):
            await start(update, context)
        else:
            await query.message.edit_text("😊 لم نتمكن من التحقق من اشتراكك بعد. انضم للقناة أولاً.")

    # 2. معالجة الفهارس (استدعاء مباشر للدوال المستوردة)
    elif data in ["show_index", "home_index"]:
        await query.answer()
        await show_index(update, context)
    
    elif data == "show_index_en":
        await query.answer()
        from index_handler import show_index_en
        await show_index_en(update, context)
    
    elif data.startswith("index:"):
        await query.answer()
        await search_by_index(update, context)
    
    elif data.startswith("index_page:"):
        await query.answer()
        await navigate_index_pages(update, context)

    # 3. معالجة التحميلات (يجب أن تتوافق مع hashlib المستخدم في search_handler)
    elif data.startswith("file:"):
        await query.answer()
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        
        if file_id and conn:
            # تسجيل التحميل في قاعدة البيانات
            await conn.execute("""
                INSERT INTO downloads (book_id, user_id)
                SELECT id, $1 FROM books WHERE file_id = $2 LIMIT 1
            """, query.from_user.id, file_id)
        
        # تمرير الطلب لـ search_handler لإرسال الملف الفعلي
        await handle_callbacks(update, context)

    # 4. الأكثر تحميلاً والتنقل
    elif data == "top_downloads_week":
        await query.answer()
        await show_top_downloads_week(update, context)
        
    elif data in ["next_page", "prev_page", "search_similar"]:
        await query.answer()
        await handle_callbacks(update, context)

# ===============================================
# رسالة البدء /start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = context.bot_data.get("db_conn")
    if conn:
        await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)

    keyboard_main = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")],
        [InlineKeyboardButton("📚 عرض الفهرس العربي", callback_data="show_index")],
        [InlineKeyboardButton("📚 عرض الفهرس الإنجليزي", callback_data="show_index_en")],
        [InlineKeyboardButton("🔥 أكثر الكتب تحميلاً", callback_data="top_downloads_week")]
    ])

    instructions = (
        "👋 **أهلاً بك في المكتبة الرقمية**\n\n"
        "📖 أرسل اسم الكتاب للبحث عنه، أو تصفح الفهارس أدناه."
    )

    if not await check_subscription(user_id, context.bot):
        keyboard_sub = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        text = "🌿 أهلًا بك! يرجى الانضمام إلى قناتنا أولاً للمتابعة."
        if update.message: await update.message.reply_text(text, reply_markup=keyboard_sub)
        else: await update.callback_query.message.edit_text(text, reply_markup=keyboard_sub)
        return

    if update.message:
        await update.message.reply_text(instructions, reply_markup=keyboard_main, parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(instructions, reply_markup=keyboard_main, parse_mode="Markdown")

# ===============================================
# أكثر الكتب تحميلاً (إصلاح نظام المفاتيح)
# ===============================================
async def show_top_downloads_week(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if not conn: return

    one_week_ago = datetime.now() - timedelta(days=7)
    rows = await conn.fetch("""
        SELECT b.file_id, b.file_name, COUNT(d.book_id) AS d_count
        FROM downloads d JOIN books b ON b.id = d.book_id
        WHERE d.downloaded_at >= $1 GROUP BY b.file_id, b.file_name
        ORDER BY d_count DESC LIMIT 10;
    """, one_week_ago)

    if not rows:
        await update.callback_query.message.edit_text("⚠️ لا توجد تنزيلات هذا الأسبوع.")
        return

    keyboard = []
    for r in rows:
        # توليد المفتاح المتوافق مع search_handler
        key = hashlib.md5(r['file_id'].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = r['file_id']
        
        display_name = r["file_name"][:45] + "..." if len(r["file_name"]) > 45 else r["file_name"]
        keyboard.append([InlineKeyboardButton(f"📖 {display_name} ({r['d_count']})", callback_data=f"file:{key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 عودة", callback_data="home_index")])
    await update.callback_query.message.edit_text("🔥 **أكثر الكتب تحميلاً:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text(f"🚫 اشترك في {CHANNEL_USERNAME} أولاً.")
        return
    await search_books(update, context)

def run_bot():
    app = Application.builder().token(os.getenv("BOT_TOKEN")).post_init(init_db).post_shutdown(close_db).persistence(PicklePersistence(filepath="bot_data.pickle")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    
    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
