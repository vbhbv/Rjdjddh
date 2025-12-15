import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page  # نفس دالة عرض الكتب

# -----------------------------
# دوال التطبيع والنظافة
# -----------------------------
def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    if not text: return ""
    for word in ["كتاب", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

# -----------------------------
# الفهرس العربي (دون أي تغيير)
# -----------------------------
INDEXES_AR = [
    ("الروايات", "novels", ["رواية"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"]),
    ("قواعد اللغة العربية", "arabic_grammar", ["قواعد", "نحو", "صرف"]),
    ("الشعر", "poetry", ["شاعر", "قصيدة", "ديوان"]),
    ("النقد الأدبي", "literary_criticism", ["نقد", "تحليل", "أدب"]),
    ("الفيزياء", "physics", ["فيزياء", "طاقة", "ميكانيكا"]),
    ("الكيمياء", "chemistry", ["كيمياء", "تفاعل", "عنصر"]),
    ("الرياضيات", "math", ["رياضيات", "جبر", "هندسة"]),
    ("الفلسفة", "philosophy", ["فلسفة", "منطق", "أخلاق"]),
    ("علم النفس", "psychology", ["علم النفس", "سلوك", "عقل"]),
    ("علم الاجتماع", "sociology", ["علم الاجتماع", "مجتمع", "ثقافة"]),
    ("التاريخ", "history", ["تاريخ", "حضارة", "عصور"]),
    ("الجغرافيا", "geography", ["جغرافيا", "خرائط", "مناخ"]),
    ("السياسة", "politics", ["سياسة", "حكومة", "دولة"]),
    ("الاقتصاد", "economics", ["اقتصاد", "مال", "تجارة"]),
    ("البرمجة", "programming", ["برمجة", "python", "java"]),
    ("الهندسة", "engineering", ["هندسة", "ميكانيكا", "كهرباء"]),
    ("التكنولوجيا", "technology", ["تكنولوجيا", "ذكاء اصطناعي", "روبوت"]),
    ("التعليم", "education", ["تعليم", "مدرسة", "جامعة"]),
    ("اللغات", "languages", ["لغة", "ترجمة", "قاموس"]),
    ("الطب", "medicine", ["طب", "دواء", "علاج"]),
    ("صيدلة", "pharmacy", ["صيدلة", "دواء"]),
    ("طب أسنان", "dentistry", ["أسنان", "تقويم"]),
    ("أعشاب طبيعية", "herbal_medicine", ["أعشاب", "طبيعية"]),
    ("بهارات", "spices", ["بهارات", "توابل"]),
    ("الطبخ", "cooking", ["طبخ", "وصفات", "مطبخ"]),
    ("السفر", "travel", ["سفر", "رحلة", "سياحة"]),
    ("الفنون", "arts", ["فن", "رسم", "موسيقى"]),
    ("التصميم", "design", ["تصميم", "ابداع", "ابتكار"]),
    ("التصميم الداخلي", "interior_design", ["تصميم داخلي", "ديكور"]),
    ("الديكور", "decor", ["ديكور", "تزيين", "إضاءة"]),
    ("الدين", "religion", ["دين", "اسلام", "مسيحية"]),
    ("الرياضة", "sports", ["رياضة", "كرة", "تمارين"]),
    ("الأساطير", "mythology", ["أسطورة", "خرافة"]),
    ("الأبراج", "horoscopes", ["برج", "فلك"]),
    ("علم الفلك", "astronomy", ["فلك", "نجوم"]),
    ("الصحة النفسية", "mental_health", ["عقل", "راحة"]),
    ("الموسيقى", "music", ["موسيقى", "آلة"]),
    ("الرسم", "drawing", ["رسم", "لوحة"]),
    ("السينما", "cinema", ["فيلم", "عرض"]),
    ("التصوير الفوتوغرافي", "photography", ["تصوير", "كاميرا"]),
    ("العطور", "perfumes", ["عطور", "روائح", "سحر"]),
    ("السموم", "toxins", ["سموم", "مواد خطرة", "كيمياء"])
]

# -----------------------------
# الفهرس الإنجليزي الجديد
# -----------------------------
INDEXES_EN = [
    ("Novels", "novels_en", ["novel"]),
    ("Children Stories", "children_stories_en", ["children", "story"]),
    ("Arabic Grammar", "arabic_grammar_en", ["grammar", "arabic"]),
    ("Poetry", "poetry_en", ["poem", "poetry"]),
    ("Literary Criticism", "literary_criticism_en", ["criticism", "literature"]),
    ("Physics", "physics_en", ["physics", "mechanics"]),
    ("Chemistry", "chemistry_en", ["chemistry", "reaction"]),
    ("Mathematics", "math_en", ["math", "algebra", "geometry"]),
    ("Philosophy", "philosophy_en", ["philosophy", "logic"]),
    ("Psychology", "psychology_en", ["psychology", "behavior"]),
    ("Sociology", "sociology_en", ["sociology", "society"]),
    ("History", "history_en", ["history", "civilization"]),
    ("Geography", "geography_en", ["geography", "maps"]),
    ("Politics", "politics_en", ["politics", "government"]),
    ("Economics", "economics_en", ["economics", "finance"]),
    ("Programming", "programming_en", ["programming", "python", "java"]),
    ("Engineering", "engineering_en", ["engineering", "mechanics"]),
    ("Technology", "technology_en", ["technology", "AI", "robot"]),
    ("Education", "education_en", ["education", "school", "university"]),
    ("Languages", "languages_en", ["language", "dictionary", "translation"]),
    ("Medicine", "medicine_en", ["medicine", "treatment"]),
    ("Pharmacy", "pharmacy_en", ["pharmacy", "medicine"]),
    ("Dentistry", "dentistry_en", ["dentistry", "teeth"]),
    ("Herbal Medicine", "herbal_medicine_en", ["herbal", "natural"]),
    ("Spices", "spices_en", ["spices", "flavor"]),
    ("Cooking", "cooking_en", ["cooking", "recipe"]),
    ("Travel", "travel_en", ["travel", "trip"]),
    ("Arts", "arts_en", ["art", "painting", "music"]),
    ("Design", "design_en", ["design", "creative"]),
    ("Interior Design", "interior_design_en", ["interior", "decoration"]),
    ("Decor", "decor_en", ["decor", "lighting"]),
    ("Religion", "religion_en", ["religion", "islam", "christian"]),
    ("Sports", "sports_en", ["sports", "football"]),
    ("Mythology", "mythology_en", ["myth", "legend"]),
    ("Horoscopes", "horoscopes_en", ["horoscope", "zodiac"]),
    ("Astronomy", "astronomy_en", ["astronomy", "stars"]),
    ("Mental Health", "mental_health_en", ["mental", "health"]),
    ("Music", "music_en", ["music", "instrument"]),
    ("Drawing", "drawing_en", ["drawing", "art"]),
    ("Cinema", "cinema_en", ["film", "movie"]),
    ("Photography", "photography_en", ["photography", "camera"]),
    ("Perfumes", "perfumes_en", ["perfumes", "fragrance"]),
    ("Toxins", "toxins_en", ["toxins", "danger"])
]

INDEXES_PER_PAGE = 10

# -----------------------------
# عرض الفهرس بصفحات (عام لكل فهرس)
# -----------------------------
async def show_index_page(update, context: ContextTypes.DEFAULT_TYPE, indexes, page: int = 0):
    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    current_indexes = indexes[start:end]
    total_indexes = len(indexes)

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page}"))
    if end < len(indexes):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📚 اختر الفهرس الذي تريد استعراضه (عدد الفهارس: {total_indexes}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# دوال الفهرس العربي والإنجليزي
# -----------------------------
async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    await show_index_page(update, context, INDEXES_AR, page)

async def show_index_en(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    await show_index_page(update, context, INDEXES_EN, page)

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

    # تحديد نوع الفهرس الحالي من user_data
    current_index_type = context.user_data.get("current_index_type", "ar")
    if current_index_type == "en":
        await show_index_en(update, context, page)
    else:
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

    # تحديد نوع الفهرس
    if any(key == index_key for _, key, _ in INDEXES_EN):
        keywords_list = INDEXES_EN
        context.user_data["current_index_type"] = "en"
    else:
        keywords_list = INDEXES_AR
        context.user_data["current_index_type"] = "ar"

    keywords = []
    for name, key, kws in keywords_list:
        if key == index_key:
            keywords = kws
            break

    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية لهذا الفهرس.")
        return

    keywords = [normalize_text(remove_common_words(k)) for k in keywords]

    # صارم للروايات فقط
    if index_key in ["novels", "novels_en"]:
        sql_condition = " AND ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])
    else:
        sql_condition = " OR ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])

    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {sql_condition}
            ORDER BY uploaded_at DESC;
        """)
    except Exception:
        await query.message.reply_text("❌ حدث خطأ أثناء البحث عن الكتب.")
        return

    if not books:
        await query.message.reply_text("❌ لم يتم العثور على أي كتب ضمن هذا الفهرس.")
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"فهرس: {index_key}"
    context.user_data["is_index"] = True
    context.user_data["index_key"] = index_key

    # زر العودة للفهرس ثابت لجميع صفحات الكتب
    await send_books_page(update, context, include_index_home=True)
