import hashlib
import re
import os
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_suggestions import send_search_suggestions

# =================================
# الإعدادات
# =================================
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و","في","من","إلى","عن","على","ب","ل","ا","أو","أن","إذا",
    "ما","هذا","هذه","ذلك","تلك","كان","قد","الذي","التي","هو","هي",
    "ف","ك","اى"
}

# =================================
# التطبيع (سريع وخفيف)
# =================================
def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    text = text.replace("ى","ي").replace("ة","ه")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def extract_keywords(text: str) -> List[str]:
    words = normalize(text).split()
    return [w for w in words if w not in ARABIC_STOP_WORDS and len(w) > 1]

# =================================
# إرسال صفحة النتائج
# =================================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current = books[start:end]

    total_pages = max(1, (len(books)-1)//BOOKS_PER_PAGE + 1)

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page+1} من {total_pages}\n\n"
    keyboard = []

    for b in current:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([
            InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🏠 الفهرس", callback_data="home_index")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=markup)

# =================================
# البحث الرئيسي (سريع + ذكي)
# =================================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة")
        return

    keywords = extract_keywords(query)
    context.user_data["last_query"] = query

    if not keywords:
        await send_search_suggestions(update, context)
        return

    ts_query = " & ".join(keywords)

    try:
        rows = await conn.fetch("""
            SELECT file_id, file_name
            FROM books
            WHERE to_tsvector('arabic', file_name)
                  @@ to_tsquery('arabic', $1)
            ORDER BY ts_rank(
                to_tsvector('arabic', file_name),
                to_tsquery('arabic', $1)
            ) DESC
            LIMIT 200;
        """, ts_query)
    except Exception:
        await update.message.reply_text("❌ خطأ في البحث")
        return

    if not rows:
        await send_search_suggestions(update, context)
        return

    context.user_data["search_results"] = [dict(r) for r in rows]
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# =================================
# أزرار التحكّم
# =================================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await q.message.reply_document(
                document=file_id,
                caption="📚 @boooksfree1bot"
            )
        else:
            await q.message.reply_text("❌ الملف غير متوفر")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif data == "home_index":
        from index_handler import show_index
        await show_index(update, context)
