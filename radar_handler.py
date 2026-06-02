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
    """المرحلة 4: الدمج الصارم واستخراج النتائج بدقة منعاً للعشوائية"""
    size = query.data.split(":")[1]
    category = context.user_data.get("radar_category", "literature")
    difficulty = context.user_data.get("radar_difficulty", "easy")
    
    pool = context.bot_data.get("db_conn")
    if not pool:
        await query.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    # 1. كلمات مفتاحية إلزامية للتصنيف (تضمن ألا تخرج النتيجة عن الحقل المختار)
    category_keywords = []
    if category == "literature":
        category_keywords = ["رواية", "قصة", "حكاية", "روايات", "قصص", "ديستوبيا"]
    elif category == "philosophy":
        category_keywords = ["فلسف", "فكر", "منطق", "نيتشه", "كانط", "أرسطو", "أفلاطون", "هيجل", "سارتر", "وجودية", "وعي"]
    elif category == "poetry":
        category_keywords = ["ديوان", "أشعار", "قصائد", "شعر", "المعلقات"]
    elif category == "psychology":
        category_keywords = ["نفس", "سلوك", "شخصية", "عقلي", "فرويد", "يونغ", "تطوير", "ذات"]

    # 2. كلمات مفتاحية اختيارية للصعوبة والحجم (لتصفية النتائج المفحوصة)
    refinement_keywords = []
    if difficulty == "easy":
        refinement_keywords += ["مبادئ", "مدخل", "تبسيط", "قصة", "بداية", "يسير", "موجز"]
    else:
        refinement_keywords += ["نقد", "أطروحة", "دراسة", "عميق", "مجلد", "الأعمال"]

    if size == "short":
        refinement_keywords += ["وجيز", "ملخص", "شذرات", "قصيرة", "كتيب", "رسالة", "خلاصة"]
    else:
        refinement_keywords += ["موسوعة", "أجزاء", "الجزء", "كامل", "تاريخ"]

    # بناء استعلام صارم: (شرط التصنيف الإلزامي) AND (شروط التصفية الاختيارية)
    cat_clauses = [f"file_name ILIKE '%{k}%'" for k in category_keywords]
    sql_cat_part = f"({ ' OR '.join(cat_clauses) })"

    refine_clauses = [f"file_name ILIKE '%{k}%'" for k in refinement_keywords]
    
    if refine_clauses:
        sql_refine_part = f"({ ' OR '.join(refine_clauses) })"
        # الدمج بـ AND لضمان بقاء النتيجة داخل حقل التصنيف حصراً
        sql_where = f"{sql_cat_part} AND {sql_refine_part}"
    else:
        sql_where = sql_cat_part

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

        # استعلام احتياطي مرن لكنه يظل داخل التصنيف المختار في حال كانت الفلاتر الفرعية ضيقة جداً
        if not rows:
            sql_fallback = f"SELECT file_id, file_name FROM books WHERE {sql_cat_part} ORDER BY RANDOM() LIMIT 5;"
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql_fallback)

        cat_titles = {"literature": "أدب وروايات", "philosophy": "فلسفة وفكر", "poetry": "شعر وديوان", "psychology": "علم نفس وتطوير"}
        diff_titles = {"easy": "سهل وسلس 🟢", "hard": "عميق وأكاديمي 🔴"}
        size_titles = {"short": "وجبة سريعة ⏱️", "long": "رحلة ممتدة 📚"}

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = f"🚀 رادار: {cat_titles.get(category)}"
        
        text_header = (
            f"🚀 **تمت التصفية بنجاح!**\n\n"
            f"خياراتك كانت:\n"
            f"**({cat_titles.get(category)} ➔ {diff_titles.get(difficulty)} ➔ {size_titles.get(size)})**\n\n"
            f"إليك أفضل الترشيحات المناسبة لك الآن:"
        )
        await query.message.reply_text(text_header, parse_mode="Markdown")
        
        from search_handler import send_books_page
        await send_books_page(query, context)

    except Exception as e:
        logger.error(f"Radar Search System Error: {e}")
        await query.message.reply_text("⚠️ حدث خطأ أثناء إطلاق الرادار، يرجى المحاولة لاحقاً.")
