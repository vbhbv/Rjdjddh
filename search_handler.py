import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os

BOOKS_PER_PAGE = 10

try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0


# -----------------------------------------------------------
# 1) تطبيع متقدم للنصوص (أقوى من السابق)
# -----------------------------------------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower()
    replacements = {
        "أ": "ا", "إ": "ا", "آ": "ا",
        "ة": "ه", "ى": "ي", "_": " ",
        "ؤ": "و", "ئ": "ي"
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r"\s+", " ", text).strip()
    return text


# -----------------------------------------------------------
# 2) خوارزمية جمع → مفرد محسّنة (Rule-based)
# -----------------------------------------------------------
def singularize(word: str) -> str:
    word = normalize_text(word)

    rules = [
        (r"(.*)ات$", r"\1ه"),
        (r"(.*)ون$", r"\1"),
        (r"(.*)ين$", r"\1"),
        (r"(.*)ان$", r"\1"),
        (r"(.*)ات$", r"\1"),
    ]

    for pat, repl in rules:
        if re.match(pat, word):
            return re.sub(pat, repl, word)

    return word


# -----------------------------------------------------------
# 3) Light Root Expander (مدمج – سريع جداً)
# -----------------------------------------------------------
def expand_root(word: str) -> List[str]:
    word = normalize_text(word)
    roots = {word, singularize(word)}

    suffixes = ["يه", "ون", "ات", "ان", "ين", "ه"]
    for s in suffixes:
        if word.endswith(s):
            roots.add(word[:-len(s)])

    if word.startswith("ال"):
        roots.add(word[2:])

    return list(roots)


# -----------------------------------------------------------
# 4) Similarity Matching (تصحيح تلقائي بسيط)
# -----------------------------------------------------------
def char_similarity(a: str, b: str) -> float:
    matches = sum(1 for x, y in zip(a, b) if x == y)
    return matches / max(len(a), len(b), 1)


# -----------------------------------------------------------
# 5) استخراج الكلمات المفتاحية
# -----------------------------------------------------------
def extract_keywords(text: str) -> List[str]:
    if not text:
        return []

    clean = re.sub(r"[^\w\s]", "", text)
    words = clean.split()

    final = []
    for w in words:
        w = singularize(w)
        if len(w) >= 2:
            final.append(w)
    return final


# -----------------------------------------------------------
# 6) تقييم ذكي (Hybrid Scoring)
# -----------------------------------------------------------
def calculate_score(book_name: str, keywords: List[str]) -> int:
    name = normalize_text(book_name)
    parts = name.split()
    score = 0

    for kw in keywords:
        roots = expand_root(kw)
        for r in roots:
            if name == r:
                score += 25
            if r in name:
                score += 12
            for w in parts:
                if w.startswith(r):
                    score += 10
                elif char_similarity(w, r) >= 0.75:
                    score += 8

        if kw in name:
            score += 15

    return score


# -----------------------------------------------------------
# إعلام المشرف
# -----------------------------------------------------------
async def notify_admin_search(context, username, query, found):
    if ADMIN_USER_ID == 0:
        return
    try:
        msg = (
            f"🔔 بحث جديد:\n"
            f"👤 المستخدم: @{username if username else 'بدون'}\n"
            f"🔎 البحث: `{query}`\n"
            f"📌 الحالة: {'نتائج موجودة' if found else 'لا توجد نتائج'}"
        )
        await context.bot.send_message(ADMIN_USER_ID, msg, parse_mode="Markdown")
    except:
        pass


# -----------------------------------------------------------
# إرسال صفحة الكتب
# -----------------------------------------------------------
async def send_books_page(update, context):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    total_pages = max((len(books) - 1) // BOOKS_PER_PAGE + 1, 1)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current = books[start:end]

    txt = f"📚 عدد النتائج: {len(books)}\n📖 الصفحة {page+1}/{total_pages}\n\n"

    keyboard = []
    for b in current:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(txt, reply_markup=markup)
    else:
        await update.callback_query.message.edit_text(txt, reply_markup=markup)


# -----------------------------------------------------------
# البحث الرئيسي (مطوّر)
# -----------------------------------------------------------
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

    normalized = normalize_text(query)
    keywords = extract_keywords(normalized)

    if not keywords:
        await update.message.reply_text("❌ أدخل كلمة مفيدة للبحث.")
        return

    # LIKE Query
    like_parts = [f"LOWER(file_name) LIKE '%{k}%'" for k in keywords]
    where_clause = " OR ".join(like_parts)

    try:
        rows = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at 
            FROM books
            WHERE {where_clause}
        """)
    except:
        await update.message.reply_text("❌ خطأ أثناء البحث.")
        return

    # Scoring
    scored = []
    for r in rows:
        s = calculate_score(r["file_name"], keywords)
        if s > 0:
            d = dict(r)
            d["score"] = s
            scored.append(d)

    scored.sort(key=lambda x: (x["score"], x["uploaded_at"]), reverse=True)

    await notify_admin_search(context, update.effective_user.username, query, bool(scored))

    if not scored:
        await update.message.reply_text("❌ لا توجد نتائج.\nجرّب كلمة مشابهة.")
        return

    context.user_data["search_results"] = scored
    context.user_data["current_page"] = 0

    await send_books_page(update, context)


# -----------------------------------------------------------
# البحث عن كتب مشابهة
# -----------------------------------------------------------
async def search_similar_books(update, context):
    keywords = context.user_data.get("last_keywords")
    if not keywords:
        await update.callback_query.message.reply_text("❌ لا يوجد بحث سابق.")
        return
    await search_books(update.callback_query, context)


# -----------------------------------------------------------
# التعامل مع أزرار البوت
# -----------------------------------------------------------
async def handle_callbacks(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if not file_id:
            await q.message.reply_text("❌ الملف غير متاح.")
            return
        await q.message.reply_document(
            document=file_id,
            caption="📥 تم التحميل عبر @boooksfree1bot",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 شارك البوت", switch_inline_query="")]
            ])
        )

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif data == "search_similar":
        await search_similar_books(update, context)
