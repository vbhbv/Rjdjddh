import hashlib
import re
from typing import List
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_suggestions import send_search_suggestions
import logging

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# إعدادات عامة
# =========================
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و","في","من","إلى","عن","على","ب","ل","ا","أو","أن","إذا",
    "ما","هذا","هذه","ذلك","تلك","كان","قد","الذي","التي","هو","هي",
    "ف","ك","اى"
}

# =========================
# دوال التطبيع
# =========================
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower()
    text = text.replace("_"," ")
    text = text.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    text = text.replace("ى","ي").replace("ة","ه")
    text = text.replace("ـ","")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def remove_common_words(text: str) -> str:
    for w in ["كتاب","رواية","نسخة","جزء","طبعة","مجاني"]:
        text = text.replace(w,"")
    return text.strip()

def light_stem(word: str) -> str:
    for suf in ["ية","ات","ون","ين","ان","ه","ي"]:
        if word.endswith(suf) and len(word) > 4:
            word = word[:-len(suf)]
            break
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    return word

# =========================
# المرادفات
# =========================
SYNONYMS = {
    "فلسفة":["منطق","ميتافيزيقا"],
    "المهدي":["القائم","المنقذ"],
    "عدمية":["عبث","نيتشه"]
}

def expand_keywords_with_synonyms(words: List[str]) -> List[str]:
    out = set(words)
    for w in words:
        if w in SYNONYMS:
            out.update(SYNONYMS[w])
    return list(out)

# =========================
# عرض الكتب
# =========================
async def send_books_page(update, context, include_index_home=False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    stage = context.user_data.get("search_stage","")

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE

    keyboard = []
    for b in books[start:end]:
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    if include_index_home or context.user_data.get("is_index"):
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    text = f"📚 النتائج ({len(books)} كتاب)\n{stage}\nالصفحة {page+1}"
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)

# =========================
# البحث الذكي
# =========================
async def search_books(update, context):
    query = update.message.text.strip()
    conn = context.bot_data.get("db_conn")

    normalized = normalize_text(query)
    cleaned = normalize_text(remove_common_words(query))
    words = [w for w in cleaned.split() if w not in ARABIC_STOP_WORDS and len(w) > 2]
    stemmed = [light_stem(w) for w in words]
    expanded = expand_keywords_with_synonyms(stemmed)

    books = []
    stage = "❌ بدون نتائج"

    # ========= المرحلة 1: تطابق العبارة + AND =========
    try:
        and_like = " AND ".join([f"file_name ILIKE '%{w}%'" for w in words])
        books = await conn.fetch(f"""
            SELECT id,file_id,file_name,uploaded_at
            FROM books
            WHERE file_name ILIKE '%{cleaned}%'
               OR ({and_like})
            LIMIT 500;
        """)
        if books:
            stage = "🔍 تطابق العنوان (ذكي)"
    except:
        pass

    # ========= المرحلة 2: FTS موسع =========
    if not books and expanded:
        ts = " | ".join(expanded)
        books = await conn.fetch("""
            SELECT id,file_id,file_name,uploaded_at
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic',$1)
            ORDER BY ts_rank(to_tsvector('arabic',file_name),to_tsquery('arabic',$1)) DESC
            LIMIT 500;
        """, ts)
        if books:
            stage = "⭐ بحث دلالي موسع"

    # ========= المرحلة 3: اقتراحات =========
    if not books:
        await send_search_suggestions(update, context)
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = stage
    await send_books_page(update, context)

# =========================
# الأزرار
# =========================
async def handle_callbacks(update, context):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("file:"):
        key = q.data.split(":")[1]
        await q.message.reply_document(context.bot_data[f"file_{key}"])

    elif q.data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif q.data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif q.data == "home_index":
        from index_handler import show_index, show_index_en
        if context.user_data.get("current_index_type") == "en":
            await show_index_en(update, context)
        else:
            await show_index(update, context)
