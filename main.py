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
    """
    يقوم بالقبض على أي خطأ برمجي أثناء تشغيل البوت ومعالجته فوراً
    لمنع توقف السيرفر وضمان استمرارية الخدمة لكافة المستخدمين.
    """
    logger.error(msg="❌ حدث خطأ استثنائي غير متوقع أثناء معالجة التحديث:", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_chat:
        try:
            # إذا كان الخطأ ناتج عن انتهاء صلاحية الضغطة أو تفاعل قديم لا نرسل رسالة مزعجة للمستخدم
            if "Query is too old" in str(context.error):
                return
                
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ **نظام الحماية التشغيلي:**\n\nحدثت مشكلة تقنية بسيطة أثناء معالجة طلبك الحالي بسبب الضغط الإضافي على السيرفر. نرجو منك إعادة المحاولة مرة أخرى الآن أو استخدام أمر /start لتحديث اللوحة.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"تعذر إرسال تنبيه الخطأ للمستخدم: {e}")

# =====================================================================
# معمارية وإعدادات قاعدة البيانات المتقدمة (PostgreSQL Connection Pool)
# =====================================================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    """
    إنشاء وتجهيز جداول البيانات وتفعيل إضافات البحث النصي المتقدم ثلاثي الحروف (Trigram)
    """
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.critical("🚨 لم يتم العثور على متغير البيئة DATABASE_URL! يتوجب عليك ضبطه لتشغيل البوت.")
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
            # تفعيل ميزة تجاهل الحركات التشكيلية والبحث بالتشابه اللغوي العربي
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            
            # جدول أرشفة وتخزين وثائق وملفات الكتب الرقمية
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

            # جدول إدارة حسابات المستخدمين والمستويات والميزات والبريميوم
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

            # جدول الإحصائيات العامة والتحليلات السيرفرية للمنصة
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INT DEFAULT 0
            );
            """)
            
            # زرع القيم الأساسية للإحصائيات في حال تشغيل البوت لأول مرة
            await conn.execute("INSERT INTO stats (key, value) VALUES ('total_searches', 0) ON CONFLICT DO NOTHING;")
            await conn.execute("INSERT INTO stats (key, value) VALUES ('total_downloads', 0) ON CONFLICT DO NOTHING;")
            
            # بناء فهارس ومؤشرات تسريع البحث المتقدم والـ Fuzzy Match
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_books_file_name_trgm ON books USING gist (file_name gist_trgm_ops);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_books_search_vector ON books USING gin (search_vector);")

        app_context.bot_data["db_conn"] = pool
        logger.info("✅ تم التحقق من الجداول وبناء الفهارس الإحصائية بنجاح تام.")

    except Exception as e:
        logger.error("❌ فشل كلي في إعداد وتجهيز اتصالات قاعدة البيانات المتقدمة:", exc_info=True)

async def close_db(app: Application):
    """
    إغلاق آمن لكافة اتصالات قاعدة البيانات عند إيقاف السيرفر لمنع تسريب الذاكرة
    """
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()
        logger.info("✅ تم إغلاق حوض الاتصالات السحابية للـ Database بسلام.")

# =====================================================================
# أنظمة التحقق الرقمي، الاشتراك الإجباري، وصلاحيات البريميوم
# =====================================================================
async def check_subscription(user_id: int, bot: Bot) -> bool:
    """
    التحقق مما إذا كان المستخدم يمتلك بريميوم (يتخطى القنوات) أو عضو نشط في القناة الإجبارية
    """
    try:
        from __main__ import app
        pool = app.bot_data.get("db_conn")
        channel_id = app.bot_data.get("required_channel_id")
    except:
        pool, channel_id = None, None

    # الخطوة 1: فحص حالة الاشتراك المميز (البريميوم) أولاً
    if pool:
        try:
            async with pool.acquire() as conn:
                res = await conn.fetchrow("SELECT is_premium, premium_expiry FROM users WHERE user_id = $1", user_id)
                if res and res["is_premium"]:
                    # إذا كانت العضوية مفتوحة للأبد أو تاريخ انتهائها لم يأتي بعد
                    if res["premium_expiry"] is None or res["premium_expiry"] > datetime.now():
                        return True  
        except Exception as e:
            logger.error(f"فشل فحص وضع البريميوم للحساب {user_id}: {e}")

    # الخطوة 2: إذا لم يكن بريميوم، وكان نظام القناة الإجبارية معطلاً، نسمح له بالمرور مجاناً
    if channel_id is None: 
        return True
        
    # الخطوة 3: التحقق الفعلي من وجوده داخل القناة الرسمية للمكتبة
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ("member", "administrator", "creator"):
            return True
        return False
    except Exception as e:
        logger.error(f"خطأ أثناء جلب حالة العضو من تليجرام للحساب {user_id}: {e}")
        return False

async def get_channel_invite_link(bot: Bot) -> str:
    """
    استخراج وتجهيز رابط الدعوة أو المعرف العام لقناة الاشتراك الإجباري
    """
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
    except Exception as e:
        logger.error(f"تعذر جلب رابط القناة: {e}")
    return "https://t.me/"

# =====================================================================
# آلية الأرشفة التلقائية للملفات المرفوعة في القنوات المتصلة
# =====================================================================
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    تستمع هذه الدالة للمنشورات المرفوعة داخل قنوات الأرشفة المرتبطة بالبوت
    وتقوم بحفظ معرّف الملف وتصنيف الاسم للبحث عنه مستقبلاً.
    """
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
        
        # معالجة وتجهيز الاسم للبحث الفوري
        normalized = clean_arabic_text(file_name)
        
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                INSERT INTO books (file_id, file_name, name_normalized)
                VALUES ($1, $2, $3)
                ON CONFLICT (file_id) 
                DO UPDATE SET file_name = EXCLUDED.file_name, name_normalized = EXCLUDED.name_normalized;
                """, file_id, file_name, normalized)
                
                # تحديث فهارس البحث النصي بشكل فوري للملف المضاف لقاعدة البيانات
                await conn.execute("""
                UPDATE books SET search_vector = to_tsvector('arabic', COALESCE(file_name, ''))
                WHERE file_id = $1;
                """, file_id)
        except Exception as e:
            logger.error(f"فشلت عملية أرشفة الكتاب الجديد تلقائياً: {e}")

# =====================================================================
# محرك المعالجة اللغوية والبحث المطابق الذكي (Search Engine Core)
# =====================================================================
def clean_arabic_text(text: str) -> str:
    """
    تنظيف وتبسيط وتوحيد الحروف العربية والإنجليزية لتسهيل عملية مطابقة
    البحث على كل العقول، بغض النظر عن كتابة الهمزات أو التاء المربوطة.
    """
    if not text: 
        return ""
    # إزالة الرموز التعبيرية والخاصة الزائدة للحفاظ على الكلمات فقط
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    
    # خريطة توحيد وتسهيل الحروف للمستخدم البسيط
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ة': 'ه', 'ى': 'ي',
        'گ': 'ك', 'پ': 'ب', 'چ': 'ج', 'ژ': 'ج', 'ڤ': 'ف'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lower()

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    المحرك الرئيسي للبحث عن الكتب وجلبها الفوري للمستخدم بأسلوب هجين ذكي جداً
    """
    pool = context.bot_data.get("db_conn")
    if not pool or not update.message or not update.message.text: 
        return

    query_text = update.message.text.strip()
    if query_text.startswith('/'): 
        return

    # التنبيه الذكي للمصطلحات القصيرة جداً
    if len(query_text) < 2:
        await update.message.reply_text(
            text="⚠️ **من فضلك اكتب كلمة أو كلمتين واضحة من اسم الكتاب** لكي يستطيع البوت إيجاده لك بدقة وسهولة.", 
            parse_mode="Markdown"
        )
        return

    cleaned_query = clean_arabic_text(query_text)
    
    # تسجيل وإحصاء عملية البحث المجرية داخل قاعدة البيانات للتتبع والتحليل
    try:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_searches';")
    except: 
        pass

    # رسالة مؤقتة لتوضيح العملية لجميع مستويات العقول
    searching_msg = await update.message.reply_text("🔍 **جاري البحث الآن في رفوف المكتبة الرقمية...**")

    rows = []
    async with pool.acquire() as conn:
        try:
            # استخدام نظام مطابقة النصوص الهجين (Trigram Similarity + Full Text Search Vector)
            rows = await conn.fetch("""
                SELECT file_id, file_name, similarity(file_name, $1) as sim
                FROM books
                WHERE file_name % $1 
                   OR name_normalized ILIKE $2
                   OR to_tsvector('arabic', file_name) @@ plainto_tsquery('arabic', $1)
                ORDER BY sim DESC, id DESC
                LIMIT 8;
            """, query_text, f"%{cleaned_query}%")
        except Exception as e:
            logger.error(f"فشل تنفيذ استعلام البحث النصي: {e}")

    # حذف رسالة الانتظار فور انتهاء جلب البيانات
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=searching_msg.message_id)
    except:
        pass

    # إذا لم تكن هناك أي نتائج للمصطلح المبحوث عنه
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
                 f"• يمكنك كتابة اسم المؤلف (مثال: نيتشه أو نجيب محفوظ) لاستعراض مؤلفاته.\n"
                 f"• يمكنك الضغط على زر الرادار بالأسفل ليقترح عليك البوت كتباً رائعة ومسلية.",
            parse_mode="Markdown", 
            reply_markup=keyboard
        )
        return

    # إرسال النتائج للمستخدم بأسلوب منظم وأزرار تحميل فورية دون تعقيد
    await update.message.reply_text(text=f"✅ **إليك أفضل النتائج التي عثرنا عليها لطلبك ({query_text}):**")
    
    for row in rows:
        file_id = row["file_id"]
        file_name = row["file_name"]
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 اضغط هنا لتحميل الكتاب فورا", callback_data=f"dl:{file_id}")],
            [InlineKeyboardButton("📢 إرسال أو مشاركة الكتاب مع صديق", switch_inline_query_current_chat=f"book:{file_id}")]
        ])
        
        # إرسال كل نتيجة بشكل منفصل لتسهيل التحميل الفردي للمستخدم العادي
        await update.message.reply_text(
            text=f"📖 **اسم الكتاب:**\n`{file_name}`",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# =====================================================================
# نظام رادار المقترحات والترشيح التفاعلي المبسط والمفصل لجميع الفئات
# =====================================================================
async def start_radar_flow(query: CallbackQuery):
    """
    عرض خيارات الرادار لمساعدة المستخدمين الذين لا يملكون اسماً محدداً لكتاب
    """
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 روايات وقصص ومسليات", callback_data="rad_cat:novels"), InlineKeyboardButton("🧠 فلسفة وعلم نفس وعقل", callback_data="rad_cat:philosophy")],
        [InlineKeyboardButton("⏳ تاريخ وثقافة وسير", callback_data="rad_cat:history"), InlineKeyboardButton("💼 مال وأعمال وتطوير الذات", callback_data="rad_cat:business")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(
        text="💡 **مرحباً بك في رادار المقترحات الذكي!**\n\nإذا كنت محتاراً ولا تعرف ماذا تقرأ اليوم، فالرادار هنا لمساعدتك واقتراح أفضل الكتب المناسبة لك.\n\n👇 **الخطوة الأولى:** اختر القسم أو المجال الذي تميل إليه وتريد القراءة فيه الآن:",
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def process_radar_category(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    الخطوة الثانية: تحديد المستوى والعمق المطلوب للكتاب المقترح
    """
    category = query.data.split(":")[1]
    context.user_data["radar_cat"] = category
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 سهل وبسيط (للمبتدئين ومن يحب الخفة)", callback_data="rad_diff:easy")],
        [InlineKeyboardButton("🪴 متوسط (عميق وممتع بنفس الوقت)", callback_data="rad_diff:medium")],
        [InlineKeyboardButton("🏛️ تخصصي متقدم (للباحثين وأهل العلم)", callback_data="rad_diff:hard")]
    ])
    await query.message.edit_text(
        text="🎯 **الخطوة الثانية: حدد المستوى القرائي المناسب لك الآن:**\n\nهل تفضل كتاباً سهلاً وخفيفاً للبدايات، أم كتاباً يحتاج تركيزاً وعمقاً؟", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def process_radar_difficulty(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    الخطوة الثالثة: تحديد الحجم المفضل للكتاب
    """
    difficulty = query.data.split(":")[1]
    context.user_data["radar_diff"] = difficulty
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 كتيب وجيز (أقل من 150 صفحة)", callback_data="rad_size:small")],
        [InlineKeyboardButton("📖 كتاب طبيعي (150 إلى 350 صفحة)", callback_data="rad_size:medium")],
        [InlineKeyboardButton("📚 مجلد كبير وثري (أكثر من 350 صفحة)", callback_data="rad_size:large")]
    ])
    await query.message.edit_text(
        text="⏳ **الخطوة الثالثة والأخيرة: ما هو حجم الكتاب المفضل لجلسة اليوم؟**\n\nهل تبحث عن كتيب سريع تنهيه في ساعة، أم مجلد ثري لرحلة طويلة؟", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def execute_radar_search(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """
    الخطوة النهائية: استخراج الاقتراحات العشوائية المطابقة لمعايير المستخدم وسحبها من قاعدة البيانات
    """
    pool = context.bot_data.get("db_conn")
    cat = context.user_data.get("radar_cat", "novels")
    diff = context.user_data.get("radar_diff", "medium")
    size = query.data.split(":")[1]
    
    # خريطة الربط الكلمي لتسهيل البحث على المبتدئين
    keywords_map = {
        "novels": ["رواية", "قصة", "حكاية", "روايات", "قصص"],
        "philosophy": ["فلسفة", "علم نفس", "تحليل", "فيلسوف", "فكر"],
        "history": ["تاريخ", "سيرة", "الحضارة", "قديم", "مذكرات"],
        "business": ["مال", "استثمار", "تنمية", "نجاح", "ثراء", "إدارة"]
    }
    
    target_keywords = keywords_map.get(cat, ["كتاب"])
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY RANDOM() LIMIT 3;
        """, [f"%{k}%" for k in target_keywords])

    if not rows:
        await query.message.edit_text(
            text="⏳ **تنويه:** يقوم الرادار الآن بترتيب وفهرسة كتب جديدة في هذا القسم المحدد، يرجى تجربة خيارات أخرى أو استخدام محرك البحث النصي المباشر.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]])
        )
        return

    response_text = "💡 **إليك 3 اقتراحات من الرادار تم اختيارها بعناية بناءً على خياراتك:**\n\n"
    keyboard_buttons = []
    
    for i, row in enumerate(rows, 1):
        response_text += f"{i}️⃣ `{row['file_name']}`\n\n"
        keyboard_buttons.append([InlineKeyboardButton(f"📥 تحميل الترشيح رقم {i}", callback_data=f"dl:{row['file_id']}")])
    
    keyboard_buttons.append([
        InlineKeyboardButton("🔄 تعديل المعايير", callback_data="radar_menu"), 
        InlineKeyboardButton("🔙 اللوحة الرئيسية", callback_data="back_to_main")
    ])
    
    await query.message.edit_text(
        text=response_text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(keyboard_buttons)
    )

# =====================================================================
# نظام الفهارس الشاملة المفصلة (عربي وإنجليزي) لتسهيل تصفح الأقسام
# =====================================================================
async def show_index_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 قسم الروايات والآداب", callback_data="idx:novels"), InlineKeyboardButton("🕌 قسم العلوم الإسلامية والفقه", callback_data="idx:islamic")],
        [InlineKeyboardButton("📈 قسم الفكر المالي والتطوير", callback_data="idx:economy"), InlineKeyboardButton("🧬 قسم العلوم العامة والطب", callback_data="idx:science")],
        [InlineKeyboardButton("🔙 العودة إلى اللوحة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(
        text="📂 **فهرس وأقسام المكتبة العربية الشاملة:**\n\nمرحباً بك في الأرشيف المبوب، يرجى الضغط على القسم الذي ترغب في استعراض أحدث الكتب المضافة إليه تلقائياً للتحميل المباشر:", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def handle_index_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    
    cat_keywords = {
        "novels": ["رواية", "قصص", "ديوان"], 
        "islamic": ["فقه", "تفسير", "القرآن", "سيرة", "حديث"],
        "economy": ["اقتصاد", "إدارة", "تسويق", "مال"], 
        "science": ["طب", "فيزياء", "كيمياء", "رياضيات", "علم"]
    }
    
    keywords = cat_keywords.get(category, ["كتاب"])
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY id DESC LIMIT 5;
        """, [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 هذا القسم يخضع للتنظيم والفهرسة الحالية، جرب قسماً آخر.", show_alert=True)
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
    await query.message.edit_text(
        text="🇬🇧 **English Books Section / الفهرس الإنجليزي والأكاديمي:**\n\nPlease choose your category to display recently uploaded international books:\n\nيرجى اختيار القسم لعرض أحدث الكتب والوثائق الأجنبية المضافة حديثاً:", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def handle_english_index_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    
    eng_keywords = {
        "fiction": ["novel", "fiction", "stories", "drama"], 
        "selfhelp": ["mind", "habit", "power", "rich", "success", "think"], 
        "tech": ["python", "code", "programming", "data", "learn", "ai"]
    }
    keywords = eng_keywords.get(category, ["book"])
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY id DESC LIMIT 5;
        """, [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 No English books are found in this section yet.", show_alert=True)
        return

    text = f"🇬🇧 **Latest uploaded English Books in this section:**\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}️⃣ `{r['file_name']}`\n\n"
        buttons.append([InlineKeyboardButton(f"📥 Download Book {i}", callback_data=f"dl:{r['file_id']}")])
    buttons.append([InlineKeyboardButton("🔙 Back to English Index", callback_data="show_english_index")])
    
    await query.message.edit_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# =====================================================================
# نظام العضويات، الإحالات، والتسجيل الآمن
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
            
            # معالجة روابط الدعوة والإحالات المباشرة لمنح الجوائز والتحميلات الإضافية
            if context.args and context.args[0].startswith("inv_"):
                try: 
                    inviter_id = int(context.args[0].split("_")[1])
                    if inviter_id != user_id:
                        await conn.execute("UPDATE users SET search_credits = search_credits + 10, referral_count = referral_count + 1 WHERE user_id = $1", inviter_id)
                        await context.bot.send_message(
                            chat_id=inviter_id,
                            text="🎉 **خبر سار وهدية لك!**\n\nلقد دخل صديق جديد إلى البوت باستخدام رابط الدعوة الخاص بك الموزع. تم إضافة **10 محاولات تحميل إضافية مجانية** إلى رصيد حسابك فوراً شكراً لك!",
                            parse_mode="Markdown"
                        )
                except Exception as e: 
                    logger.error(f"فشلت مكافأة الإحالة للحساب: {e}")

async def welcome_bot_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    إرسال رسالة ترحيبية وتعليمات مبسطة عند إضافة البوت لمجموعة أو جروب ثقافي
    """
    chat_member = update.chat_member or update.my_chat_member
    if not chat_member or chat_member.chat.type not in ("group", "supergroup"): 
        return
    if chat_member.new_chat_member.user.id == context.bot.id and chat_member.new_chat_member.status in ("member", "administrator"):
        group_name = chat_member.chat.title or "المجموعة"
        welcome_text = f"🏛️ **أهلاً وسهلاً بكم في واحة المعرفة داخل جروب ( {group_name} )!**\n\nتم تفعيل ميزة البحث السريع عن الكتب داخل هذا الجروب بنجاح.\n\n📌 **طريقة البحث والاستخدام هنا:**\nاكتب فقط الأمر المباشر ويليه اسم الكتاب أو الرواية بالشكل التالي:\n`/search اسم الكتاب المراد قراءته`"
        try: 
            await context.bot.send_message(chat_id=chat_member.chat.id, text=welcome_text, parse_mode="Markdown")
        except: 
            pass

# =====================================================================
# إدارة الأزرار التفاعلية وتحميل الملفات الفوري (Callback Queries)
# =====================================================================
async def handle_start_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالجة كافة النقرات وضغطات الأزرار للبوت وتوجيهها بدقة وأمان تام
    """
    query = update.callback_query
    u_id = query.from_user.id
    
    # فحص الحظر الإداري أولاً
    if context.application.user_data and dict(context.application.user_data).get(u_id, {}).get("is_banned"):
        try: 
            await query.answer("❌ عذراً، حسابك الحالي تم حظره من قبل الإدارة لمخالفة الشروط.", show_alert=True)
        except: 
            pass
        return

    # تأمين وحماية الضغطة من الأخطاء والـ Timeout الفجائي لتسريع استجابة السيرفر
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"⚠️ انتهت صلاحية ضغطة زر التليجرام أو تم تجاهلها: {e}")
        return

    # توجيه الطلبات حسب الكود البرمجي للزر المكبوس
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
            
            await query.message.reply_document(
                document=file_id, 
                caption="⚜️ **تم جلب وتجهيز كتابك بنجاح من الأرشيف الرقمي.**\n\nنتمنى لك قراءة ممتعة ووصفة فكرية نافعة! لا تنسى مشاركة البوت مع أصدقائك لدعمنا."
            )
        except Exception as e:
            logger.error(f"خطأ أثناء إرسال وتحميل الملف للمستخدم {u_id}: {e}")
            await query.message.reply_text(
                text="❌ **معذرة:** تعذر إرسال هذا الملف حالياً، قد يكون الملف قد تم حذفه من خوادم تليجرام الرئيسية أو أن الوثيقة تالفة ونعمل على إصلاحها.", 
                parse_mode="Markdown"
            )
            
    elif query.data == "show_advertising_info":
        adv_text = "📢 **قسم الإعلانات والتبادل والخدمات الرقمية:**\n\nلدعم استمرارية السيرفرات ودفع نفقات حوض البيانات والمكتبة لكي تظل مجانية لكل العقول، نفتح باب التبادل الإعلاني والاشتراكات والتمويل.\n\n📩 **للتواصل المباشر مع إدارة المنصة الرسمية:** @UUUULU"
        await query.message.reply_text(text=adv_text, parse_mode="Markdown")
        
    elif query.data == "buy_premium":
        text = "⭐ **باقات العضوية المميزة المريحة (Premium) لرواد المعرفة:**\n\nإذا كنت لا تحب الإعلانات أو الاشتراكات الإجبارية وتريد ميزات خارقة، يمكنك ترقية حسابك لعضوية البريميوم الفخمة والحصول على:\n\n• ⚡ **سرعة البرق:** الأولوية القصوى للسيرفر في معالجة طلباتك وإرسال الكتب فوراً.\n• 🚫 **تخطي تام ومطلق:** تصفح وابحث وحمل دون الحاجة للاشتراك بأي قنوات إجبارية نهائياً وبلا أي إعلانات مزعجة.\n• 📥 **تحميل بلا حدود:** إلغاء أي قيود على عدد الكتب المسموح بتحميلها يومياً.\n\n📩 **للاشتراك الفوري والآمن ومعرفة الأسعار والطرق، راسل الإدارة عبر معرف التليجرام:** @UUUULU"
        await query.message.reply_text(text=text, parse_mode="Markdown")
        
    elif query.data in ("back_to_main", "check_subscription"):
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇶 تصفح الكتب العربية", callback_data="show_index"), InlineKeyboardButton("🇬🇧 English Books / الأجنبي", callback_data="show_english_index")],
                [InlineKeyboardButton("💡 رادار الترشيحات والمقترحات الذكي", callback_data="radar_menu")],
                [InlineKeyboardButton("⭐ اشتراك بريميوم (تخطي القنوات والإعلانات)", callback_data="buy_premium")],
                [InlineKeyboardButton("📢 قسم الإعلانات والتبادل التجاري", callback_data="show_advertising_info")]
            ])
            await query.message.edit_text(
                text="🏛️ **مرحباً بك في القائمة الرئيسية لـ مكتبة الكتب الرقمية العظمى**\n\nتم التحقق من حسابك بنجاح والنظام مفتوح بالكامل بين يديك الآن مجاناً لفحص وتحميل أكثر من نصف مليون كتاب وثيقة فكرية وأدبية وثقافية.\n\n✍️ **طريقة الاستخدام السهلة (لكل العقول):**\nاكتب اسم الكتاب أو اسم المؤلف أو الكلمة المفتاحية مباشرة في رسالة هنا للبوت، وسيقوم المحرك بالبحث الفوري وإعطائك زر التحميل المباشر والخاطف.",
                parse_mode="Markdown", 
                reply_markup=keyboard
            )
        else:
            link = await get_channel_invite_link(context.bot)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اضغط هنا أولاً للاشتراك في القناة الرسمية", url=link)],
                [InlineKeyboardButton("🔄 اضغط هنا لتفعيل الحساب بعد الاشتراك مباشرة", callback_data="check_subscription")]
            ])
            try: 
                await query.message.reply_text(
                    text="🚫 **تنبيه هام - يجب إكمال الاشتراك لتفعيل الخدمة:**\n\nعذراً، يتطلب النظام تفعيل اشتراكك في قناة المكتبة الرسمية بالأسفل أولاً لحفظ واستمرارية الخدمة المجانية لكل الناس وتحديث محرك البحث. يرجى الانضمام للقناة ثم العودة والضغط على الزر الدائري لتفعيل الحساب فوراً.", 
                    parse_mode="Markdown", 
                    reply_markup=keyboard
                )
            except: 
                pass

# =====================================================================
# الترحيب البدئي، تعليمات الاستخدام الدقيقة، وحقوق الملكية الفكرية
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    دالة استقبال المستخدم لأول مرة ومعالجة قيود العضوية والترحيب السلس
    """
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"): 
        return
        
    await register_user(update, context)

    # التحقق من الاشتراك الإجباري للمستخدم وإظهار لوحة القنوات أولاً إن لم يكن مشتركاً
    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اضغط هنا للاشتراك في القناة الرسمية للمنصة", url=link)],
            [InlineKeyboardButton("🔄 اضغط هنا لتفعيل الحساب فوراً بعد الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text="👋 **أهلاً ومرحباً بك في منصة مكتبة الكتب الرقمية  !**\n\n"
                 "لضمان استمرارية الخوادم وتغطية النفقات المرتفعة ولتحديث قواعد البيانات بأحدث الكتب يومياً، "
                 "يرجى الانضمام أولاً لقناة البوت الداعمة بالأسفل، ثم اضغط على زر التفعيل لتنطلق في عالم القراءة المجاني بالكامل.", 
            parse_mode="Markdown", 
            reply_markup=keyboard
        )
        return

    # إظهار القائمة الرئيسية الشاملة والمفصلة جداً مع تلبية كامل شروطك لرسالة الحقوق والتعليمات بالملف الكامل
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇶 تصفح الكتب العربية", callback_data="show_index"), InlineKeyboardButton("🇬🇧 English Books / الأجنبي", callback_data="show_english_index")],
        [InlineKeyboardButton("💡 رادار الترشيحات والمقترحات الذكي", callback_data="radar_menu")],
        [InlineKeyboardButton("⭐ اشتراك بريميوم (تخطي القنوات والإعلانات)", callback_data="buy_premium")],
        [InlineKeyboardButton("📢 قسم الإعلانات والتبادل التجاري", callback_data="show_advertising_info")]
    ])
    
    await update.message.reply_text(
        text="🏛️ **أهلاً بك في بوابة منصة مكتبة الكتب الفكرية الشاملة**\n\n"
             "نضع بين يديك هذا المحرك التفاعلي البسيط والمتقدم جداً لمساعدتك في الحصول على أي كتاب أو رواية أو وثيقة دراسية مجاناً وبكل سهولة تامة لتناسب كافة المستويات والأعمار.\n\n"
             "⚖️ **رسالة احترام حقوق الملكية الفكرية وطبع النشر:**\n"
             "جميع المواد، الكتب، والملفات الرقمية المتاحة في هذه المنصة يتم فهرستها وجلبها تلقائياً بالكامل من مصادر إنترنت عامة ومفتوحة للعموم ومتداولة مسبقاً. "
             "نحن نحترم ونلتزم تماماً بحقوق الطبع والنشر والملكية الفكرية لأي كاتب أو دار نشر؛ وبناءً على ذلك، إذا كنت تملك حقاً قانونياً لمؤلف وترى أن تداوله يضرك، "
             "يرجى مراسلتنا فوراً وبشكل ودي ومباشر عبر معرف الإدارة، وسيقوم فريق الصيانة بحذفه نهائياً من خوادم وقواعد بيانات البوت خلال دقائق معدودة.\n\n"
             "🔎 **تعليمات الاستخدام المباشرة للبحث وفحص الأرشيف:**\n"
             "طريقة الاستخدام سهلة جداً ولا تحتاج أي شرح أو أوامر معقدة! كل ما عليك فعله هو **كتابة اسم الكتاب** أو **اسم المؤلف** أو **كلمة مفتاحية مميزة** من العنوان في رسالة نصية عادية هنا للبوت وإرسالها، "
             "وسيقوم المحرك التلقائي بفحص مئات الآلاف من الرفوف الرقمية وجلب رابط التحميل الفوري والمباشر لك في ثوانٍ معدودة.", 
        parse_mode="Markdown", 
        reply_markup=keyboard
    )

async def search_books_with_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    التحقق الآمن من اشتراك المستخدم قبل تفعيل وتنفيذ محرك البحث النصي
    """
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"): 
        return
        
    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اضغط هنا للاشتراك في القناة أولاً", url=link)],
            [InlineKeyboardButton("🔄 تفعيل وتحديث الحساب الآن", callback_data="check_subscription")]
        ])
        await update.message.reply_text(
            text="⚠️ **توقف مؤقت للنظام:** يرجى تفعيل أو تجديد اشتراكك في القناة الرسمية للمنصة المرفقة بالأسفل لتأصيل حسابك والتمكن من إكمال البحث المفتوح مجاناً.", 
            parse_mode="Markdown", 
            reply_markup=keyboard
        )
        return
        
    await search_books(update, context)

# =====================================================================
# إدارة الصور الموفرة للأداء وموارد الاستضافة للـ VPS
# =====================================================================
async def handle_photo_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    توجيه معالجة الصور لتقليل الاستهلاك وحفظ أداء السيرفر السحابي
    """
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"): 
        return
    await update.message.reply_text(
        text="⚠️ **تنظيم تشغيلي مهم:**\n\nنود إعلامكم بأن البحث عن طريق إرسال صور أغلفة الكتب معطل حالياً بشكل مؤقت؛ وذلك للحفاظ على استقرار السيرفر وسرعة معالجة الملفات النصية مجاناً لجميع الباحثين.\n\n✍️ **البديل السريع المتاح:** من فضلك اكتب اسم الكتاب أو المؤلف في رسالة نصية عادية وسنوفره لك فورا وبسرعة خيالية.",
        parse_mode="Markdown"
    )

# =====================================================================
# دالة التشغيل والانطلاق المعمارية الرئيسية (Main Operational Function)
# =====================================================================
def main():
    """
    الدالة الأم لبدء تشغيل سيرفر البوت وربط كافة الأكواد وبناء الجلسات الدائمة
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.critical("🚨 خطأ فادح: لم يتم العثور على توكن البوت BOT_TOKEN في متغيرات البيئة! يتوجب عليك تعيينه أولاً لكي ينطلق البوت.")
        return

    # استخدام الـ PicklePersistence لحفظ بيانات الإعدادات والتحليلات عبر الإيقاف والتشغيل دون ضياعها
    persistence = PicklePersistence(filepath="bot_permanent_data.pickle")
    
    global app
    app = Application.builder().token(token).persistence(persistence).post_init(init_db).build()

    # ربط معالج الأخطاء الاستثنائي الشامل لتجنب انقطاع خادم البولينج
    app.add_error_handler(error_handler)

    # استدعاء وتسجيل لوحة تحكم المسؤولين المتقدمة من الملف الجانبي admin_panel
    try:
        from admin_panel import register_admin_handlers  
        register_admin_handlers(app, start)
        logger.info("✅ تم دمج وتكامل معالجات لوحة تحكم المسؤولين والأدمن بنجاح.")
    except Exception as e:
        logger.warning(f"⚠️ تحذير: لم يتم العثور على حزمة admin_panel أو تعذر تحميلها: {e}")

    # تسجيل خطوط الأوامر الثابتة والمحركات التفاعلية للبوت لجميع الحالات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_books_with_subscription))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    
    # فلترة آمنة لتوجيه الرسائل النصية والصور السيرفرية ومنع تجميد المعالجة
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_cover))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(ChatMemberHandler(welcome_bot_in_group, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 نظام مكتبة الكتب الرقمية الشاملة يعمل الآن بكامل طاقته المعمارية وبدأ في استقبال طلبات المستخدمين الفورية...")
    
    # تشغيل خوادم الاستماع المباشر من تليجرام
    app.run_polling()

if __name__ == "__main__":
    main()
