import os
import re
import asyncpg
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    ChatMemberHandler, PicklePersistence, ContextTypes, filters
)

# 🛠 تم تصحيح هذا السطر وإلغاء المتغير القديم المتسبب في الـ ImportError
from admin_panel import register_admin_handlers  
from search_handler import search_books, handle_callbacks
# استيراد دوال الرادار من الملف المستقل لضمان الربط الكامل
from radar_handler import (
    start_radar_flow, process_radar_category, 
    process_radar_difficulty, execute_radar_search
)
# 🇬🇧 استيراد دوال الفهرس الإنكليزي الـ 50 قسماً لربطه بالمنظومة الرئيسية
from english_index_handler import (
    show_english_index_menu, handle_english_index_selection
)
# ✍️ استيراد دالة فهرس أشهر أعلام الفكر والأدب الجديد لربط الأزرار والـ Callbacks تلقائياً
from authors_index import (
    show_index_menu as show_authors_index_menu, handle_index_selection as handle_authors_index_selection
)

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
                premium_expiry TIMESTAMP,
                search_credits INT DEFAULT 0
            );
            """)

            await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;
            """)

            await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS premium_expiry TIMESTAMP;
            """)

            await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS search_credits INT DEFAULT 0;
            """)

            # إضافة جدول إحصائيات التحميل الأسبوعي لحساب الأكثر تحميلاً (5 مرات فما فوق)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS download_stats (
                id SERIAL PRIMARY KEY,
                file_id TEXT,
                downloaded_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_download_stats_date 
            ON download_stats (downloaded_at);
            """)

        app_context.bot_data["db_conn"] = pool
        logger.info("✅ Database pool ready with premium, credits and download stats columns.")

    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

# ===============================================
# إغلاق قاعدة البيانات
# ===============================================
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
# الاشتراك الإجباري الديناميكي والمستمر عبر الـ Persistence
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        from __main__ import app
        channel_id = app.bot_data.get("required_channel_id")
    except:
        channel_id = None

    if channel_id is None: 
        return True
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

async def get_channel_invite_link(bot) -> str:
    try:
        from __main__ import app
        channel_id = app.bot_data.get("required_channel_id")
    except:
        channel_id = None

    if channel_id is None:
        return "https://t.me/"
    try:
        chat = await bot.get_chat(channel_id)
        if chat.username:
            return f"https://t.me/{chat.username}"
        elif chat.invite_link:
            return chat.invite_link
    except: pass
    return "https://t.me/"

# ===============================================
# تسجيل المستخدم ومعالجة الإحالة (تم إصلاحها بشكل شامل)
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):

    pool = context.bot_data.get("db_conn")

    if not pool or not update.effective_user:
        return

    user_id = update.effective_user.id

    async with pool.acquire() as conn:

        existing_user = await conn.fetchval(
            "SELECT user_id FROM users WHERE user_id = $1",
            user_id
        )

        # لا تمنح المكافأة إلا إذا كان المستخدم جديداً كلياً في النظام
        if not existing_user:

            await conn.execute(
                "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                user_id
            )

            # استخراج كود الإحالة الآمن عبر فحص دقيق للـ args أو النص الخام للرسالة
            inviter_id = None
            if context.args and context.args[0].startswith("inv_"):
                try:
                    inviter_id = int(context.args[0].split("_")[1])
                except: pass
            elif update.message and update.message.text:
                match = re.search(r'/start inv_(\d+)', update.message.text)
                if match:
                    try:
                        inviter_id = int(match.group(1))
                    except: pass

            # إذا عثرنا على أيدي الشخص الداعي وهو لا يساوي أيدي المستخدم الجديد
            if inviter_id and inviter_id != user_id:
                try:
                    # إضافة 10 محاولات في قاعدة البيانات للشخص صاحب الرابط
                    await conn.execute("""
                        UPDATE users
                        SET search_credits = search_credits + 10
                        WHERE user_id = $1
                    """, inviter_id)

                    # فك قفل الحظر المؤقت بأسلوب القاموس الآمن للحماية من خطأ الـ MappingProxy
                    if context.application.user_data:
                        user_data_dict = dict(context.application.user_data)
                        if inviter_id in user_data_dict and "block_until" in context.application.user_data[inviter_id]:
                            context.application.user_data[inviter_id]["block_until"] = None

                    # إرسال إشعار فوري للشخص القديم يبلغه بنجاح الإضافة
                    try:
                        await context.bot.send_message(
                            chat_id=inviter_id,
                            text=(
                                "🎉 **شكرًا لك! لقد انضم مستخدم جديد إلى البوت من خلال رابطك.**\n\n"
                                "🎁 تم إضافة **10 محاولات بحث إضافية** إلى حسابك مجاناً!\n"
                                "يمكنك الآن الاستمرار في تصفح وتحميل الكتب والروايات."
                            ),
                            parse_mode="Markdown"
                        )
                    except:
                        pass

                except Exception as e:
                    logger.error(f"Error processing referral inside DB update: {e}")

# ===============================================
# الترحيب المضمون عند إضافة البوت للمجموعة
# ===============================================
async def welcome_bot_in_group(update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member or update.my_chat_member
    if not chat_member:
        return

    if chat_member.chat.type not in ("group", "supergroup"):
        return

    if (
        chat_member.new_chat_member.user.id == context.bot.id
        and chat_member.new_chat_member.status in ("member", "administrator")
    ):

        group_name = chat_member.chat.title or "المجموعة"

        welcome_text = (
            f"🎉 **أهلاً بكم في مجموعة ( {group_name} )!**\n\n"
            f"🤖 تم تفعيل بوت مكتبة الكتب داخل المجموعة بنجاح.\n\n"
            f"📌 **طريقة الاستخدام:**\n"
            f"اكتب الأمر `/search` ثم اسم الكتاب مباشرة.\n\n"
            f"📖 **مثال صحيح:**\n"
            f"`/search مقدمة ابن خلدون`\n\n"
            f"🚀 استمتعوا بالبحث والقراءة الحرة داخل المجموعة!"
        )

        try:
            await context.bot.send_message(
                chat_id=chat_member.chat.id,
                text=welcome_text,
                parse_mode="Markdown"
            )
            logger.info(f"✅ Sent welcome message to group: {group_name} ({chat_member.chat.id})")
        except Exception as e:
            logger.error(f"❌ Error sending group welcome to {chat_member.chat.id}: {e}")

# ===============================================
# callbacks
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    
    # 🔒 فحص الحظر الفوري والآمن عند ضغط أي زر
    u_id = query.from_user.id
    if context.application.user_data:
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            await query.answer("❌ أنت محظور من استخدام أزرار هذا البوت.", show_alert=True)
            return

    await query.answer()

    if query.data == "show_index":
        from indexes import show_index_menu
        await show_index_menu(update, context)
        return

    elif query.data.startswith("idx:"):
        from indexes import handle_index_selection
        await handle_index_selection(update, context)
        return

    elif query.data == "show_authors_index":
        await show_authors_index_menu(update, context)
        return

    elif query.data.startswith("idx:"):
        # توجيه الكولباك لمعالج الـ 50 مؤلفاً المشهورين
        await handle_authors_index_selection(update, context)
        return

    elif query.data == "show_english_index":
        await show_english_index_menu(update, context)
        return

    elif query.data.startswith("eng_idx:"):
        await handle_english_index_selection(update, context)
        return

    elif query.data == "show_trending":
        from search_handler import send_trending_books
        await send_trending_books(update, context)
        return

    elif query.data == "radar_menu":
        await start_radar_flow(query)
        return

    elif query.data.startswith("rad_cat:"):
        await process_radar_category(query, context)
        return

    elif query.data.startswith("rad_diff:"):
        await process_radar_difficulty(query, context)
        return

    elif query.data.startswith("rad_size:"):
        await execute_radar_search(query, context)
        return

    elif query.data == "show_advertising_info":
        adv_text = (
            "📢 **الإعلانات ودعم استمرار البوت**\n"
            "--------------------------------------\n"
            "مستخدمينا الأعزاء، إن الحفاظ على هذا البوت وتطويره ليستمر في خدمتكم كأكبر مكتبة رقمية مجانية يتطلب تكاليف تشغيلية مرتفعة لتغطية مصاريف السيرفرات وقواعد البيانات الضخمة التي تحتضن أكثر من 1.5 مليون كتاب ومصدر.\n\n"
            "ومن أجل ضمان استمرارية هذه الخدمة وتغطية هذه التكاليف، فتحنا باب الإعلان وفق شروط صارمة تناسب طابع هذه المكتبة؛ حيث **نروج للقنوات الثقافية والعلمية والتعليمية فقط**، نصرةً للمحتوى الهادف وحفاظاً على بيئة معرفية تليق بجمهورنا من القراء والباحثين.\n\n"
            "📬 **للاستفسار وحجز المساحات الإعلانية:**\n"
            "التواصل المباشر مع إدارة البوت ومعرفة التفاصيل، يرجى مراسلتنا عبر المعرف التالي:\n"
            "📩 @UUUULU"
        )
        await query.message.reply_text(text=adv_text, parse_mode="Markdown")
        return

    elif query.data == "back_to_main" or query.data == "check_subscription":

        if await check_subscription(query.from_user.id, context.bot):

            # 📋 ترتيب رأسي منظم للأزرار مع إضافة زر أشهر أعلام الفكر والأدب
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
                [InlineKeyboardButton("✍️ أشهر أعلام الفكر والأدب", callback_data="show_authors_index")],
                [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
                [InlineKeyboardButton("💡 مستشارك القرائي", callback_data="radar_menu")],
                [InlineKeyboardButton("🔥 الأكثر تحميلاً هذا الأسبوع", callback_data="show_trending")],
                [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
                [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
            ])

            await query.message.edit_text(
                text=(
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
            target_link = await get_channel_invite_link(context.bot)
            await query.message.reply_text(
                text=f"❌ لم يتم العثور على اشتراكك في القناة المطلوبة.\n🔔 يرجى الانضمام هنا أولاً ثم إعادة المحاولة:\n{target_link}"
            )
        return

    elif query.data == "buy_premium":
        text = (
            "⭐ **باقات العضوية المميزة (Premium)**\n\n"
            "افتح ميزة البحث اللامحدود والتحميل السريع بدون قيود أو فترات انتظار:\n\n"
            "📅 **الخطط المتاحة:**\n"
            "• الاشتراك الشهري: **5$** شهرياً.\n"
            "• الاشتراك نصف السنوي: **25$** (توفير بقيمة شهر).\n"
            "• الاشتراك السنوي الكلي: **45$** (العرض الأقوى).\n\n"
            "💳 **طريقة التفعيل:**\n"
            "يرجى التواصل المباشر معنا عبر المعرف أدناه لإرسال الأيدي وإتمام التفعيل الفوري:\n"
            "📩 @UUUULU"
        )
        await query.message.reply_text(text=text, parse_mode="Markdown")
        return

    await handle_callbacks(update, context)

# ===============================================
# /start
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):

    # 🔒 منع المستخدم المحظور من تشغيل البوت عبر /start نهائياً
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            return

    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        target_link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك في القناة", url=target_link)],
            [InlineKeyboardButton("🔍 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text=(
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

    # 📋 ترتيب رأسي منظم للأزرار عند استخدام أمر /start مع إضافة الزر الجديد
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
        [InlineKeyboardButton("✍️ أشهر أعلام الفكر والأدب", callback_data="show_authors_index")],
        [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
        [InlineKeyboardButton("💡 مستشارك القرائي", callback_data="radar_menu")],
        [InlineKeyboardButton("🔥 الأكثر تحميلاً هذا الأسبوع", callback_data="show_trending")],
        [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
        [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
    ])
    
    await update.message.reply_text(
        text=(
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
            "في حال وجود أي محتوى مخالف لحقوق النشر, يرجى التواصل معنا وسيتم حذفه فورًا.\n\n"
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

    # 🔒 فحص الحظر ومنع البحث النصي تماماً
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            return

    if not await check_subscription(update.effective_user.id, context.bot):
        target_link = await get_channel_invite_link(context.bot)
        # متبقي الكود كما هو منقطع في رسالتك الأساسية...
