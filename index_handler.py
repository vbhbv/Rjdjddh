# index_handler.py

import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page  # استخدام نفس عرض صفحات البحث العادي
from search_handler import normalize_text, remove_common_words

# -----------------------------
# دوال التطبيع والنظافة
# -----------------------------
# استخدم دوال التطبيع من search_handler.py لتجنب تكرار الكود

# -----------------------------
# قائمة الفهارس - 50 فهرس
# -----------------------------
INDEXES = [
    # بداية بـ "الروايات"
    ("الروايات", "novels", ["رواية", "قصة", "قصص", "مغامرة", "خيال", "دراما"]),

    # فهارس متنوعة
    ("قواعد اللغة العربية", "arabic_grammar", ["قواعد", "نحو", "صرف", "إملاء", "لغوي"]),
    ("كتب إنكليزية", "english_books", ["english", "grammar", "literature", "novel"]),
    ("كتب قانون", "law_books", ["قانون", "تشريع", "محاماة", "تشريعات"]),
    ("الشعر", "poetry", ["شاعر", "قصيدة", "ديوان", "مقطوعة", "معلقات"]),
    ("النقد الأدبي", "literary_criticism", ["نقد", "تحليل", "ادب", "بلاغة"]),
    ("الفيزياء", "physics", ["فيزياء", "طاقة", "كوانتم", "ميكانيكا"]),
    ("الكيمياء", "chemistry", ["كيمياء", "تفاعل", "مركب", "عنصر"]),
    ("الرياضيات", "math", ["رياضيات", "جبر", "هندسة", "إحصاء"]),
    ("الفلسفة", "philosophy", ["فلسفة", "ميتافيزيقيا", "منطق", "أخلاق"]),
    ("الاقتصاد", "economics", ["اقتصاد", "مال", "تجارة", "سوق"]),
    ("البرمجة", "programming", ["برمجة", "كود", "python", "java", "algorithm"]),
    ("التاريخ", "history", ["تاريخ", "حضارة", "عصور", "ملوك"]),
    ("الجغرافيا", "geography", ["جغرافيا", "خرائط", "مناخ", "بيئة"]),
    ("الفنون", "arts", ["فن", "رسم", "موسيقى", "لوحة"]),
    ("التصميم", "design", ["تصميم", "ديكور", "جرافيك", "ابداع"]),
    ("الطب", "medicine", ["طب", "دواء", "تشخيص", "علاج"]),
    ("الطبخ", "cooking", ["طبخ", "وصفات", "اكل", "مطبخ"]),
    ("السفر", "travel", ["سفر", "رحلة", "دليل", "سياحة"]),
    ("الدين", "religion", ["دين", "اسلام", "مسيحية", "يهودية"]),
    ("السياسة", "politics", ["سياسة", "حكومة", "برلمان", "دولة"]),
    ("الرياضة", "sports", ["رياضة", "كرة", "سباق", "تمارين"]),
    ("علم النفس", "psychology", ["علم النفس", "تحليل نفسي", "سلوك", "عقل"]),
    ("الأدب", "literature", ["أدب", "قصة", "مقال"]),
    ("علم الاجتماع", "sociology", ["علم الاجتماع", "مجتمع", "ثقافة", "علاقات"]),
    ("التكنولوجيا", "technology", ["تكنولوجيا", "روبوت", "ذكاء اصطناعي", "تقنية"]),
    ("الهندسة", "engineering", ["هندسة", "ميكانيكا", "كهرباء", "مدني"]),
    ("التعليم", "education", ["تعليم", "مدرسة", "جامعة", "تدريس"]),
    ("اللغات", "languages", ["لغة", "تحدث", "ترجمة", "قاموس"]),
    ("الأساطير", "mythology", ["أسطورة", "خرافة", "أساطير", "أبطال"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"]),
    ("الخياطة", "sewing", ["خياطة", "تطريز", "ملابس", "أزياء"]),
    ("الحاسوب", "computer", ["حاسوب", "برمجة", "كمبيوتر", "تقنية"]),
    ("الروبوتات", "robotics", ["روبوت", "ذكاء اصطناعي", "ميكانيكا"]),
    ("الذكاء الاصطناعي", "ai", ["ذكاء اصطناعي", "ai", "تعلم آلة"]),
    ("التسويق", "marketing", ["تسويق", "اعلان", "بيع", "استراتيجية"]),
    ("التصوير", "photography", ["تصوير", "كاميرا", "فن", "عدسة"]),
    ("الأعمال", "business", ["أعمال", "شركة", "ريادة", "تجارة"]),
    ("التطوير الذاتي", "self_development", ["تطوير", "ذات", "مهارات", "نجاح"]),
    ("الصحة", "health", ["صحة", "علاج", "تشخيص", "دواء"]),
    ("البيئة", "environment", ["بيئة", "تلوث", "نباتات", "حيوانات"]),
    ("الموسيقى", "music", ["موسيقى", "عزف", "آلة", "غناء"]),
    ("التصميم الداخلي", "interior_design", ["ديكور", "تصميم", "منزل", "فن"]),
    ("الإعلام", "media", ["إعلام", "صحافة", "تلفزيون", "راديو"]),
    ("التجارة الإلكترونية", "ecommerce", ["تجارة", "الكتروني", "متاجر", "بيع"]),
    ("الأديان والمعتقدات", "religion_beliefs", ["دين", "إسلام", "مسيحية", "يهودية", "معتقد"]),
    ("الطبيعة", "nature", ["طبيعة", "غابة", "بحر", "جبال"]),
    ("الفلك", "astronomy", ["فلك", "نجوم", "كواكب", "فضاء"]),
    ("علم الاجتماع التطبيقي", "applied_sociology", ["مجتمع", "ثقافة", "علاقات", "سلوك"]),
    ("السينما", "cinema", ["فيلم", "سينما", "إخراج", "تمثيل"]),
]

# -----------------------------
# عرض الفهرس بصفحات 10 عناصر
# -----------------------------
INDEXES_PER_PAGE = 10

async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    current_indexes = INDEXES[start:end]

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page-1}"))
    if end < len(INDEXES):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text("📚 اختر الفهرس الذي تريد استعراضه:", reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text("📚 اختر الفهرس الذي تريد استعراضه:", reply_markup=reply_markup)

# -----------------------------
# الملاحة بين صفحات الفهرس
# -----------------------------
async def navigate_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split(":")[1])
    except Exception:
        await query.message.reply_text("❌ خطأ في تحديد الصفحة.")
        return
    await show_index(update, context, page)

# -----------------------------
# البحث داخل الفهرس وعرض الكتب
# -----------------------------
async def search_by_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index_key = query.data.replace("index:", "")

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    keywords = []
    for name, key, kws in INDEXES:
        if key == index_key:
            keywords = kws
            break

    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية لهذا الفهرس.")
        return

    keywords = [normalize_text(remove_common_words(k)) for k in keywords]

    # تحسين دقة البحث: الكلمة الأساسية أولاً
    primary_keywords = [keywords[0]] if keywords else []
    secondary_keywords = keywords[1:] if len(keywords) > 1 else []

    conditions = []
    for k in primary_keywords:
        conditions.append(f"LOWER(file_name) LIKE '%{k}%'")
    for k in secondary_keywords:
        conditions.append(f"LOWER(file_name) LIKE '%{k}%'")

    sql_where = " AND ".join(conditions)

    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {sql_where}
            ORDER BY uploaded_at DESC;
        """)
    except Exception:
        await query.message.reply_text("❌ حدث خطأ أثناء البحث عن الكتب.")
        return

    if not books:
        await query.message.reply_text("❌ لم يتم العثور على أي كتب ضمن هذا الفهرس.")
        return

    # حفظ الكتب في user_data
    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"فهرس: {index_key}"
    context.user_data["is_index"] = True  # علامة أن هذه الكتب ضمن الفهرس

    # إرسال الكتب مع زر العودة للفهرس دائمًا
    await send_books_page(update, context, include_index_home=True)
