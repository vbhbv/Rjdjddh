import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# إعداد اللوج لتتبع أي أخطاء داخل الرادار
logger = logging.getLogger(__name__)

async def start_radar_flow(query):
    """المرحلة 1: اختيار التصنيف العام"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 أدب وروايات", callback_data="rad_cat:literature"),
         InlineKeyboardButton("🧠 فلسفة وفكر", callback_data="rad_cat:philosophy")],
        [InlineKeyboardButton("📜 شعر وديوان", callback_data="rad_cat:poetry"),
         InlineKeyboardButton("💡 علم نفس وتطوير", callback_data="rad_cat:psychology")],
        [InlineKeyboardButton("⬅️ العودة للقائمة الرئيسية", callback_data="check_subscription")]
    ])
    text = (
        "🎯 **مرحباً بك في رادار الكتب الذكي!**\n\n"
        "أنا هنا لأساعدك في العثور على كتابك القادم بدقة.\n"
        "أولاً، **ما هو المجال أو الحقل المعرفي الذي يثير فضولك الآن؟**"
    )
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def process_radar_category(query, context: ContextTypes.DEFAULT_TYPE):
    """المرحلة 2: اختيار مستوى الصعوبة"""
    category = query.data.split(":")[1]
    context.user_data["radar_category"] = category
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 سهل وسلس (بداية خفيفة)", callback_data="rad_diff:easy")],
        [InlineKeyboardButton("🔴 عميق وأكاديمي (تحدي عقلي)", callback_data="rad_diff:hard")]
    ])
    
    cat_titles = {
        "literature": "الأدب والروايات", 
        "philosophy": "الفلسفة والفكر", 
        "poetry": "الشعر والديوان", 
        "psychology": "علم النفس والتطوير"
    }
    
    text = (
        f"🧠 **أحسنت الاختيار! حقل ({cat_titles.get(category, '')}) يفتح آفاقاً جديدة.**\n\n"
        "ولكي نختار بدقة، **ما هو مستوى العمق أو الصعوبة الذي تفضله في القراءة الآن؟**"
    )
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def process_radar_difficulty(query, context: ContextTypes.DEFAULT_TYPE):
    """المرحلة 3: اختيار الحجم والالتزام الزمني"""
    difficulty = query.data.split(":")[1]
    context.user_data["radar_difficulty"] = difficulty
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ كتاب قصير (وجبة سريعة)", callback_data="rad_size:short")],
        [InlineKeyboardButton("📚 كتاب كامل (رحلة ممتدة)", callback_data="rad_size:long")]
    ])
    
    text = (
        "⏳ **ممتاز جداً.. حددنا الصعوبة والعمق الفكري.**\n\n"
        "السؤال الأخير لنطلق الرادار: **كم من الوقت أو حجم الالتزام الذي تملكه لهذا الكتاب؟**"
    )
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def execute_radar_search(query, context: ContextTypes.DEFAULT_TYPE):
    """المرحلة 4: الدمج واستخراج النتائج التصفوية من قاعدة البيانات"""
    size = query.data.split(":")[1]
    category = context.user_data.get("radar_category", "literature")
    difficulty = context.user_data.get("radar_difficulty", "easy")
    
    pool = context.bot_data.get("db_conn")
    if not pool:
        await query.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    # بناء مصفوفة الكلمات المفتاحية بناءً على خيارات المستخدم
    keywords = []
    
    if category == "literature":
        keywords += ["رواية", "قصة", "حكاية", "روايات"] if difficulty == "easy" else ["الأعمال الكاملة", "ثلاثية", "مجلد", "ديستوبيا", "نقد"]
    elif category == "philosophy":
        keywords += ["مبادئ", "مدخل", "تبسيط", "قصة الفلسفة", "بداية"] if difficulty == "easy" else ["نقد", "نيتشه", "ظاهراتية", "منطق", "أطروحة"]
    elif category == "poetry":
        keywords += ["قصائد", "أشعار", "بسيط", "روائع"] if difficulty == "easy" else ["ديوان", "المجلد", "الكاملة", "شرح"]
    elif category == "psychology":
        keywords += ["عادات", "نجاح", "غير حياتك", "كيف", "خطوات"] if difficulty == "easy" else ["التحليل النفسي", "فرويد", "السلوك", "المعرفي", "دراسة"]

    # فلترة الحجم المذكور بالكلمات المفتاحية كعامل مساعد ذكي للتصفية
    if size == "short":
        keywords += ["وجيز", "ملخص", "شذرات", "قصيرة", "كتيب", "رسالة"]
    else:
        keywords += ["موسوعة", "أجزاء", "الجزء", "كامل"]

    where_clauses = [f"file_name ILIKE '%{k}%'" for k in keywords]
    sql_where = " OR ".join(where_clauses)

    sql = f"""
    SELECT file_id, file_name 
    FROM books 
    WHERE {sql_where}
    ORDER BY RANDOM() 
    LIMIT 5;
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

        if not rows:
            # استعلام احتياطي عام في حال كانت الفلاتر مفرطة الضيق على الداتابيز
            sql_fallback = "SELECT file_id, file_name FROM books ORDER BY RANDOM() LIMIT 5;"
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql_fallback)

        cat_titles = {"literature": "أدب وروايات", "philosophy": "فلسفة وفكر", "poetry": "شعر وديوان", "psychology": "علم نفس وتطوير"}
        diff_titles = {"easy": "سهل وسلس 🟢", "hard": "عميق وأكاديمي 🔴"}
        size_titles = {"short": "وجبة سريعة ⏱️", "long": "رحلة ممتدة 📚"}

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = f"🚀 رادار: {cat_titles.get(category)}"
        
        # إرسال نص ترحيبي تمهيدي قبل استدعاء قائمة النتائج التفاعلية القياسية للمستخدم
        text_header = (
            f"🚀 **تمت التصفية بنجاح!**\n\n"
            f"خياراتك كانت:\n"
            f"**({cat_titles.get(category)} ➔ {diff_titles.get(difficulty)} ➔ {size_titles.get(size)})**\n\n"
            f"إليك أفضل الترشيحات المناسبة لك الآن:"
        )
        await query.message.reply_text(text_header, parse_mode="Markdown")
        
        # استدعاء عرض الصفحات القياسي الفوري المعتمد في البوت
        from search_handler import send_books_page
        await send_books_page(query, context)

    except Exception as e:
        logger.error(f"Radar Search System Error: {e}")
        await query.message.reply_text("⚠️ حدث خطأ أثناء إطلاق الرادار، يرجى المحاولة لاحقاً.")
