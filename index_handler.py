# index_handler.py
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page

def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower().replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    if not text: return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

# -----------------------------
# قائمة الفهارس
# -----------------------------
INDEXES = [
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
    ("الأدب", "literature", ["أدب", "رواية", "قصة", "مقال"]),
    ("علم الاجتماع", "sociology", ["علم الاجتماع", "مجتمع", "ثقافة", "علاقات"]),
    ("التكنولوجيا", "technology", ["تكنولوجيا", "روبوت", "ذكاء اصطناعي", "تقنية"]),
    ("الهندسة", "engineering", ["هندسة", "ميكانيكا", "كهرباء", "مدني"]),
    ("التعليم", "education", ["تعليم", "مدرسة", "جامعة", "تدريس"]),
    ("اللغات", "languages", ["لغة", "تحدث", "ترجمة", "قاموس"]),
    ("الأساطير", "mythology", ["أسطورة", "خرافة", "أساطير", "أبطال"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"])
]

# -----------------------------
# إرسال صفحة الفهرس مع زر العودة للواجهة
# -----------------------------
async def send_index_page(update, context: ContextTypes.DEFAULT_TYPE):
    page = context.user_data.get("index_page", 0)
    start = page * 10
    end = start + 10
    current_indexes = INDEXES[start:end]

    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    nav_buttons = []
    if start > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="index_prev"))
    if end < len(INDEXES):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="index_next"))
    # زر العودة للفهرس
    nav_buttons.append(InlineKeyboardButton("🏠 العودة للفهرس", callback_data="show_index"))
    keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    query = update.callback_query
    text = "📚 اختر الفهرس المطلوب (مظهر مختلف عن البحث العادي):"
    if query:
        await query.answer()
        await query.message.edit_text(text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# بدء عرض الفهرس
# -----------------------------
async def show_index(update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["index_page"] = 0
    await send_index_page(update, context)

# -----------------------------
# التعامل مع أزرار الملاحة للفهرس
# -----------------------------
async def handle_index_navigation(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = context.user_data.get("index_page", 0)

    if query.data == "index_next":
        context.user_data["index_page"] = page + 1
    elif query.data == "index_prev":
        context.user_data["index_page"] = page - 1
    elif query.data == "show_index":
        context.user_data["index_page"] = 0

    await send_index_page(update, context)

# -----------------------------
# البحث عبر الفهرس وتحميل الكتب
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
    or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])

    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
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
    await send_books_page(update, context)
