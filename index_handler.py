# index_handler.py

import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page  # استخدام نفس عرض صفحات البحث العادي

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
# قائمة الفهارس الموسعة - 54 مجال مع الطب والطب البديل
# -----------------------------
INDEXES = [
    ("الروايات", "novels", ["رواية"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"]),
    ("الخيال العلمي", "sci_fi", ["خيال", "علمي", "فضاء", "مستقبل"]),
    ("القصص البوليسية", "detective_stories", ["جريمة", "بوليسي", "تحقيق", "قضية"]),
    ("الروايات التاريخية", "historical_novels", ["تاريخ", "رواية", "ملوك", "حروب"]),
    ("الروايات الرومانسية", "romance_novels", ["رومانسية", "حب", "عاطفة", "عشق"]),
    ("الروايات النفسية", "psychological_novels", ["نفسية", "تحليل", "سلوك", "عقل"]),
    ("قواعد اللغة العربية", "arabic_grammar", ["قواعد", "نحو", "صرف", "إملاء"]),
    ("الشعر", "poetry", ["شاعر", "قصيدة", "ديوان", "معلقات"]),
    ("النقد الأدبي", "literary_criticism", ["نقد", "تحليل", "أدب", "بلاغة"]),
    ("الأدب العالمي", "world_literature", ["أدب", "رواية", "كتّاب"]),
    ("الفيزياء", "physics", ["فيزياء", "طاقة", "كوانتم", "ميكانيكا"]),
    ("الكيمياء", "chemistry", ["كيمياء", "تفاعل", "مركب", "عنصر"]),
    ("الرياضيات", "math", ["رياضيات", "جبر", "هندسة", "إحصاء"]),
    ("الفلسفة", "philosophy", ["فلسفة", "ميتافيزيقيا", "منطق", "أخلاق"]),
    ("علم النفس", "psychology", ["علم النفس", "تحليل نفسي", "سلوك", "عقل"]),
    ("علم الاجتماع", "sociology", ["علم الاجتماع", "مجتمع", "ثقافة", "علاقات"]),
    ("التاريخ", "history", ["تاريخ", "حضارة", "عصور", "ملوك", "حروب"]),
    ("الجغرافيا", "geography", ["جغرافيا", "خرائط", "مناخ", "بيئة"]),
    ("السياسة", "politics", ["سياسة", "حكومة", "برلمان", "دولة"]),
    ("الاقتصاد", "economics", ["اقتصاد", "مال", "تجارة", "سوق", "استثمار"]),
    ("البرمجة", "programming", ["برمجة", "كود", "python", "java"]),
    ("الهندسة", "engineering", ["هندسة", "ميكانيكا", "كهرباء", "مدني"]),
    ("التكنولوجيا", "technology", ["تكنولوجيا", "روبوت", "ذكاء اصطناعي"]),
    ("التعليم", "education", ["تعليم", "مدرسة", "جامعة", "تدريس"]),
    ("اللغات", "languages", ["لغة", "تحدث", "ترجمة", "قاموس"]),
    ("الطب", "medicine", ["طب", "دواء", "تشخيص", "علاج"]),
    ("صيدلة", "pharmacy", ["صيدلة", "دواء", "علاج", "عقاقير"]),
    ("طب أسنان", "dentistry", ["أسنان", "طب", "تقويم", "جراحة"]),
    ("أعشاب طبيعية", "herbal_medicine", ["أعشاب", "طبيعية", "علاج", "صحة"]),
    ("بهارات", "spices", ["بهارات", "توابل", "نكهات", "طبخ"]),
    ("الطبخ", "cooking", ["طبخ", "وصفات", "اكل", "مطبخ"]),
    ("السفر", "travel", ["سفر", "رحلة", "دليل", "سياحة"]),
    ("الفنون", "arts", ["فن", "رسم", "موسيقى", "لوحة"]),
    ("التصميم", "design", ["تصميم", "ديكور", "جرافيك", "ابداع"]),
    ("الدين", "religion", ["دين", "اسلام", "مسيحية", "يهودية"]),
    ("الرياضة", "sports", ["رياضة", "كرة", "سباق", "تمارين"]),
    ("الأساطير", "mythology", ["أسطورة", "خرافة", "أساطير", "أبطال"]),
    ("الأبراج", "horoscopes", ["برج", "فلك", "تنجيم", "أبراج"]),
    ("علم الفلك", "astronomy", ["فلك", "نجوم", "كواكب", "فضاء"]),
    ("الصحة النفسية", "mental_health", ["عقل", "سعادة", "راحة", "توازن"]),
    ("التحليل المالي", "finance", ["مال", "استثمار", "سوق", "تحليل"]),
    ("الموسيقى", "music", ["موسيقى", "آلة", "نغم", "أغاني"]),
    ("الرسم", "drawing", ["رسم", "لوحة", "فن", "تلوين"]),
    ("السينما", "cinema", ["فيلم", "سينما", "مخرج", "عرض"]),
    ("التصوير الفوتوغرافي", "photography", ["تصوير", "كاميرا", "عدسة"]),
    ("الألعاب", "games", ["لعبة", "video game", "مسابقة", "مرح"]),
    ("السيارات", "cars", ["سيارة", "محرك", "قيادة", "طرقات"]),
    ("الدعم التقني", "tech_support", ["تقني", "دعم", "حساب", "حل"]),
    ("الذكاء الاصطناعي", "ai", ["ذكاء", "اصطناعي", "روبوت"]),
    ("الموسيقى الكلاسيكية", "classical_music", ["موسيقى", "كلاسيك", "أوركسترا", "فن"]),
    ("الخيال والفانتازيا", "fantasy", ["خيال", "سحر", "عالم", "مغامرة"]),
]

# -----------------------------
# عرض الفهرس بصفحات 10 عناصر
# -----------------------------
INDEXES_PER_PAGE = 10

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
    text = f"📚 اختر الفهرس الذي تريد استعراضه (عدد الفهارس: {total_indexes}):"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
        await update.callback_query.answer()
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

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
# البحث داخل الفهرس وعرض الكتب مع زر العودة دائمًا
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

    # البحث صارم فقط للروايات، باقي الأقسام OR
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

    # زر العودة للفهرس ثابت مهما كانت الصفحة
    await send_books_page(update, context, include_index_home=True)
