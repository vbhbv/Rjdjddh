import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page  # دالة عرض الكتب كما هي

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
# الفهارس
# -----------------------------
INDEXES_AR = [
    ("الروايات", "novels", ["رواية"]),
    ("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"]),
    # أضف بقية الفهارس هنا...
]

INDEXES_EN = [
    ("Novels", "novels_en", ["novel"]),
    ("Children Stories", "children_stories_en", ["children", "story"]),
    # أضف بقية الفهارس هنا...
]

INDEXES_PER_PAGE = 5  # عدد الفهارس لكل صفحة

# -----------------------------
# عرض صفحة فهرس
# -----------------------------
async def show_index_page(update, context: ContextTypes.DEFAULT_TYPE, indexes, page: int = 0, index_type="ar"):
    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    current_indexes = indexes[start:end]
    total_indexes = len(indexes)

    # أزرار الفهارس
    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in current_indexes]

    # أزرار التنقل بين الصفحات
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page-1}:{index_type}"))
    if end < len(indexes):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}:{index_type}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    # زر التواصل ثابت
    keyboard.append([InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")])

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
    context.user_data["current_index_type"] = "ar"
    await show_index_page(update, context, INDEXES_AR, page, index_type="ar")

async def show_index_en(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "en"
    await show_index_page(update, context, INDEXES_EN, page, index_type="en")

# -----------------------------
# الملاحة بين صفحات الفهرس
# -----------------------------
async def navigate_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split(":")
        page = int(parts[1])
        index_type = parts[2] if len(parts) > 2 else "ar"
    except Exception:
        await query.message.reply_text("❌ خطأ في تحديد الصفحة.")
        return

    # اختر الفهرس المناسب
    if index_type == "en":
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

    # عرض الكتب مع زر العودة للفهرس
    await send_books_page(update, context, include_index_home=True)
