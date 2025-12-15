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
MAX_RESULTS = 500

ARABIC_STOP_WORDS = {
    "و","في","من","الى","عن","على","ب","ل","ا","او","ان","اذا",
    "ما","هذا","هذه","ذلك","تلك","كان","قد","الذي","التي","هو","هي","ف","ك"
}

# =========================
# التطبيع
# =========================
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    text = text.replace("ى","ي").replace("ة","ه")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def remove_common_words(text: str) -> str:
    for w in ["كتاب","روايه","نسخه","طبعه","pdf","مجاني"]:
        text = text.replace(w,"")
    return text.strip()

def light_stem(word: str) -> str:
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    for suf in ["ات","ون","ين","ه","ي","ة"]:
        if word.endswith(suf) and len(word) > 3:
            word = word[:-len(suf)]
            break
    return word

# =========================
# إرسال النتائج
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home=False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page+1}\n\n"
    keyboard = []

    for b in current:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    if include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=markup)

# =========================
# البحث المصحح جذرياً
# =========================
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

    normalized = normalize_text(query)
    cleaned = normalize_text(remove_common_words(query))
    words = [w for w in cleaned.split() if w not in ARABIC_STOP_WORDS and len(w) > 2]
    stems = [light_stem(w) for w in words]

    if not stems:
        await send_search_suggestions(update, context)
        return

    ts_query = " & ".join(stems)

    try:
        books = await conn.fetch("""
            SELECT
                id,
                file_id,
                file_name,
                uploaded_at,

                -- 1️⃣ تطابق العبارة
                CASE
                    WHEN LOWER(file_name) LIKE '%' || $1 || '%' THEN 3
                    ELSE 0
                END AS phrase_boost,

                -- 2️⃣ عدد الكلمات المتطابقة
                (
                    SELECT COUNT(*)
                    FROM unnest(string_to_array($2, ' ')) w
                    WHERE LOWER(file_name) LIKE '%' || w || '%'
                ) AS word_hits,

                -- 3️⃣ ترتيب FTS
                ts_rank(
                    to_tsvector('arabic', file_name),
                    to_tsquery('arabic', $3)
                ) AS rank_score

            FROM books
            WHERE
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $3)
                OR LOWER(file_name) LIKE '%' || $1 || '%'

            ORDER BY
                phrase_boost DESC,
                word_hits DESC,
                rank_score DESC,
                LENGTH(file_name) ASC

            LIMIT 500;
        """, normalized, " ".join(words), ts_query)

    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ خطأ أثناء البحث.")
        return

    if not books:
        await send_search_suggestions(update, context)
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# =========================
# callbacks
# =========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("file:"):
        key = q.data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await q.message.reply_document(file_id)
        return

    if q.data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context, True)

    if q.data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context, True)

    if q.data == "home_index":
        from index_handler import show_index
        await show_index(update, context)
