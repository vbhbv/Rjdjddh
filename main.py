import os
import re
import asyncpg
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    ChatMemberHandler, PicklePersistence, ContextTypes, filters
)

# 🛠 استيراد الدوال من الملفات الملحقة ببرمجية البوت
from admin_panel import register_admin_handlers  
from search_handler import search_books, handle_callbacks
# استيراد دوال الرادار من الملف المستقل لضمان الربط الكامل
from radar_handler import (
    start_radar_flow, process_radar_category, 
    process_radar_difficulty, execute_radar_search
)
# 🇬🇧 استيراد دوال الفهرس الإنكليزي لربطه بالمنظومة الرئيسية
from english_index_handler import (
    show_english_index_menu, handle_english_index_selection
)

# 📸 استيراد المحرك الاحترافي الخاص بالبحث عن طريق غلاف الكتاب
from cover_search import telegram_photo_handler_pipeline, init_db_pool

# ===============================================
# إعداد اللوج والمراقبة
# ===============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# إعداد وتجهيز قاعدة البيانات (PostgreSQL)
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
        
        # ⚡ تهيئة ربط الـ Pool الخاص بملف البحث عبر الأغلفة ليعمل بكفاءة بالتوازي
        await init_db_pool(pool)
        
        logger.info("✅ Database pool ready with premium, credits and download stats columns.")

    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

# ===============================================
# إغلاق قاعدة البيانات بأمان عند توقف السيرفر
# ===============================================
async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()
        logger.info("✅ Database pool closed.")

# ===============================================
# استقبال ملفات الـ PDF وأرشفتها تلقائياً من القنوات
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
# نظام الاشتراك الإجباري المستقر مع استثناء البريميوم
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        from __main__ import app
        pool = app.bot_data.get("db_conn")
        channel_id = app.bot_data.get("required_channel_id")
    except:
        pool = None
        channel_id = None

    if pool:
        try:
            async with pool.acquire() as conn:
                premium_status = await conn.fetchrow(
                    "SELECT is_premium, premium_expiry FROM users WHERE user_id = $1", 
                    user_id
                )
                if premium_status and premium_status["is_premium"]:
                    expiry = premium_status["premium_expiry"]
                    if expiry is None or expiry > datetime.now():
                        return True  
        except Exception as e:
            logger.error(f"Error checking premium status in subscription bypass: {e}")

    if channel_id is None: 
        return True
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"Error checking chat member status for channel {channel_id}: {e}")
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
# تسجيل المستخدم الجديد وإدارة منظومة الإحالة المكافئة
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

        if not existing_user:
            await conn.execute(
                "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                user_id
            )

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

            if inviter_id and inviter_id != user_id:
                try:
                    await conn.execute("""
                        UPDATE users
                        SET search_credits = search_credits + 10
                        WHERE user_id = $1
                    """, inviter_id)

                    if context.application.user_data:
                        user_data_dict = dict(context.application.user_data)
                        if inviter_id in user_data_dict and "block_until" in context.application.user_data[inviter_id]:
                            context.application.user_data[inviter_id]["block_until"] = None

                    try:
                        await context.bot.send_message(
                            chat_id=inviter_id,
                            text=(
                                "🎉 **شكرًا لك! لقد انضم مستخدم جديد إلى البوت من خلال رابط الدعوة الخاص بك.**\n\n"
                                "🎁 تم إضافة **10 محاولات بحث إضافية** إلى حسابك مجاناً كهدية من الإدارة!\n"
                                "يمكنك الآن الاستمرار في تصفح وتحميل الكتب الروايات."
                            ),
                            parse_mode="Markdown"
                        )
                    except: pass
                except Exception as e:
                    logger.error(f"Error processing referral inside DB update: {e}")

# ===============================================
# الترحيب الآلي عند إضافة البوت للمجموعات والسوبرجروب
# ===============================================
async def welcome_bot_in_group(update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member or update.my_chat_member
    if not chat_member or chat_member.chat.type not in ("group", "supergroup"):
        return

    if (
        chat_member.new_chat_member.user.id == context.bot.id
        and chat_member.new_chat_member.status in ("member", "administrator")
    ):
        group_name = chat_member.chat.title or "المجموعة الثقافية"
        welcome_text = (
            f"🎉 **أهلاً بكم جميعاً في مجموعة ( {group_name} )!**\n\n"
            f"🤖 تم تفعيل بوت مكتبة الكتب الذكي داخل المجموعة بنجاح وتأمين الاتصال بقواعد البيانات.\n\n"
            f"📌 **طريقة الاستخدام السريعة والفعالة للبحث عن الكتب:**\n"
            f"يرجى كتابة الأمر الرمزي التالي `/search` يليه اسم الكتاب المراد قراءته مباشرة.\n\n"
            f"📖 **مثال توضيحي صحيح للبحث:**\n"
            f"`/search مقدمة ابن خلدون`\n\n"
            f"🚀 نتمنى لكم رحلة بحث ممتعة وقراءة حرة ومثمرة داخل المجموعة!"
        )
        try:
            await context.bot.send_message(
                chat_id=chat_member.chat.id,
                text=welcome_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Error sending group welcome to {chat_member.chat.id}: {e}")

# ===============================================
# معالجة الضغط على الأزرار التفاعلية (Callbacks)
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    u_id = query.from_user.id
    
    if context.application.user_data:
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            await query.answer("❌ عذراً، أنت محظور من استخدام أزرار وتفاعلات هذا البوت من قبل الإدارة.", show_alert=True)
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
            "📢 **قسم الإعلانات ودعم استمرار البوت الرقمي**\n"
            "--------------------------------------------------\n"
            "مكتبتنا تعتمد بالكامل على دعمكم الصادق. الحفاظ على السيرفرات الضخمة وتحديثها المستمر يتطلب تكاليف تشغيلية لتظل الخدمة مجانية كلياً للجميع.\n\n"
            "الإعلانات لدينا تخضع لرقابة صارمة، ونحرص على اختيار قنوات ومنصات مفيدة وهادفة تلائم ذائقتكم الثقافية والعلمية.\n\n"
            "📬 **للاستفسار وحجز المساحات الإعلانية:**\n"
            "📩 تواصل مباشرة مع الإدارة: @UUUULU"
        )
        await query.message.reply_text(text=adv_text, parse_mode="Markdown")
        return

    elif query.data == "back_to_main" or query.data == "check_subscription":
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
                [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
                [InlineKeyboardButton("💡 مستشارك القرائي (الرادار)", callback_data="radar_menu")],
                [InlineKeyboardButton("🔥 الأكثر تحميلاً هذا الأسبوع", callback_data="show_trending")],
                [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
                [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
            ])
            await query.message.edit_text(
                text=(
                    "🌟 *مرحبًا بك مجدداً في بوت مكتبة الكتب*\n\n"
                    "📚 أكبر مكتبة رقمية تفاعلية مجانية تضم أكثر من مليون كتاب ورواية ومصدر أكاديمي متاح بين يديك الآن.\n"
                    "🔎 يمكنك البحث بكل سهولة عن أي عنوان تريد من خلال كتابة اسم الكتاب أو جزء منه في رسالة نصية مباشرة.\n\n"
                    "🧭 *تعليمات وإرشادات البحث الصحيحة للحصول على أفضل نتيجة:*\n"
                    "✔️ اكتب اسم الكتاب بدقة وبدون كلمات زائدة.\n"
                    "✔️ أو اكتب جزءاً واضحاً وفريداً من العنوان الأصلي للمؤلف.\n\n"
                    "📖 نتمنى لك رحلة قراءة ماتعة ومثمرة!"
                ),
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            target_link = await get_channel_invite_link(context.bot)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك في القناة هنا", url=target_link)],
                [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
            ])
            try:
                await query.message.reply_text(
                    text=(
                        "🌱 **فضلاً، اشترك في القناة أولاً ليعمل معك البوت!**\n\n"
                        "الاشتراك في القناة مجاني تماماً، وهو الدعم الوحيد الذي يضمن استمرار البوت وتغطية تكاليف السيرفرات الضخمة ليظل متاحاً للجميع."
                    ),
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except: pass
        return

    elif query.data == "buy_premium":
        text = (
            "⭐ **باقات العضوية المميزة والمزايا الحصرية (Premium)**\n\n"
            "افتح القوة الكاملة للبوت واستمتع بميزة البحث اللامحدود والتحميل الفوري والسريع جداً للملفات الكبيرة بدون قيود، وبدون فترات انتظار، مع استثناء كامل وشامل من كافة القنوات الإجبارية الحالية والمستقبلية:\n\n"
            "💎 **أبرز مزايا حساب البريميوم الذهبي:**\n"
            "• بحث لانهائي طوال اليوم بدون سقف للمحاولات.\n"
            "• تخطي تام لشرط الاشتراك في أي قناة إجبارية في البوت.\n"
            "• أولوية قصوى وسرعة تحميل مضاعفة لملفات الـ PDF الأكاديمية والضخمة.\n"
            "• دعم فني مخصص للمطالبة بكتب غير متوفرة في قواعد البيانات.\n\n"
            "💳 **طريقة التفعيل السريع:**\n"
            "يرجى التواصل المباشر مع قسم المبيعات والاشتراكات لإرسال الآيدي (User ID) الخاص بك وإتمام عملية التفعيل الفوري:\n"
            "📩 معرف التواصل: @UUUULU"
        )
        await query.message.reply_text(text=text, parse_mode="Markdown")
        return

    await handle_callbacks(update, context)

# ===============================================
# معالجة أمر البدء والترحيب الرئيسي (/start)
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            return

    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        target_link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة هنا", url=target_link)],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text=(
                "👋 **أهلاً بك في بوت مكتبة الكتب الرقمية !**\n\n"
                "📚 **فضلاً، اشترك في القناة أدناه ليعمل معك البوت بنجاح:**\n\n"
                "الاشتراك مجاني بالكامل، وهو الدعم الذي يساعدنا على إبقاء البوت متاح مجاناً للجميع بدون اشتراكات مدفوعة."
            ),
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
        [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
        [InlineKeyboardButton("💡 مستشارك القرائي (الرادار)", callback_data="radar_menu")],
        [InlineKeyboardButton("🔥 الأكثر تحميلاً هذا الأسبوع", callback_data="show_trending")],
        [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
        [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
    ])
    await update.message.reply_text(
        text=(
            "🌟 *مرحبًا بك في بوت مكتبة الكتب الذكي*\n\n"
            "📚 مكتبة رقمية متكاملة ومفتوحة المصدر تضم أكثر من مليون كتاب ورواية ومصدر معرفي بين يديك.\n"
            "🔎 يمكنك الآن البحث بحرية تامة من خلال كتابة اسم الكتاب أو جزء منه في رسالة نصية مباشرة للبوت، أو استخدام فهارس الأقسام بالأسفل.\n\n"
            "📖 نتمنى لك وقتًا ممتعًا وقراءة نافعة ومثمرة!"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ===============================================
# إدارة واستقبال معالجة عمليات البحث النصي والتحقق المسبق
# ===============================================
async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            return

    if not await check_subscription(update.effective_user.id, context.bot):
        target_link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة هنا", url=target_link)],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text=(
                "⚠️ **توقفت عملية البحث الحالية!**\n\n"
                "🌱 **فضلاً، اشترك في القناة أدناه ليعمل معك البوت واستئناف البحث:**\n\n"
                "الاشتراك مجاني تماماً، وهو الدعم الوحيد الذي يساعدنا على تغطية تكاليف السيرفرات وضمان بقاء البوت مفتوحاً ومتاحاً مجاناً للجميع."
            ),
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    await search_books(update, context)

# ===============================================
# 📸 استقبال الصور (أغلفة الكتب) ومعالجتها عبر الـ OCR
# ===============================================
async def handle_photo_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if user_data_dict.get(u_id, {}).get("is_banned"):
            return

    if not await check_subscription(update.effective_user.id, context.bot):
        target_link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة هنا", url=target_link)],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text="⚠️ **توقفت عملية فحص الغلاف الحالية!**\n\n🌱 فضلاً، اشترك في القناة أولاً لتفعيل ميزة البحث بالصور واستئناف الفحص.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # إخطار المستخدم ببدء عملية معالجة الغلاف
    processing_msg = await update.message.reply_text("🔄 جاري تحميل صورة الغلاف وقراءة النصوص الذكية... يرجى الانتظار ثوانٍ.")
    
    try:
        # 1. تنزيل ملف الصورة من تيليجرام بأعلى جودة متوفرة
        photo_file = await update.message.photo[-1].get_file()
        
        # إنشاء مجلد مؤقت للتحميلات إذا لم يكن موجوداً
        os.makedirs("downloads", exist_ok=True)
        temp_image_path = f"downloads/cover_{photo_file.file_id}.jpg"
        
        await photo_file.download_to_drive(temp_image_path)
        
        # 2. تمرير الصورة إلى خط المعالجة الاحترافي المتزامن (Async Non-blocking Pipeline)
        result = await telegram_photo_handler_pipeline(temp_image_path)
        
        # 3. حذف رسالة الانتظار المؤقتة للترتيب
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_msg.message_id)
        
        # 4. معالجة الرد وإرسال النتائج للمستخدم بناءً على جودة التماثل
        if isinstance(result, dict) and result["status"] == "exact_match":
            book_data = result["book"]
            success_text = (
                f"{result['message']}\n\n"
                f"📖 **اسم الكتاب:** {book_data['title']}\n"
                f"✍️ **المؤلف:** {book_data['author'] if book_data.get('author') else 'غير مدرج'}"
            )
            await update.message.reply_text(text=success_text, parse_mode="Markdown")
            # 💡 تلميح: يمكنك هنا استدعاء دالة إرسال الملف مباشرة للمستخدم عبر التليجرام باستخدام الـ file_id
            
        elif isinstance(result, dict) and result["status"] == "suggestion":
            book_data = result["book"]
            suggest_text = (
                f"{result['message']}\n\n"
                f"📖 **العنوان المقترح:** {book_data['title']}\n"
                f"✍️ **المؤلف:** {book_data['author'] if book_data.get('author') else 'غير مدرج'}"
            )
            await update.message.reply_text(text=suggest_text, parse_mode="Markdown")
        else:
            # في حال فشل القراءة أو عدم جلب نصوص متطابقة بنسبة كافية
            await update.message.reply_text(text=result, parse_mode="Markdown")
            
        # 5. تنظيف السيرفر وحذف ملف الصورة فوراً لحماية المساحة القرصية
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
            
    except Exception as e:
        logger.error(f"❌ Error inside photo cover handler pipeline: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ عذراً، حدث خطأ تقني غير متوقع أثناء معالجة صورة الغلاف. يرجى المحاولة لاحقاً.")
        except: pass

# ===============================================
# دالة التشغيل والانطلاق الرئيسية والتثبيت المستدام (Main)
# ===============================================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("🚨 BOT_TOKEN environment variable is missing.")
        return

    persistence = PicklePersistence(filepath="bot_data.pickle")
    
    global app
    app = (
        Application.builder()
        .token(token)
        .persistence(persistence)
        .post_init(init_db)
        .build()
    )

    register_admin_handlers(app, start)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_books_with_subscription))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    
    # 📸 ربط مستمع الصور الموجه مباشرة لمعالجة الأغلفة والفحص بـ OCR
    app.add_handler(filters.ChatType.PRIVATE & MessageHandler(filters.PHOTO, handle_photo_cover))
    
    app.add_handler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(ChatMemberHandler(welcome_bot_in_group, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 The cultural book library bot is polling and fully operational...")
    app.run_polling()

if __name__ == "__main__":
    main()
