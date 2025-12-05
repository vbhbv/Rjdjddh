import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os
import asyncio
import pyarabic.araby as araby
from unidecode import unidecode

# -----------------------------
# الإعدادات وقائمة Stop Words
# -----------------------------
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

# إعدادات المشرف
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف المتقدم
# -----------------------------
def normalize_text(text: str) -> str:
    if not text: return ""
    text = str(text).lower()
    text = unidecode(text)
    text = araby.strip_tashkeel(text)
    text = araby.normalize_hamza(text)
    text = text.replace("ـ", "")
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_common_words(text: str) -> str:
    if not text: return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء", "طبعة", "مجاني", "كبير", "صغير"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    if not text: return []
    clean_text = normalize_text(text)
    words = clean_text.split()
    keywords = [w for w in words if w not in ARABIC_STOP_WORDS and len(w) >= 1]
    stop_words_for_search = [w for w in words if w in ARABIC_STOP_WORDS]
    return list(set(keywords + stop_words_for_search))

def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "ه"]
    for suf in suffixes:
        if word.endswith(suf) and len(word) > len(suf) + 2:
            word = word[:-len(suf)]
            break
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    return word if word else ""

# -----------------------------
# المرادفات لتحسين نتائج البحث
# -----------------------------
SYNONYMS = {
    "مهندس": ["هندسة", "مقاول", "معماري"],
    "الهندسة": ["مهندس", "معمار", "بناء"],
    "المهدي": ["المنقذ", "القائم"],
    "عدمية": ["نيتشه", "موت", "عبث"],
    "دين": ["إسلام", "مسيحية", "يهودية", "فقه"],
    "فلسفة": ["منطق", "مفهوم", "متافيزيقا"],
    "صوفية": ["تصوف", "طرق صوفية", "الأولياء", "روحانية"]
}

def expand_keywords_with_synonyms(keywords: List[str]) -> List[str]:
    expanded = set(keywords)
    for k in keywords:
        if k in SYNONYMS:
            expanded.update(SYNONYMS[k])
    return list(expanded)

# -----------------------------
# تقييم النتائج بالكلمات القصيرة والطويلة
# -----------------------------
def calculate_score(book: Dict[str, Any], query_keywords: List[str], normalized_query: str) -> int:
    score = 0
    book_name = normalize_text(book.get('file_name', ''))

    if normalized_query == book_name:
        score += 200
    elif normalized_query in book_name:
        score += 100

    title_words = book_name.split()
    for k in query_keywords:
        k_len = len(k)
        is_significant_short = k_len <= 3 and k not in ARABIC_STOP_WORDS
        base_match_score = 30 if k_len > 3 else 20
        base_stem_score = 15 if k_len > 3 else 10
        k_stem = light_stem(k)
        if not k_stem: continue

        for t_word in title_words:
            t_stem = light_stem(t_word)
            if t_stem.startswith(k_stem) and len(k_stem) >= 2:
                score += base_match_score * 2
            elif k_stem in t_stem:
                score += base_stem_score
            elif k in t_word:
                score += 5
            if is_significant_short and k == t_word:
                score += 50
    return score

# -----------------------------
# إشعار المشرف
# -----------------------------
async def notify_admin_search(context: ContextTypes.DEFAULT_TYPE, username: str, query: str, found: bool):
    if ADMIN_USER_ID == 0: return
    bot = context.bot
    status_text = "✅ تم العثور على نتائج" if found else "❌ لم يتم العثور على نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"
    message = f"🔔 قام المستخدم {username_text} بالبحث عن:\n`{query}`\nالحالة: {status_text}"
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to notify admin: {e}")

# -----------------------------
# عرض صفحة الكتب
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "بحث موسع" in search_stage or "الجذور" in search_stage:
        stage_note = "⚠️ نتائج بحث موسع (بحثنا بالجذور والمرادفات)"
    elif "تطابق جميع الكلمات" in search_stage:
        stage_note = "✅ نتائج دلالية (تطابق جميع كلماتك المفتاحية)"
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

    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الذكي PostgreSQL + FTS + pg_trgm
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query: return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    # تثبيت الامتداد pg_trgm تلقائيًا
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    except:
        pass

    normalized_query = normalize_text(remove_common_words(query))
    all_words_in_query = normalize_text(query).split()
    keywords = [w for w in all_words_in_query if w not in ARABIC_STOP_WORDS and len(w) >= 1]
    expanded_keywords = expand_keywords_with_synonyms(keywords)
    stemmed_keywords = [light_stem(k) for k in expanded_keywords]

    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords

    search_stage_text = "بحث دقيق FTS + Trigram"
    books = []

    try:
        # تحديث عمود tsv_content إذا لزم الأمر
        await conn.execute("""
            UPDATE books SET tsv_content = to_tsvector('simple', file_name)
            WHERE tsv_content IS NULL OR uploaded_at > (NOW() - INTERVAL '1 day')
        """)

        # البحث المدمج
        books = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at,
            (ts_rank(tsv_content, websearch_to_tsquery('simple', $1)) * 0.7
            + similarity(file_name, $1) * 0.3) AS final_score
            FROM books
            WHERE tsv_content @@ websearch_to_tsquery('simple', $1)
            OR similarity(file_name, $1) > 0.3
            ORDER BY final_score DESC, uploaded_at DESC
            LIMIT 100
        """, normalized_query)

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في البحث: {e}")
        return

    found_results = bool(books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    scored_books = []
    for book in books:
        score = calculate_score(book, all_words_in_query, normalized_query)
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = search_stage_text
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    keywords = context.user_data.get("last_keywords")
    last_query = context.user_data.get("last_query", "")

    if not keywords or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    try:
        expanded_keywords = expand_keywords_with_synonyms(keywords)
        stemmed_keywords = [light_stem(k) for k in expanded_keywords]
        search_terms = list(set(expanded_keywords + stemmed_keywords))

        books = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at,
            (ts_rank(tsv_content, websearch_to_tsquery('simple', $1)) * 0.7
            + similarity(file_name, $1) * 0.3) AS final_score
            FROM books
            WHERE tsv_content @@ websearch_to_tsquery('simple', $1)
            OR similarity(file_name, $1) > 0.3
            ORDER BY final_score DESC, uploaded_at DESC
            LIMIT 100
        """, last_query)

    except Exception as e:
        await update.callback_query.message.edit_text(f"❌ حدث خطأ أثناء البحث عن كتب مشابهة: {e}")
        return

    scored_books = []
    for book in books:
        all_words_in_query = normalize_text(last_query).split()
        score = calculate_score(book, all_words_in_query, last_query)
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    if not scored_books:
        await update.callback_query.message.edit_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (مشابه بالجذور والمرادفات)"
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار الكتب + الفهرس
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

    elif data == "home_index" or data == "show_index":
        from index_handler import show_index
        await show_index(update, context)
    elif data.startswith("index_page:"):
        from index_handler import navigate_index_pages
        await navigate_index_pages(update, context)
    elif data.startswith("index:"):
        from index_handler import search_by_index
        await search_by_index(update, context)
