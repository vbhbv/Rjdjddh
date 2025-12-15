# index_handler.py
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page  # دالة عرض الكتب

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
# الفهرس العربي
# -----------------------------
INDEXES = [
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

INDEXES_PER_PAGE = 10

# -----------------------------
# الفهرس الإنجليزي
# -----------------------------
ENGLISH_INDEXES = [
    ("Novels", "novels_en", ["novel", "story", "fiction"]),
    ("Children Stories", "children_stories_en", ["children", "story", "adventure"]),
    ("Science", "science_en", ["physics", "chemistry", "biology"]),
    ("Mathematics", "math_en", ["math", "algebra", "geometry"]),
    ("Programming", "programming_en", ["python", "java", "coding"]),
    ("Technology", "technology_en", ["AI", "robotics", "technology"]),
    ("History", "history_en", ["history", "civilization", "era"]),
    ("Philosophy", "philosophy_en", ["philosophy", "ethics", "logic"]),
    ("Psychology", "psychology_en", ["psychology", "mind", "behavior"]),
    ("Languages", "languages_en", ["language", "translation", "dictionary"])
]

ENGLISH_INDEXES_PER_PAGE = 10

# -----------------------------
# عرض الفهرس العربي
# -----------------------------
async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    current_indexes = INDEXES[start:end]
    total_indexes = len(INDEXES)

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page-1}"))
    if end < len(INDEXES):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📚 اختر الفهرس العربي (عدد الفهارس: {total_indexes}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# عرض الفهرس الإنجليزي
# -----------------------------
async def show_english_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    start = page * ENGLISH_INDEXES_PER_PAGE
    end = start + ENGLISH_INDEXES_PER_PAGE
    current_indexes = ENGLISH_INDEXES[start:end]
    total_indexes = len(ENGLISH_INDEXES)

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index_en:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"index_en_page:{page-1}"))
    if end < len(ENGLISH_INDEXES):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"index_en_page:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"📚 Choose an English index (Total: {total_indexes}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# الملاحة بين صفحات الفهارس
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

async def navigate_english_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split(":")[1])
    except Exception:
        await query.message.reply_text("❌ Error determining page.")
        return
    await show_english_index(update, context, page)

# -----------------------------
# البحث داخل الفهارس
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
    if index_key == "novels":
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

    await send_books_page(update, context, include_index_home=True)

async def search_by_english_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index_key = query.data.replace("index_en:", "")

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ Database not connected.")
        return

    keywords = []
    for name, key, kws in ENGLISH_INDEXES:
        if key == index_key:
            keywords = kws
            break

    if not keywords:
        await query.message.reply_text("❌ No keywords for this index.")
        return

    keywords = [normalize_text(remove_common_words(k)) for k in keywords]
    sql_condition = " OR ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])

    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {sql_condition}
            ORDER BY uploaded_at DESC;
        """)
    except Exception:
        await query.message.reply_text("❌ Error fetching books.")
        return

    if not books:
        await query.message.reply_text("❌ No books found for this index.")
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"English Index: {index_key}"
    context.user_data["is_index"] = True
    context.user_data["index_key"] = index_key

    await send_books_page(update, context, include_index_home=True)
