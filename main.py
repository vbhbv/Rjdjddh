import os
import hashlib
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultDocument, InlineQueryResultCachedDocument, InputTextMessageContent
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    InlineQueryHandler, PicklePersistence, ContextTypes, filters
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
# تسجيل المستخدم ومعالجة الإحالة (للمستخدمين الجدد فقط)
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if not pool or not update.effective_user:
        return

    user_id = update.effective_user.id
    async with pool.acquire() as conn:
        # 1. الفحص أولاً: هل المستخدم موجود مسبقاً في قاعدة البيانات؟
        existing_user = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", user_id)
        
        # 2. إذا كان مستخدماً جديداً كلياً (غير مسجل سابقاً)
        if not existing_user:
            # تسجيله في النظام لأول مرة
            await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)
            
            # معالجة نظام الإحالة والمكافأة (بما أنه مستخدم جديد)
            if context.args and context.args[0].startswith("inv_"):
                try:
                    inviter_id = int(context.args[0].split("_")[1])
                    
                    # التأكد أن الشخص لا يدعو نفسه
                    if inviter_id != user_id:
                        # تفعيل البريميوم للشخص الذي شارك الرابط لمدة أسبوع واحد (7 أيام) تلقائياً
                        await conn.execute("""
                            UPDATE users 
                            SET is_premium = TRUE, 
                                premium_expiry = NOW() + INTERVAL '7 days' 
                            WHERE user_id = $1
                        """, inviter_id)
                        
                        # تصفير حظر الـ 24 ساعة في ذاكرة السيرفر للناشر ليعود للبحث مباشرة
                        if context.application.user_data and inviter_id in context.application.user_data:
                            if "block_until" in context.application.user_data[inviter_id]:
                                context.application.user_data[inviter_id]["block_until"] = None
                        
                        # إرسال رسالة شكر وتبشير للناشر
                        try:
                            await context.bot.send_message(
                                chat_id=inviter_id,
                                text="🎉 **شكرًا لك! لقد انضم مستخدم جديد إلى البوت من خلال رابطك.**\n\n"
                                     "🎁 تم تفعيل **العضوية المميزة (Premium) لحسابك مجاناً لمدة أسبوع كامل!**\n"
                                     "يمكنك الآن الاستمتاع ببحث غير محدود لكافة الكتب والروايات."
                            )
                        except:
                            pass
                except Exception as e:
                    logger.error(f"Error processing referral shortcut: {e}")

# ===============================================
# ميزة البحث المضمن من أي مكان (Inline Mode) - النسخة القاطعة
# ===============================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    inline_query = update.inline_query
    query = inline_query.query.strip()
    user_id = update.effective_user.id
    pool = context.bot_data.get("db_conn")

    if not query or not pool:
        return

    # استدعاء دالات التطبيع المعتمدة في البوت لضمان تطابق دقة البحث الإملائي والكلمات الجانبية
    from search_handler import normalize_query, get_clean_keywords
    norm_q = normalize_query(query)
    keywords = get_clean_keywords(norm_q)
    ts_query = ' & '.join([f"{w}:*" for w in keywords])
    full_pattern = f"%{query}%"

    results = []
    async with pool.acquire() as conn:
        # 1. التحقق من الاشتراك الإجباري بالقناة الداعمة لحماية البوت
        if not await check_subscription(user_id, context.bot):
            results.append(
                InlineQueryResultDocument(
                    id="sub_required",
                    title="⚠️ يجب الاشتراك في القناة أولاً لاستخدام البحث المضمن!",
                    description=f"انقر هنا للاشتراك في {CHANNEL_USERNAME}",
                    document_url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}",
                    mime_type="text/html",
                    input_message_content=InputTextMessageContent(
                        f"🚫 **عذراً، يجب عليك الاشتراك أولاً في قناة البوت الرسمية {CHANNEL_USERNAME}** لتتمكن من استخدام ميزة البحث الفوري وتحميل الكتب من أي مكان!"
                    )
                )
            )
            await inline_query.answer(results, cache_time=5)
            return

        try:
            # استعلام جلب البيانات الذكي والسريع
            sql = """
            SELECT file_id, file_name,
                   ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
                   similarity(file_name, $2) AS sim
            FROM books
            WHERE 
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
                OR file_name ILIKE $3
                OR file_name % $2
            ORDER BY 
                (file_name ILIKE $3) DESC, 
                rank DESC, 
                sim DESC
            LIMIT 10;
            """
            
            rows = await conn.fetch(sql, ts_query, norm_q, full_pattern)
            
            for i, row in enumerate(rows):
                # الحل القاطع: استخدام الكائن المخصص والمثالي للملفات المرفوعة مسبقاً (Cached Document)
                results.append(
                    InlineQueryResultCachedDocument(
                        id=f"inline_bk_{i}_{hashlib.md5(row['file_id'].encode()).hexdigest()[:8]}",
                        title=row['file_name'],
                        file_id=row['file_id'], # تمرير معرف تليجرام الأصلي والآمن دون روابط
                        caption=f"📖 **{row['file_name']}**\n\nتم التحميل بواسطة: @boooksfree1bot",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                        ])
                    )
                )

        except Exception as e:
            logger.error(f"Inline Database Search Error: {e}")

    # إرسال قائمة النتائج الفورية مباشرة لتعمل فوق صندوق الكتابة بسلاسة
    await inline_query.answer(results, cache_time=2)

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
            "للتفعيل, يرجى التواصل معنا عبر المعرف أدناه:\n"
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
    
    # تسجيل معالج ميزة البحث المضمن (Inline Mode) للعمل من أي جروب أو شات كلياً
    app.add_handler(InlineQueryHandler(inline_search_books))

    register_admin_handlers(app, start)
    app.run_polling()

if __name__ == "__main__":
    run_bot()
