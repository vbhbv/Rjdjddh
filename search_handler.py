import hashlib
import re
from typing import List
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_suggestions import send_search_suggestions
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOOKS_PER_PAGE = 10
MAX_RESULTS = 500

ARABIC_STOP_WORDS = {
    "و","في","من","إلى","عن","على","ب","ل","ا","أو","أن","إذا","ما","هذا",
    "هذه","ذلك","تلك","كان","قد","الذي","التي","هو","هي","ف","ك","اى"
}

# =========================
# Normalization
# =========================
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    text = text.replace("ى","ي").replace("ة","ه")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def light_stem(word: str) -> str:
    for suf in ["يات","ات","ون","ين","ه","ي","ة"]:
        if word.endswith(suf) and len(word) > 3:
            return word[:-len(suf)]
    if word.startswith("ال") and len(word) > 3:
        return word[2:]
    return word

# =========================
# Pagination
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home=False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    keyboard = []
    for b in current_books:
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

    if include_index_home or context.user_data.get("is_index"):
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    text = f"📚 النتائج: {len(books)} كتاب\nالصفحة {page+1}"

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# =========================
# SEARCH ENGINE (FIXED)
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    nq = normalize_text(query)

    words = [light_stem(w) for w in nq.split() if w not in ARABIC_STOP_WORDS and len(w) > 1]
    ts_and = " & ".join(words)
    ts_or = " | ".join(words)

    books = []

    # =======================
    # 1️⃣ Exact Phrase BOOST
    # =======================
    books = await conn.fetch("""
        SELECT id, file_id, file_name, uploaded_at,
        1000 AS score
        FROM books
        WHERE LOWER(file_name) LIKE $1
        ORDER BY uploaded_at DESC
        LIMIT 100
    """, f"%{nq}%")

    # =======================
    # 2️⃣ FTS AND (BOOSTED)
    # =======================
    if len(books) < MAX_RESULTS and ts_and:
        rows = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at,
            ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) * 100 AS score
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            ORDER BY score DESC
            LIMIT $2
        """, ts_and, MAX_RESULTS)
        books.extend(rows)

    # =======================
    # 3️⃣ FTS OR (LOWER)
    # =======================
    if len(books) < MAX_RESULTS and ts_or:
        rows = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at,
            ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) * 10 AS score
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            ORDER BY score DESC
            LIMIT $2
        """, ts_or, MAX_RESULTS)
        books.extend(rows)

    if not books:
        await send_search_suggestions(update, context)
        return

    # =======================
    # 🧠 FINAL SORT & UNIQUE
    # =======================
    unique = {}
    for b in books:
        unique[b["file_id"]] = b

    final = sorted(unique.values(), key=lambda x: (-x["score"], -x["uploaded_at"].timestamp()))
    context.user_data["search_results"] = [dict(b) for b in final[:MAX_RESULTS]]
    context.user_data["current_page"] = 0

    await send_books_page(update, context)

# =========================
# CALLBACKS
# =========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data.startswith("file:"):
        key = q.data.split(":")[1]
        fid = context.bot_data.get(f"file_{key}")
        await q.message.reply_document(fid)

    elif q.data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif q.data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif q.data == "home_index":
        from index_handler import show_index
        await show_index(update, context)
