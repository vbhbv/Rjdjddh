import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List
import os

# -----------------------------
# الإعدادات
# -----------------------------
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = text.replace("ـ", "")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def remove_common_words(text: str) -> str:
    for word in [
        "كتاب", "رواية", "نسخة", "مجموعة",
        "اريد", "جزء", "طبعة", "مجاني",
        "كبير", "صغير"
    ]:
        text = text.replace(word, "")
    return text.strip()

def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "ه"]
    for suf in suffixes:
        if word.endswith(suf) and len(word) > len(suf) + 2:
            word = word[:-len(suf)]
            break
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    return word

# -----------------------------
# المرادفات
# -----------------------------
SYNONYMS = {
    "مهندس": ["هندسة", "مقاول", "معماري"],
    "الهندسة": ["مهندس", "معمار", "بناء"],
    "المهدي": ["المنقذ", "القائم"],
    "عدمية": ["نيتشه", "موت", "عبث"],
    "دين": ["إسلام", "مسيحية", "يهودية", "فقه"],
    "فلسفة": ["منطق", "مفهوم", "متافيزيقا"]
}

def expand_keywords_with_synonyms(keywords: List[str]) -> List[str]:
    expanded = set(keywords)
    for k in keywords:
        if k in SYNONYMS:
            expanded.update(SYNONYMS[k])
    return list(expanded)

# -----------------------------
# إرسال النتائج
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1
    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE

    text = f"📚 النتائج ({len(books)} كتاب)\n"
    text += f"الصفحة {page + 1} من {total_pages}\n\n"

    keyboard = []

    for book in books[start:end]:
        key = hashlib.md5(book["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = book["file_id"]
        keyboard.append([
            InlineKeyboardButton(book["file_name"], callback_data=f"file:{key}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    cleaned = normalize_text(remove_common_words(query))
    words = cleaned.split()
    keywords = [w for w in words if w not in ARABIC_STOP_WORDS]

    expanded = expand_keywords_with_synonyms(keywords)
    stemmed = [light_stem(w) for w in expanded]

    ts_query = " & ".join(stemmed)

    try:
        books = await conn.fetch("""
            SELECT file_id, file_name
            FROM books
            WHERE to_tsvector('arabic', file_name)
            @@ to_tsquery('arabic', $1)
            LIMIT 200
        """, ts_query)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في البحث: {e}")
        return

    # ❌ لا نتائج → اقتراحات ذكية
    if not books:
        from search_suggestions import show_search_suggestions
        await show_search_suggestions(update, context, query)
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# callbacks
# -----------------------------
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(file_id)
        else:
            await query.message.reply_text("❌ الملف غير متوفر.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif data in ("home_index", "show_index"):
        from index_handler import show_index
        await show_index(update, context)
