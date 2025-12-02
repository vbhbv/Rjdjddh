import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os
import math
from collections import Counter

BOOKS_PER_PAGE = 10

# -----------------------------
# إعدادات المشرف
# -----------------------------

try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))  # معرف المشرف
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    if not text:
        return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

# -----------------------------
# TF-IDF + Cosine Similarity
# -----------------------------

def tokenize(text: str):
    return extract_keywords(normalize_text(remove_common_words(text)))

def compute_tf(words):
    count = Counter(words)
    total = len(words) or 1
    return {w: count[w] / total for w in count}

def compute_idf(documents):
    N = len(documents)
    idf = {}
    for doc in documents:
        for term in set(doc):
            idf[term] = idf.get(term, 0) + 1
    return {term: math.log(N / freq) for term, freq in idf.items()}

def compute_tfidf(words, idf):
    tf = compute_tf(words)
    return {term: tf.get(term, 0) * idf.get(term, 0) for term in idf}

def cosine_similarity(vec1, vec2):
    dot = sum(vec1.get(k, 0) * vec2.get(k, 0) for k in vec1)
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0
    return dot / (mag1 * mag2)

# -----------------------------
# إشعار المشرف
# -----------------------------

async def notify_admin_search(context, username: str, query: str, found: bool):
    if ADMIN_USER_ID == 0:
        return

    bot = context.bot
    status_text = "✅ نتائج" if found else "❌ لا يوجد نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"

    message = (
        f"🔔 قام المستخدم {username_text} بالبحث عن:\n"
        f"`{query}`\nالحالة: {status_text}"
    )
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except:
        pass

# -----------------------------
# إرسال صفحات الكتب
# -----------------------------

async def send_books_page(update, context):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    stage = context.user_data.get("search_stage", "")

    total_pages = max(1, (len(books) - 1) // BOOKS_PER_PAGE + 1)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = (
        f"📚 النتائج ({len(books)} كتاب)\n"
        f"{stage}\n"
        f"الصفحة {page + 1} من {total_pages}\n\n"
    )

    keyboard = []

    for b in current_books:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([
            InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))

    if nav:
        keyboard.append(nav)

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=markup)

# -----------------------------
# البحث الجديد (TF-IDF فقط)
# -----------------------------

async def search_books(update, context):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    # جلب كل الكتب
    books = await conn.fetch("SELECT id, file_id, file_name, uploaded_at FROM books;")

    if not books:
        await update.message.reply_text("❌ لا توجد كتب.")
        return

    # تجهيز النصوص
    query_tokens = tokenize(query)
    titles_tokens = [tokenize(book["file_name"]) for book in books]

    # حساب IDF
    idf = compute_idf(titles_tokens + [query_tokens])

    # متجه استعلام
    query_vec = compute_tfidf(query_tokens, idf)

    # حساب التشابه
    scored_books = []
    for book, tokens in zip(books, titles_tokens):
        book_vec = compute_tfidf(tokens, idf)
        score = cosine_similarity(query_vec, book_vec)
        bd = dict(book)
        bd["score"] = score
        scored_books.append(bd)

    # فرز النتائج
    scored_books.sort(key=lambda b: (b["score"], b["uploaded_at"]), reverse=True)

    found = any(b["score"] > 0.01 for b in scored_books)

    # إشعار المشرف
    await notify_admin_search(context, update.effective_user.username, query, found)

    if not found:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 بحث مشابه", callback_data="search_similar")]
        ])
        await update.message.reply_text(
            f"❌ لا توجد نتائج لـ: {query}", reply_markup=keyboard)
        return

    # حفظ وإرسال
    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "🔎 بحث ذكاء اصطناعي (TF-IDF)"

    await send_books_page(update, context)

# -----------------------------
# بحث مشابه
# -----------------------------

async def search_similar_books(update, context):
    conn = context.bot_data.get("db_conn")
    last_query = context.user_data.get("last_keywords")

    if not conn:
        await update.callback_query.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    books = await conn.fetch("SELECT id, file_id, file_name, uploaded_at FROM books;")

    titles_tokens = [tokenize(book["file_name"]) for book in books]

    idf = compute_idf(titles_tokens)
    query_vec = compute_tfidf(last_query, idf)

    scored_books = []
    for book, tokens in zip(books, titles_tokens):
        book_vec = compute_tfidf(tokens, idf)
        score = cosine_similarity(query_vec, book_vec)
        bd = dict(book)
        bd["score"] = score
        scored_books.append(bd)

    scored_books.sort(key=lambda b: (b["score"], b["uploaded_at"]), reverse=True)

    if not any(b["score"] > 0.01 for b in scored_books):
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "🔎 بحث مشابه (TF-IDF)"

    await send_books_page(update, context)

# -----------------------------
# التعامل مع الكولباك
# -----------------------------

async def handle_callbacks(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            share = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 شارك البوت", switch_inline_query="")]
            ])
            await query.message.reply_document(
                document=file_id, caption=caption, reply_markup=share
            )
        else:
            await query.message.reply_text("❌ الملف غير موجود.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
    elif data == "search_similar":
        await search_similar_books(update, context)
