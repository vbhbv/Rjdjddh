import os
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

from admin_panel import register_admin_handlers
from search_handler import search_books, handle_callbacks

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

        pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )

        async with pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                file_name TEXT,
                name_normalized TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fts_books
            ON books USING gin (to_tsvector('arabic', file_name));
            """)

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trgm_books
            ON books USING gin (file_name gin_trgm_ops);
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW(),
                is_premium BOOLEAN DEFAULT FALSE,
                premium_expiry TIMESTAMP
            );
            """)
            
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_expiry TIMESTAMP;")

        app_context.bot_data["db_conn"] = pool
        logger.info("✅ Database pool ready with premium columns.")

    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()
        logger.info("✅ Database pool closed.")

# ===============================================
# استقبال ملفات PDF
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if (
        update.channel_post
        and update.channel_post.document
        and update.channel_post.document.mime_type == "application/pdf"
    ):
        pool = context.bot_data.get("db_conn")
        if not pool:
            return

        document = update.channel_post.document
        async with pool.acquire() as conn:
            await conn.execute("""
            INSERT INTO books(file_id, file_name)
            VALUES($1, $2)
            ON CONFLICT (file_id) DO UPDATE
            SET file_name = EXCLUDED.file_name;
            """, document.file_id, document.file_name)

# ===============================================
# الاشتراك الإجباري
# ===============================================
CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# ===============================================
# تسجيل المستخدم
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if pool and update.effective_user:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                update.effective_user.id
            )

# ===============================================
# callbacks
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # معالجة طلب الفهرس
    if query.data == "show_index":
        from indexes import show_index_menu
        await show_index_menu(update, context)
        return
    
    # معالجة اختيار قسم من الفهرس
    elif query.data.startswith("idx:"):
        from indexes import handle_index_selection
        await handle_index_selection(update, context)
        return

    elif query.data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            # الكيبورد الجديد يحتوي على الفهرس والاشتراك المميز
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗂 فهرس المكتبة الذكي", callback_data="show_index")],
                [InlineKeyboardButton("⭐ تفعيل البحث اللامحدود (5$)", callback_data="buy_premium")]
            ])
            await query.message.edit_text(
                (
                    "🌟 *مرحبًا بك في بوت مكتبة الكتب*\n\n"
                    "📚 مكتبة رقمية مجانية تضم أكثر من مليون كتاب\n"
                    "🔎 يمكنك البحث بسهولة بكتابة اسم الكتاب أو جزء منه\n\n"
                    "🧭 *تعليمات البحث الصحيحة:*\n"
                    "✔️ اكتب اسم الكتاب فقط\n"
                    "✔️ أو جزء واضح من العنوان\n\n"
                    "❌ أمثلة بحث غير صحيحة:\n"
                    "✖️ كلمات عشوائية\n"
                    "✖️ جمل طويلة أو أوصاف\n\n"
                    "⚖️ *تنويه قانوني:*\n"
                    "إدارة وفريق بوت مكتبة الكتب يحترمون حقوق الملكية الفكرية احترامًا تامًا.\n"
                    "جميع الملفات المفهرسة تم رفعها من قبل مستخدمي تيليجرام أو قنوات عامة.\n"
                    "في حال وجود أي محتوى مخالف لحقوق النشر، يرجى التواصل معنا وسيتم حذفه فورًا.\n\n"
                    "📩 باستخدامك للبوت فأنت تقرّ بذلك.\n\n"
                    "📖 نتمنى لك قراءة ممتعة!"
                ),
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            await query.message.reply_text(
                f"❌ لم يتم العثور على اشتراكك في {CHANNEL_USERNAME}\n"
                "🔔 يرجى الاشتراك أولاً ثم إعادة المحاولة"
            )
        return

    elif query.data == "buy_premium":
        text = (
            "⭐ **العضوية المميزة (Premium)**\n\n"
            "استمتع ببحث غير محدود طوال اليوم دون قيود!\n\n"
            "💳 **السعر:** 5 دولارات شهرياً.\n"
            "للتفعيل، يرجى التواصل معنا عبر المعرف أدناه:\n"
            "📩 @HMDALataar"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    await handle_callbacks(update, context)

# ===============================================
# /start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            (
                "👋 مرحبًا بك في *بوت مكتبة الكتب*\n\n"
                "📚 أكبر مكتبة رقمية مجانية على تيليجرام\n"
                "📖 يحتوي البوت على أكثر من *مليون كتاب* في مختلف المجالات\n\n"
                "🔐 لاستخدام البوت يجب الانضمام في القناة الداعمة علمًا انه مجاني\n"
                "👇 اشترك أولاً ثم اضغط على (تحقق من الاشتراك)"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # زر الفهرس كزر Armageddon في المقدمة
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗂 فهرس المكتبة الذكي", callback_data="show_index")],
        [InlineKeyboardButton("⭐ تفعيل البحث اللامحدود (5$)", callback_data="buy_premium")]
    ])
    await update.message.reply_text(
        (
            "🌟 *مرحبًا بك في بوت مكتبة الكتب*\n\n"
            "📚 مكتبة رقمية مجانية تضم أكثر من مليون كتاب\n"
            "🔎 يمكنك البحث بسهولة بكتابة اسم الكتاب أو جزء منه\n\n"
            "🧭 *تعليمات البحث الصحيحة:*\n"
            "✔️ اكتب اسم الكتاب فقط\n"
            "✔️ أو جزء واضح من العنوان\n\n"
            "❌ أمثلة بحث غير صحيحة:\n"
            "✖️ كلمات عشوائية\n"
            "✖️ جمل طويلة أو أوصاف\n\n"
            "⚖️ *تنويه قانوني:*\n"
            "إدارة وفريق بوت مكتبة الكتب يحترمون حقوق الملكية الفكرية احترامًا تامًا.\n"
            "جميع الملفات المفهرسة تم رفعها من قبل مستخدمي تيليجرام أو قنوات عامة.\n"
            "في حال وجود أي محتوى مخالف لحقوق النشر، يرجى التواصل معنا وسيتم حذفه فورًا.\n\n"
            "📩 باستخدامك للبوت فأنت تقرّ بذلك.\n\n"
            "📖 نتمنى لك قراءة ممتعة!"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ===============================================
# البحث
# ===============================================
async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        await update.message.reply_text(
            f"🚫 لاستخدام البوت يجب الاشتراك في {CHANNEL_USERNAME} أولاً"
        )
        return
    await search_books(update, context)

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("🚨 BOT_TOKEN not found.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
