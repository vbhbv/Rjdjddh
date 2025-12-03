# search_handler.py

import hashlib
import math
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from typing import List, Dict, Any
import os

BOOKS_PER_PAGE = 10

# -----------------------------
# إعدادات المشرف
# -----------------------------
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# قاموس تحويل الجمع إلى المفرد
# -----------------------------
WORD_MAP = {
    "روايات": "رواية",
    "كتب": "كتاب",
    "مجلات": "مجلة",
    "قصص": "قصة"
}

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    words = text.split()
    normalized_words = [WORD_MAP.get(w, w) for w in words]
    return " ".join(normalized_words)

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
    return [w for w in words if len(w) >= 1]

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

# -----------------------------
# توسيع جذور خفيف
# -----------------------------
def expand_root(word: str) -> List[str]:
    variations = set()
    w = normalize_text(word)
    variations.add(w)
    if w.startswith("ال"):
        variations.add(w[2:])
    if w.endswith("ة"):
        variations.add(w[:-1])
    if w.endswith("ي"):
        variations.add(w[:-1])
    for suf in ("ون", "ين", "ات", "ان"):
        if w.endswith(suf):
            variations.add(w[:-len(suf)])
    return list(variations)

# -----------------------------
# دوال BM25
# -----------------------------
def compute_idf(N: int, df: int) -> float:
    return math.log((N - df + 0.5) / (df + 0.5) + 1.0)

def bm25_score_for_doc(doc_terms: List[str], query_terms: List[str], idf_map: Dict[str, float], avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    tf = {}
    for t in doc_terms:
        tf[t] = tf.get(t, 0) + 1
    dl = len(doc_terms)
    score = 0.0
    for q in query_terms:
        idf = idf_map.get(q, 0.0)
        f = tf.get(q, 0)
        if f == 0:
            continue
        denom = f + k1 * (1 - b + b * (dl / avgdl))
        numer = f * (k1 + 1)
        score += idf * (numer / denom)
    return score

# -----------------------------
# التقييم الهيوريستيكي
# -----------------------------
def heuristic_score(book_name: str, keywords: List[str]) -> int:
    score = 0
    name = normalize_text(book_name)
    title_words = name.split()
    normalized_query = " ".join(keywords)
    if normalized_query == name:
        score += 40
    elif normalized_query in name:
        score += 15
    for kw in keywords:
        roots = expand_root(kw)
        for w in title_words:
            for r in roots:
                if w.startswith(r):
                    score += 8
                elif r in w:
                    score += 5
        if kw in name:
            score += 10
    return score

# -----------------------------
# إشعار المشرف
# -----------------------------
async def notify_admin_search(context: ContextTypes.DEFAULT_TYPE, username: str, query: str, found: bool):
    if ADMIN_USER_ID == 0:
        return
    bot = context.bot
    status_text = "✅ تم العثور على نتائج" if found else "❌ لم يتم العثور على نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"
    message = f"🔔 قام المستخدم {username_text} بالبحث عن:\n`{query}`\nالحالة: {status_text}"
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to notify admin: {e}")

# -----------------------------
# إرسال صفحة النتائج
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "نتيجة البحث")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1
    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]
    if "بحث موسع" in search_stage:
        stage_note = "⚠️ نتائج بحث موسع"
    elif "تطابق" in search_stage:
        stage_note = "✅ نتائج دلالية"
    else:
        stage_note = search_stage
    text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []
    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الرئيسي
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    query = update.message.text.strip()
    if not query:
        return
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return
    normalized_query = normalize_text(remove_common_words(query))
    keywords = extract_keywords(normalized_query)
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords
    if not keywords:
        await update.message.reply_text("❌ لا يمكن البحث عن كلمات خالية.")
        return

    try:
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        candidates = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC
            LIMIT 150;
        """)
    except Exception:
        await update.message.reply_text("❌ حدث خطأ أثناء استدعاء قاعدة البيانات.")
        return

    if not candidates:
        try:
            or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
            candidates = await conn.fetch(f"""
                SELECT id, file_id, file_name, uploaded_at
                FROM books
                WHERE {or_conditions}
                ORDER BY uploaded_at DESC;
            """)
        except Exception:
            await update.message.reply_text("❌ حدث خطأ أثناء استدعاء قاعدة البيانات.")
            return

    try:
        N_row = await conn.fetchval("SELECT COUNT(*) FROM books;")
        N = int(N_row or 0) if N_row is not None else 1
    except Exception:
        N = 1

    idf_map = {}
    for k in keywords:
        try:
            df = await conn.fetchval(f"SELECT COUNT(*) FROM books WHERE LOWER(file_name) LIKE '%{get_db_safe_query(k)}%';")
            df = int(df or 0)
        except Exception:
            df = 0
        idf_map[k] = compute_idf(N, df)

    candidate_docs = []
    candidate_lens = []
    for c in candidates:
        name = normalize_text(c['file_name'] or "")
        terms = [w for w in re.sub(r'[^\w\s]', '', name).split() if w]
        candidate_docs.append((c, terms))
        candidate_lens.append(len(terms) or 1)
    avgdl = sum(candidate_lens) / len(candidate_lens) if candidate_lens else 1.0

    scored = []
    alpha, beta, gamma = 1.0, 0.7, 12.0
    query_terms_expanded = list(dict.fromkeys([k for k in keywords] + [r for k in keywords for r in expand_root(k)]))

    for (c, terms) in candidate_docs:
        idf_map_expanded = {qt: idf_map.get(qt, 0.0) for qt in query_terms_expanded}
        bm25_s = bm25_score_for_doc(terms, query_terms_expanded, idf_map_expanded, avgdl)
        heur = heuristic_score(c['file_name'] or "", keywords)
        full_bonus = gamma if normalized_query and normalized_query in normalize_text(c['file_name'] or "") else 0
        total_score = alpha * bm25_s + beta * heur + full_bonus
        if total_score > 0:
            d = dict(c)
            d['score'] = total_score
            scored.append(d)

    scored.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    found_results = bool(scored)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not scored:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = scored
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث محسّن (BM25 + heuristics)"
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    keywords = context.user_data.get("last_keywords")
    if not keywords or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return
    try:
        rows = await conn.fetch("SELECT id, file_id, file_name, uploaded_at FROM books;")
    except Exception:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return
    scored = []
    for r in rows:
        sc = heuristic_score(r['file_name'] or "", keywords)
        if sc > 0:
            d = dict(r)
            d['score'] = sc
            scored.append(d)
    scored.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    if not scored:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return
    context.user_data["search_results"] = scored
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (مشابه)"
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار التحميل
# -----------------------------
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            share_button = InlineKeyboardMarkup([[InlineKeyboardButton("📤 شارك البوت مع أصدقائك", switch_inline_query="")]])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=share_button)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
    elif data == "search_similar":
        await search_similar_books(update, context)
