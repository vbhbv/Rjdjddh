import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from search_handler import send_books_page

# ==================================================
# أدوات التطبيع
# ==================================================

COMMON_WORDS = {"كتاب", "نسخة", "مجموعة", "مجلد", "جزء"}

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def clean_keywords(words: List[str]) -> List[str]:
    result = []
    for w in words:
        w = normalize_text(w)
        for cw in COMMON_WORDS:
            w = w.replace(cw, "")
        if w:
            result.append(w)
    return result


# ==================================================
# نموذج الفهرس
# ==================================================

@dataclass(frozen=True)
class IndexItem:
    title: str
    key: str
    keywords: List[str]
    lang: str  # ar / en


# ==================================================
# تعريف الفهارس (نفسها لكن بشكل أنظف)
# ==================================================

INDEXES: List[IndexItem] = [

    # -------- عربي --------
    IndexItem("الروايات", "novels", ["رواية"], "ar"),
    IndexItem("قصص الأطفال", "children_stories", ["قصص", "أطفال", "حكاية", "مغامرة"], "ar"),

    # -------- English --------
    IndexItem("Novels", "novels_en", ["novel"], "en"),
    IndexItem("Children Stories", "children_stories_en", ["children", "story"], "en"),
]

INDEXES_PER_PAGE = 5


# ==================================================
# أدوات مساعدة
# ==================================================

def get_indexes_by_lang(lang: str) -> List[IndexItem]:
    return [i for i in INDEXES if i.lang == lang]

def get_index_by_key(key: str) -> IndexItem | None:
    for idx in INDEXES:
        if idx.key == key:
            return idx
    return None


# ==================================================
# عرض صفحات الفهارس
# ==================================================

async def show_index_page(
    update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    lang: str = "ar"
):
    indexes = get_indexes_by_lang(lang)

    start = page * INDEXES_PER_PAGE
    end = start + INDEXES_PER_PAGE
    page_items = indexes[start:end]

    keyboard = [
        [InlineKeyboardButton(i.title, callback_data=f"index:{i.key}")]
        for i in page_items
    ]

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("⬅️ السابق", callback_data=f"index_page:{page-1}:{lang}")
        )
    if end < len(indexes):
        nav.append(
            InlineKeyboardButton("التالي ➡️", callback_data=f"index_page:{page+1}:{lang}")
        )
    if nav:
        keyboard.append(nav)

    keyboard.append(
        [InlineKeyboardButton("📩 تواصل معنا", url="https://t.me/Boooksfreee1bot")]
    )

    text = f"📚 اختر الفهرس (عدد الفهارس: {len(indexes)})"
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, reply_markup=markup)


# ==================================================
# نقاط الدخول
# ==================================================

async def show_index(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "ar"
    await show_index_page(update, context, page, "ar")

async def show_index_en(update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    context.user_data["current_index_type"] = "en"
    await show_index_page(update, context, page, "en")


async def navigate_index_pages(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, page, lang = query.data.split(":")
        await show_index_page(update, context, int(page), lang)
    except Exception:
        await query.message.reply_text("❌ خطأ في التنقل بين الصفحات.")


# ==================================================
# البحث داخل فهرس
# ==================================================

async def search_by_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index_key = query.data.replace("index:", "")
    index_item = get_index_by_key(index_key)

    if not index_item:
        await query.message.reply_text("❌ فهرس غير معروف.")
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    keywords = clean_keywords(index_item.keywords)
    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية.")
        return

    # تحديد نوع الشرط
    joiner = " AND " if index_key in ("novels", "novels_en") else " OR "
    conditions = joiner.join(
        [f"LOWER(file_name) LIKE ${i+1}" for i in range(len(keywords))]
    )
    values = [f"%{k}%" for k in keywords]

    try:
        books = await conn.fetch(
            f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {conditions}
            ORDER BY uploaded_at DESC
            """,
            *values
        )
    except Exception:
        await query.message.reply_text("❌ خطأ أثناء البحث.")
        return

    if not books:
        await query.message.reply_text("❌ لا توجد نتائج.")
        return

    # حفظ الحالة
    context.user_data.update({
        "search_results": [dict(b) for b in books],
        "current_page": 0,
        "search_stage": f"فهرس: {index_item.title}",
        "is_index": True,
        "index_key": index_key,
        "current_index_type": index_item.lang
    })

    await send_books_page(update, context, include_index_home=True)
