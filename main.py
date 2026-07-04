import os
import re
import sys
import time
import json
import asyncio
import logging
import asyncpg
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union

from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update, 
    Bot, 
    Chat, 
    User, 
    Message, 
    Document,
    CallbackQuery
)
from telegram.ext import (
    Application, 
    MessageHandler, 
    CommandHandler, 
    CallbackQueryHandler,
    ChatMemberHandler, 
    PicklePersistence, 
    ContextTypes, 
    filters
)
from telegram.error import TelegramError, BadRequest, TimedOut, NetworkError

# =====================================================================
# نظام المراقبة الشامل وجداول تسجيل أحداث السيرفر (Logging System)
# =====================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("library_bot_core.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# =====================================================================
# معالج الأخطاء الاستثنائي لحماية السيرفر من الانهيار المفاجئ
# =====================================================================
async def error_handler(update: Optional[object], context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="❌ حدث خطأ استثنائي غير متوقع أثناء معالجة التحديث:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            if "Query is too old" in str(context.error):
                return
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ **نظام الحماية التشغيلي:**\n\nحدثت مشكلة تقنية بسيطة أثناء معالجة طلبك الحالي. نرجو منك إعادة المحاولة مرة أخرى أو استخدام أمر /start لتحديث اللوحة.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"تعذر إرسال تنبيه الخطأ للمستخدم: {e}")

# =====================================================================
# معمارية وإعدادات قاعدة البيانات المتقدمة (PostgreSQL Connection Pool)
# =====================================================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.critical("🚨 لم يتم العثور على متغير البيئة DATABASE_URL!")
            return

        logger.info("⏳ جاري إنشاء حوض اتصالات قاعدة البيانات (Connection Pool)...")
        pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=5,
            max_size=20,
            max_queries=50000,
            max_inactive_connection_lifetime=300.0,
            command_timeout=60.0
        )

        async with pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                name_normalized TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                search_vector TSVECTOR
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW(),
                is_premium BOOLEAN DEFAULT FALSE,
                premium_expiry TIMESTAMP,
                search_credits INT DEFAULT 50,
                referral_count INT DEFAULT 0
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INT DEFAULT 0
            );
            """)
            
            await conn.execute("INSERT INTO stats (key, value) VALUES ('total_searches', 0) ON CONFLICT DO NOTHING;")
            await conn.execute("INSERT INTO stats (key, value) VALUES ('total_downloads', 0) ON CONFLICT DO NOTHING;")
            
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_books_file_name_trgm ON books USING gist (file_name gist_trgm_ops);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_books_search_vector ON books USING gin (search_vector);")

        app_context.bot_data["db_conn"] = pool
        
        if not app_context.bot_data.get("required_channel_id"):
            channel_env = os.getenv("REQUIRED_CHANNEL_ID")
            if channel_env:
                try:
                    app_context.bot_data["required_channel_id"] = int(channel_env)
                except ValueError:
                    app_context.bot_data["required_channel_id"] = channel_env

        logger.info("✅ تم التحقق من الجداول وبناء الفهارس بنجاح.")
    except Exception as e:
        logger.error("❌ فشل في إعداد قاعدة البيانات:", exc_info=True)

async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()
        logger.info("✅ تم إغلاق حوض الاتصالات السحابية بنجاح.")

# =====================================================================
# أنظمة التحقق الرقمي والاشتراك الإجباري الآمن
# =====================================================================
async def check_subscription(user_id: int, bot: Bot) -> bool:
    """
    التحقق الآمن من اشتراك المستخدم مع حماية برمجية تمنع توقف البوت عن الرد
    """
    try:
        from __main__ import app
        pool = app.bot_data.get("db_conn")
        channel_id = app.bot_data.get("required_channel_id")
    except:
        pool, channel_id = None, None

    if pool:
        try:
            async with pool.acquire() as conn:
                res = await conn.fetchrow("SELECT is_premium, premium_expiry FROM users WHERE user_id = $1", user_id)
                if res and res["is_premium"]:
                    if res["premium_expiry"] is None or res["premium_expiry"] > datetime.now():
                        return True  
        except Exception as e:
            logger.error(f"خطأ فحص البريميوم: {e}")

    # إذا لم يتم تحديد قناة إجبارية في متغيرات البيئة، اسمح للمستخدم بالمرور فوراً
    if not channel_id: 
        return True
        
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ("member", "administrator", "creator"):
            return True
        return False
    except Exception as e:
        logger.error(f"خطأ أثناء فحص عضوية القناة للتليجرام للحساب {user_id}: {e}")
        # حماية كبرى: إذا لم يجد البوت القناة أو كان الـ ID خاطئاً، يعود بـ True لكي لا يتعطل البوت بالكامل
        if "Chat not found" in str(e) or "chat not found" in str(e):
            return True
        return False

async def get_channel_invite_link(bot: Bot) -> str:
    try:
        from __main__ import app
        channel_id = app.bot_data.get("required_channel_id")
    except: 
        channel_id = None
    if not channel_id: 
        return "https://t.me/"
    try:
        chat = await bot.get_chat(channel_id)
        if chat.username: 
            return f"https://t.me/{chat.username}"
        elif chat.invite_link: 
            return chat.invite_link
    except Exception as e:
        logger.error(f"تعذر جلب رابط القناة: {e}")
    return f"https://t.me/{str(channel_id).replace('-100', '')}" if isinstance(channel_id, int) else "https://t.me/"

# =====================================================================
# آلية الأرشفة التلقائية للملفات المرفوعة في القنوات المتصلة
# =====================================================================
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (
        update.channel_post
        and update.channel_post.document
        and update.channel_post.document.mime_type == "application/pdf"
    ):
        pool = context.bot_data.get("db_conn")
        if not pool: 
            return
        document = update.channel_post.document
        file_id = document.file_id
        file_name = document.file_name or "كتاب_غير_مصنف.pdf"
        normalized = clean_arabic_text(file_name)
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                INSERT INTO books (file_id, file_name, name_normalized) VALUES ($1, $2, $3)
                ON CONFLICT (file_id) DO UPDATE SET file_name = EXCLUDED.file_name, name_normalized = EXCLUDED.name_normalized;
                """, file_id, file_name, normalized)
                await conn.execute("UPDATE books SET search_vector = to_tsvector('arabic', COALESCE(file_name, '')) WHERE file_id = $1;", file_id)
        except Exception as e:
            logger.error(f"فشلت أرشفة الكتاب: {e}")

# =====================================================================
# محرك المعالجة اللغوية والبحث المطابق الذكي (Search Engine Core)
# =====================================================================
def clean_arabic_text(text: str) -> str:
    if not text: 
        return ""
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ة': 'ه', 'ى': 'ي',
        'گ': 'ك', 'پ': 'ب', 'چ': 'ج', 'ژ': 'ج', 'ڤ': 'ف'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lower()

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if not pool or not update.message or not update.message.text: 
        return

    query_text = update.message.text.strip()
    if query_text.startswith('/'): 
        return

    if len(query_text) < 2:
        await update.message.reply_text(
            text="⚠️ **من فضلك اكتب كلمة أو كلمتين واضحة من اسم الكتاب** لكي يستطيع البوت إيجاده لك بدقة وسهولة.", 
            parse_mode="Markdown"
        )
        return

    cleaned_query = clean_arabic_text(query_text)
    try:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_searches';")
    except: pass

    searching_msg = await update.message.reply_text("🔍 **جاري البحث الآن في رفوف المكتبة الرقمية...**")
    rows = []
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT file_id, file_name, similarity(file_name, $1) as sim
                FROM books
                WHERE file_name % $1 
                   OR name_normalized ILIKE $2
                   OR to_tsvector('arabic', file_name) @@ plainto_tsquery('arabic', $1)
                ORDER BY sim DESC, id DESC LIMIT 8;
            """, query_text, f"%{cleaned_query}%")
    except Exception as e:
        logger.error(f"فشل استعلام البحث: {e}")

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=searching_msg.message_id)
    except: pass

    if not rows:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💡 تشغيل رادار المقترحات الذكي", callback_data="radar_menu")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
        ])
        await update.message.reply_text(
            text=f"❌ **عذراً، لم نجد كتاباً بهذا الاسم حالياً:** ({query_text})\n\n"
                 f"💡 **نصائح سهلة للبحث:**\n"
                 f"• تأكد من كتابة الحروف بشكل صحيح وبدون أخطاء إملائية.\n"
                 f"• جرب كتابة كلمة واحدة فريدة ومميزة من اسم الكتاب بدلاً من العنوان الطويل.\n"
                 f"• يمكنك الضغط على زر الرادار بالأسفل ليقترح عليك البوت كتباً رائعة ومسلية.",
            parse_mode="Markdown", 
            reply_markup=keyboard
        )
        return

    await update.message.reply_text(text=f"✅ **إليك أفضل النتائج التي عثرنا عليها لطلبك ({query_text}):**")
    for row in rows:
        file_id = row["file_id"]
        file_name = row["file_name"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 اضغط هنا لتحميل الكتاب فورا", callback_data=f"dl:{file_id}")],
            [InlineKeyboardButton("📢 إرسال أو مشاركة الكتاب مع صديق", switch_inline_query_current_chat=f"book:{file_id}")]
        ])
        await update.message.reply_text(
            text=f"📖 **اسم الكتاب:**\n`{file_name}`", parse_mode="Markdown", reply_markup=keyboard
        )

# =====================================================================
# نظام رادار المقترحات والترشيح التفاعلي
# =====================================================================
async def start_radar_flow(query: CallbackQuery):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 روايات وقصص ومسليات", callback_data="rad_cat:novels"), InlineKeyboardButton("🧠 فلسفة وعلم نفس وعقل", callback_data="rad_cat:philosophy")],
        [InlineKeyboardButton("⏳ تاريخ وثقافة وسير", callback_data="rad_cat:history"), InlineKeyboardButton("💼 مال وأعمال وتطوير الذات", callback_data="rad_cat:business")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(
        text="💡 **مرحباً بك في رادار المقترحات الذكي!**\n\n👇 **الخطوة الأولى:** اختر القسم أو المجال الذي تميل إليه وتريد القراءة فيه الآن:",
        parse_mode="Markdown", reply_markup=keyboard
    )

async def process_radar_category(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    category = query.data.split(":")[1]
    context.user_data["radar_cat"] = category
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 سهل وبسيط (للمبتدئين ومن يحب الخفة)", callback_data="rad_diff:easy")],
        [InlineKeyboardButton("🪴 متوسط (عميق وممتع بنفس الوقت)", callback_data="rad_diff:medium")],
        [InlineKeyboardButton("🏛️ تخصصي متقدم (للباحثين وأهل العلم)", callback_data="rad_diff:hard")]
    ])
    await query.message.edit_text(
        text="🎯 **الخطوة الثانية: حدد المستوى القرائي المناسب لك الآن:**", parse_mode="Markdown", reply_markup=keyboard
    )

async def process_radar_difficulty(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    difficulty = query.data.split(":")[1]
    context.user_data["radar_diff"] = difficulty
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 كتيب وجيز (أقل من 150 صفحة)", callback_data="rad_size:small")],
        [InlineKeyboardButton("📖 كتاب طبيعي (150 إلى 350 صفحة)", callback_data="rad_size:medium")],
        [InlineKeyboardButton("📚 مجلد كبير وثري (أكثر من 350 صفحة)", callback_data="rad_size:large")]
    ])
    await query.message.edit_text(
        text="⏳ **الخطوة الثالثة والأخيرة: ما هو حجم الكتاب المفضل لجلسة اليوم؟**", parse_mode="Markdown", reply_markup=keyboard
    )

async def execute_radar_search(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    cat = context.user_data.get("radar_cat", "novels")
    keywords_map = {
        "novels": ["رواية", "قصة", "حكاية", "روايات", "قصص"],
        "philosophy": ["فلسفة", "علم نفس", "تحليل", "فيلسوف", "فكر"],
        "history": ["تاريخ", "سيرة", "الحضارة", "قديم", "مذكرات"],
        "business": ["مال", "استثمار", "تنمية", "نجاح", "ثراء", "إدارة"]
    }
    target_keywords = keywords_map.get(cat, ["كتاب"])
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books WHERE file_name ILIKE ANY($1) ORDER BY RANDOM() LIMIT 3;
        """, [f"%{k}%" for k in target_keywords])

    if not rows:
        await query.message.edit_text(
            text="⏳ **تنويه:** يقوم الرادار الآن بترتيب وفهرسة كتب جديدة في هذا القسم المحدد.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        )
        return

    response_text = "💡 **إليك 3 اقتراحات من الرادار تم اختيارها بعناية بناءً على خياراتك:**\n\n"
    keyboard_buttons = []
    for i, row in enumerate(rows, 1):
        response_text += f"{i}️⃣ `{row['file_name']}`\n\n"
        keyboard_buttons.append([InlineKeyboardButton(f"📥 تحميل الترشيح رقم {i}", callback_data=f"dl:{row['file_id']}")])
    keyboard_buttons.append([InlineKeyboardButton("🔄 تعديل المعايير", callback_data="radar_menu"), InlineKeyboardButton("🔙 اللوحة الرئيسية", callback_data="back_to_main")])
    await query.message.edit_text(text=response_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard_buttons))

# =====================================================================
# نظام الفهارس الشاملة المفصلة (عربي وإنجليزي)
# =====================================================================
async def show_index_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 قسم الروايات والآداب", callback_data="idx:novels"), InlineKeyboardButton("🕌 قسم العلوم الإسلامية والفقه", callback_data="idx:islamic")],
        [InlineKeyboardButton("📈 قسم الفكر المالي والتطوير", callback_data="idx:economy"), InlineKeyboardButton("🧬 قسم العلوم العامة والطب", callback_data="idx:science")],
        [InlineKeyboardButton("🔙 العودة إلى اللوحة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(text="📂 **فهرس وأقسام المكتبة العربية الشاملة:**", parse_mode="Markdown", reply_markup=keyboard)

async def handle_index_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    cat_keywords = {
        "novels": ["رواية", "قصص", "ديوان"], "islamic": ["فقه", "تفسير", "القرآن", "سيرة", "حديث"],
        "economy": ["اقتصاد", "إدارة", "تسويق", "مال"], "science": ["طب", "فيزياء", "كيمياء", "رياضيات", "علم"]
    }
    keywords = cat_keywords.get(category, ["كتاب"])
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT file_id, file_name FROM books WHERE file_name ILIKE ANY($1) ORDER BY id DESC LIMIT 5;", [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 هذا القسم يخضع للتنظيم والفهرسة الحالية.", show_alert=True)
        return

    text = f"📂 **إليك أحدث 5 وثائق ومصادر متوفرة في هذا القسم الآن:**\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}️⃣ `{r['file_name']}`\n\n"
        buttons.append([InlineKeyboardButton(f"📥 تحميل هذا الكتاب {i}", callback_data=f"dl:{r['file_id']}")])
    buttons.append([InlineKeyboardButton("🔙 العودة إلى الفهارس", callback_data="show_index")])
    await query.message.edit_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def show_english_index_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Fiction & English Stories", callback_data="eng_idx:fiction"), InlineKeyboardButton("🧠 Mindset & Development", callback_data="eng_idx:selfhelp")],
        [InlineKeyboardButton("💻 Coding & Technology Books", callback_data="eng_idx:tech"), InlineKeyboardButton("🔙 Back To Main Menu", callback_data="back_to_main")]
    ])
    await query.message.edit_text(text="🇬🇧 **English Books Section / الفهرس الإنجليزي والأكاديمي:**", parse_mode="Markdown", reply_markup=keyboard)

async def handle_english_index_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    eng_keywords = {
        "fiction": ["novel", "fiction", "stories", "drama"], "selfhelp": ["mind", "habit", "power", "rich", "success", "think"], "tech": ["python", "code", "programming", "data", "learn", "ai"]
    }
    keywords = eng_keywords.get(category, ["book"])
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT file_id, file_name FROM books WHERE file_name ILIKE ANY($1) ORDER BY id DESC LIMIT 5;", [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 No English books are found here yet.", show_alert=True)
        return

    text = f"🇬🇧 **Latest uploaded English Books:**\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}️⃣ `{r['file_name']}`\n\n"
        buttons.append([InlineKeyboardButton(f"📥 Download Book {i}", callback_data=f"dl:{r['file_id']}")])
    buttons.append([InlineKeyboardButton("🔙 Back to English Index", callback_data="show_english_index")])
    await query.message.edit_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# =====================================================================
# نظام العضويات والتسجيل الآمن
# =====================================================================
async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if not pool or not update.effective_user: 
        return
    user_id = update.effective_user.id
    async with pool.acquire() as conn:
        existing_user = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not existing_user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
            if context.args and context.args[0].startswith("inv_"):
                try: 
                    inviter_id = int(context.args[0].split("_")[1])
                    if inviter_id != user_id:
                        await conn.execute("UPDATE users SET search_credits = search_credits + 10, referral_count = referral_count + 1 WHERE user_id = $1", inviter_id)
                        await context.bot.send_message(chat_id=inviter_id, text="🎉 **عضو جديد دخل عبر رابط إحالتك! تم إضافة 10 محاولات لحسابك.**")
                except Exception as e: logger.error(f"فشلت مكافأة الإحالة: {e}")

async def welcome_bot_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member or update.my_chat_member
    if not chat_member or chat_member.chat.type not in ("group", "supergroup"): return
    if chat_member.new_chat_member.user.id == context.bot.id and chat_member.new_chat_member.status in ("member", "administrator"):
        welcome_text = f"🏛️ **أهلاً وسهلاً بكم في واحة المعرفة!**\n\n📌 **طريقة البحث والاستخدام هنا:**\n`/search اسم الكتاب`"
        try: await context.bot.send_message(chat_id=chat_member.chat.id, text=welcome_text, parse_mode="Markdown")
        except: pass

# =====================================================================
# إدارة الأزرار التفاعلية (Callback Queries)
# =====================================================================
async def handle_start_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    u_id = query.from_user.id
    
    if context.application.user_data and dict(context.application.user_data).get(u_id, {}).get("is_banned"):
        try: await query.answer("❌ حسابك محظور من الإدارة.", show_alert=True)
        except: pass
        return

    try: await query.answer()
    except Exception as e:
        logger.warning(f"⚠️ انتهت صلاحية ضغطة الزر: {e}")
        return

    if query.data == "show_index":
        await show_index_menu(update, context)
    elif query.data.startswith("idx:"):
        await handle_index_selection(update, context)
    elif query.data == "show_english_index":
        await show_english_index_menu(update, context)
    elif query.data.startswith("eng_idx:"):
        await handle_english_index_selection(update, context)
    elif query.data == "radar_menu":
        await start_radar_flow(query)
    elif query.data.startswith("rad_cat:"):
        await process_radar_category(query, context)
    elif query.data.startswith("rad_diff:"):
        await process_radar_difficulty(query, context)
    elif query.data.startswith("rad_size:"):
        await execute_radar_search(query, context)
    elif query.data.startswith("dl:"):
        file_id = query.data.split(":")[1]
        try:
            pool = context.bot_data.get("db_conn")
            try:
                async with pool.acquire() as conn:
                    await conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_downloads';")
            except: pass
            await query.message.reply_document(document=file_id, caption="⚜️ **تم جلب كتابك بنجاح من الأرشيف.**")
        except Exception as e:
            logger.error(f"خطأ تحميل الملف: {e}")
            await query.message.reply_text(text="❌ **معذرة:** تعذر إرسال هذا الملف، قد يكون محذوفاً من خوادم تليجرام.", parse_mode="Markdown")
    elif query.data == "show_advertising_info":
        await query.message.reply_text(text="📢 **قسم الإعلانات والتبادل:**\n\n📩 للتواصل مع الإدارة: @UUUULU", parse_mode="Markdown")
    elif query.data == "buy_premium":
        await query.message.reply_text(text="⭐ **باقات البريميوم:** تخطي القنوات الإجبارية نهائياً وبلا حدود تحميل.\n\n📩 للاشتراك: @UUUULU", parse_mode="Markdown")
    elif query.data in ("back_to_main", "check_subscription"):
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇶 تصفح الكتب العربية", callback_data="show_index"), InlineKeyboardButton("🇬🇧 English Books / الأجنبي", callback_data="show_english_index")],
                [InlineKeyboardButton("💡 رادار الترشيحات والمقترحات الذكي", callback_data="radar_menu")],
                [InlineKeyboardButton("⭐ اشتراك بريميوم (تخطي القنوات)", callback_data="buy_premium")],
                [InlineKeyboardButton("📢 قسم الإعلانات والتبادل التجاري", callback_data="show_advertising_info")]
            ])
            await query.message.edit_text(
                text="🏛️ **مرحباً بك في القائمة الرئيسية لـ مكتبة الكتب الرقمية العظمى**\n\nتم التحقق من حسابك بنجاح. اكتب اسم الكتاب مباشرة هنا في الشات وسيقوم المحرك بجلبه لك فورا.",
                parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            link = await get_channel_invite_link(context.bot)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اضغط هنا أولاً للاشتراك في القناة الرسمية", url=link)],
                [InlineKeyboardButton("🔄 اضغط هنا لتفعيل الحساب بعد الاشتراك مباشرة", callback_data="check_subscription")]
            ])
            await query.message.reply_text(text="🚫 **يجب إكمال الاشتراك أولاً لتفعيل الخدمة مجاناً.**", parse_mode="Markdown", reply_markup=keyboard)

# =====================================================================
# الترحيب البدئي، تعليمات الاستخدام الدقيقة، وحقوق الملكية الفكرية
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    if context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"): return
    
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اضغط هنا للاشتراك في القناة الرسمية للمنصة", url=link)],
            [InlineKeyboardButton("🔄 اضغط هنا لتفعيل الحساب فوراً بعد الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text="👋 **أهلاً ومرحباً بك في منصة مكتبة الكتب الرقمية العظمى!**\n\nيرجى الانضمام أولاً لقناة البوت الرسمية بالأسفل، ثم اضغط على زر التفعيل لتنطلق في عالم القراءة المجاني بالكامل.", 
            parse_mode="Markdown", reply_markup=keyboard
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇶 تصفح الكتب العربية", callback_data="show_index"), InlineKeyboardButton("🇬🇧 English Books / الأجنبي", callback_data="show_english_index")],
        [InlineKeyboardButton("💡 رادار الترشيحات والمقترحات الذكي", callback_data="radar_menu")],
        [InlineKeyboardButton("⭐ اشتراك بريميوم (تخطي القنوات)", callback_data="buy_premium")],
        [InlineKeyboardButton("📢 قسم الإعلانات والتبادل التجاري", callback_data="show_advertising_info")]
    ])
    
    await update.message.reply_text(
        text="🏛️ **أهلاً بك في بوابة منصة مكتبة الكتب الشاملة**\n\n⚖️ **الملكية الفكرية:** نحترم تماماً حقوق الطبع والنشر؛ إذا كنت تملك حقاً قانونياً لمؤلف وترى أن تداوله يضرك، راسلنا لحذفه فوراً عبر @UUUULU.\n\n🔎 **طريقة الاستخدام:** اكتب اسم الكتاب أو المؤلف مباشرة هنا في رسالة عادية، وسيجلب لك البوت رابط التحميل فورا.", 
        parse_mode="Markdown", reply_markup=keyboard
    )

async def search_books_with_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message: return
    if context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"): return
    
    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اضغط هنا للاشتراك في القناة أولاً", url=link)],
            [InlineKeyboardButton("🔄 تفعيل وتحديث الحساب الآن", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text="⚠️ **توقف مؤقت للنظام:** يرجى تفعيل أو تجديد اشتراكك في القناة الرسمية للمنصة المرفقة بالأسفل لتتمكن من إكمال البحث المفتوح مجاناً.", 
            parse_mode="Markdown", reply_markup=keyboard
        )
        return
        
    await search_books(update, context)

async def handle_photo_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    await update.message.reply_text(text="⚠️ **البحث الصوري معطل حالياً.** من فضلك اكتب اسم الكتاب نصياً وسنوفره لك فورا.", parse_mode="Markdown")

# =====================================================================
# دالة التشغيل والانطلاق المعمارية الرئيسية (Main Operational Function)
# =====================================================================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.critical("🚨 لم يتم العثور على توكن البوت BOT_TOKEN!")
        return

    persistence = PicklePersistence(filepath="bot_permanent_data.pickle")
    
    global app
    app = Application.builder().token(token).persistence(persistence).post_init(init_db).build()
    app.add_error_handler(error_handler)

    try:
        from admin_panel import register_admin_handlers  
        register_admin_handlers(app, start)
        logger.info("✅ تم دمج وتكامل معالجات لوحة تحكم المسؤولين والأدمن بنجاح.")
    except Exception as e:
        logger.warning(f"⚠️ تحذير: لم يتم العثور على حزمة admin_panel: {e}")

    # تسجيل الحواضن والمعالجات الأساسية للبوت بترتيب منطقي يمنع الحجب
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_books_with_subscription))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_cover))
    
    # التقاط الرسائل النصية المباشرة في الخاص وتوجيهها للمحرك فوراً
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(ChatMemberHandler(welcome_bot_in_group, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 نظام مكتبة الكتب الرقمية الشاملة يعمل الآن بكامل طاقته...")
    app.run_polling()

if __name__ == "__main__":
    main()
