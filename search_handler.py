import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os
import math

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
# معلمات BM25 وخيارات البحث
# -----------------------------
BM25_K1 = 1.2
BM25_B = 0.75
MIN_SCORE = 1.0        # الحد الأدنى للنقطة ليُعرض الكتاب (يمكنك تغييره)
MAX_FETCH = 1000       # أقصى عدد سجلات نجلبها من قاعدة البيانات للتقييم المحلي (لحماية الأداء)

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
    # تحويل الجمع إلى مفرد للكلمات الموجودة في القاموس
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
    return [w for w in words if len(w) >= 2]  # دعم الكلمات القصيرة

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

# -----------------------------
# توسيع الجذر (Root Expansion) -- مختصر وخفيف
# -----------------------------
def expand_root(word: str) -> List[str]:
    variations = set()
    word = normalize_text(word)
    variations.add(word)
    # بعض اللواحق الشائعة للتوسيع الخفيف
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "اتي"]
    for suf in suffixes:
        if word.endswith(suf) and len(word) > len(suf):
            variations.add(word[:-len(suf)])
    if word.startswith("ال") and len(word) > 2:
        variations.add(word[2:])
    # إرجاع تنوعات قصيرة لتطابق أفضل لكن ليس مبالغًا (لحماية الأداء)
    return list(variations)

# -----------------------------
# دالة BM25 خفيفة تعمل على عنوان الكتاب فقط
# -----------------------------
def compute_bm25_for_corpus(corpus_titles: List[str], keywords: List[str]) -> Dict[int, float]:
    """
    حساب نقاط BM25 لكل مستند (index في corpus_titles).
    نُستخدم حصص محلية (tf داخل العنوان، df = عدد العناوين التي تحتوي المصطلح).
    """
    N = len(corpus_titles)
    if N == 0:
        return {}

    # نفصل الكلمات لكل عنوان ونحسب الطول
    tokenized = [normalize_text(title).split() for title in corpus_titles]
    doc_lens = [len(toks) for toks in tokenized]
    avgdl = sum(doc_lens) / N if N > 0 else 0.0

    # حساب df لكل كلمة في keywords (داخل هذه العناوين المجلوبة)
    df: Dict[str, int] = {}
    # لتحسين المطابقة نوسع جذر كل كلمة ونعتبر أي تطابق مع أي تنويعة كوجود
    for kw in keywords:
        kw_roots = set(expand_root(kw))
        cnt = 0
        for toks in tokenized:
            found = False
            for t in toks:
                if any(root == t or t.startswith(root) for root in kw_roots):
                    found = True
                    break
            if found:
                cnt += 1
        df[kw] = max(1, cnt)  # تجنب الصفر لتفادي القسمة على صفر

    # حساب bm25 لكل وثيقة
    scores: Dict[int, float] = {}
    for idx, toks in enumerate(tokenized):
        score = 0.0
        dl = doc_lens[idx] if doc_lens[idx] > 0 else 1
        for kw in keywords:
            kw_roots = set(expand_root(kw))
            # tf = عدد مرات ظهور أي من تنويعات الجذر في المستند
            tf = 0
            for t in toks:
                if any(root == t or t.startswith(root) for root in kw_roots):
                    tf += 1
            if tf == 0:
                continue
            # idf تقريبي
            idf = math.log((N - df.get(kw, 1) + 0.5) / (df.get(kw, 1) + 0.5) + 1)
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * (dl / avgdl)) if avgdl > 0 else tf + BM25_K1
            score += idf * ((tf * (BM25_K1 + 1)) / denom)
        scores[idx] = score
    return scores

# -----------------------------
# دالة التقييم (القديمة) - خفيفة
# -----------------------------
def heuristic_score(title: str, keywords: List[str], normalized_query: str) -> float:
    """التقييم الوزني القديم المختصر (مطابقات حرفية، بداية كلمة، احتواء)."""
    score = 0.0
    name = normalize_text(title)
    # التطابق الحرفي الكامل أو عبارة
    if normalized_query == name:
        score += 50
    elif normalized_query in name:
        score += 20

    words_in_name = name.split()
    for kw in keywords:
        roots = expand_root(kw)
        # نقاط عند التطابق المباشر أو بداية الكلمة
        for root in roots:
            for w in words_in_name:
                if w.startswith(root):
                    score += 6
                elif root in w:
                    score += 4
        # زيادة نقاط إذا تطابقت الكلمة بالكامل
        if kw in name:
            score += 10
    return score

# -----------------------------
# دمج الدرجات: bm25 + heuristic
# -----------------------------
def combined_score(bm25_val: float, heur: float, weight_bm25: float = 0.7) -> float:
    return weight_bm25 * bm25_val + (1 - weight_bm25) * heur

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
# إرسال صفحة الكتب (كما كان)
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "بحث موسع" in search_stage:
        stage_note = "⚠️ نتائج بحث موسع (بحثنا بالكلمات المفتاحية)"
    elif "تطابق جميع الكلمات" in search_stage:
        stage_note = "✅ نتائج دلالية (تطابق جميع كلماتك)"
    else:
        stage_note = "✅ نتائج مطابقة (تطابق العبارة كاملة)"

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
# البحث المحسن (المدمج)
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

    # تطبيع واستخرج كلمات البحث
    normalized_query = normalize_text(remove_common_words(query))
    keywords = extract_keywords(normalized_query)
    # إذا المستخدم كتب عبارة كاملة طويلة نضيفها كمرادف للكلمات
    if normalized_query and normalized_query not in keywords:
        # لو العبارة أكثر من كلمة، ضمّنها كـ keyword واحد لزيادة دقة العبارة
        if len(normalized_query.split()) > 1:
            keywords.insert(0, normalized_query)

    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords

    if not keywords:
        await update.message.reply_text("❌ لا يمكن البحث عن كلمات قصيرة جدًا.")
        return

    # المرحلة الأولى: استعلام سريع محدود لتصفية المرشحين
    try:
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC
            LIMIT {MAX_FETCH};
        """)
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    # إن لم نجد شيء، نجرب بحث أوسع (نفس الاستعلام لكن بدون LIMIT قد يكون خطر لذا نحافظ على LIMIT)
    if not books:
        try:
            books = await conn.fetch(f"""
                SELECT id, file_id, file_name, uploaded_at
                FROM books
                WHERE {" OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])}
                ORDER BY uploaded_at DESC
                LIMIT {MAX_FETCH};
            """)
        except Exception as e:
            await update.message.reply_text("❌ حدث خطأ في البحث.")
            return

    found_results = bool(books)

    # نحضر العناوين كقائمة للمصحف BM25 المحلي
    corpus_titles = [b['file_name'] for b in books]
    bm25_scores = compute_bm25_for_corpus(corpus_titles, keywords)

    # الآن نحسب الدرجة المركبة لكل كتاب
    scored_books = []
    for idx, book in enumerate(books):
        heur = heuristic_score(book['file_name'], keywords, normalized_query)
        bm25_val = bm25_scores.get(idx, 0.0)
        total = combined_score(bm25_val, heur, weight_bm25=0.7)
        # تطبيق الحد MIN_SCORE لإخراج النتائج الضعيفة
        if total >= MIN_SCORE:
            book_dict = dict(book)
            book_dict['score'] = total
            scored_books.append(book_dict)

    # رتب النتائج نهائيًا
    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)

    await notify_admin_search(context, update.effective_user.username, query, bool(scored_books))

    if not scored_books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث محسن (BM25+جذر)"
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة (يعتمد نفس الميكانيك)
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    keywords = context.user_data.get("last_keywords")
    if not keywords or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    try:
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC
            LIMIT {MAX_FETCH};
        """)
    except Exception as e:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    corpus_titles = [b['file_name'] for b in books]
    bm25_scores = compute_bm25_for_corpus(corpus_titles, keywords)

    scored_books = []
    for idx, book in enumerate(books):
        heur = heuristic_score(book['file_name'], keywords, context.user_data.get("last_query", ""))
        bm25_val = bm25_scores.get(idx, 0.0)
        total = combined_score(bm25_val, heur, weight_bm25=0.7)
        if total >= MIN_SCORE:
            book_dict = dict(book)
            book_dict['score'] = total
            scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    if not scored_books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (مشابه)"
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار الكتب والمشاركة
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
            share_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 شارك البوت مع أصدقائك", switch_inline_query="")]
            ])
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
