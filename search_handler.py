import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List
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
    # إزالة الكلمات القصيرة جدًا (لتقليل النتائج غير الدقيقة)
    return [w for w in words if len(w) >= 3]

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

# -----------------------------
# توسيع الجذر (Root Expansion)
# -----------------------------
def expand_root(word: str) -> List[str]:
    variations = set()
    word = normalize_text(word)
    variations.add(word)
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين"]
    for suf in suffixes:
        if word.endswith(suf):
            variations.add(word[:-len(suf)])
    if word.startswith("ال"):
        variations.add(word[2:])
    # حذف بعض الحروف الأخيرة إذا كان الكلمة طويلة جدًا (للتقريب)
    if len(word) > 5:
        variations.add(word[:-1])
        variations.add(word[:-2])
    return list(variations)

# -----------------------------
# دالة التقييم الوزني (محسّنة)
# -----------------------------
def calculate_score(book_name: str, keywords: List[str]) -> int:
    score = 0
    name = normalize_text(book_name)
    words_in_name = name.split()

    for kw in keywords:
        roots = expand_root(kw)
        matched_root = False
        for root in roots:
            for w in words_in_name:
                if w == root:
                    score += 20  # تطابق كامل
                    matched_root = True
                elif w.startswith(root):
                    score += 12
                    matched_root = True
                elif root in w:
                    score += 8
                    matched_root = True
        # زيادة النقاط للكلمة الكاملة في الاسم
        if kw in name:
            score += 15
            matched_root = True
        # خصم النقاط للكلمات غير المطابقة
        if not matched_root:
            score -= 3
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
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1
    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
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
# البحث السريع والدقيق (محسّن)
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
        await update.message.reply_text("❌ لا يمكن البحث عن كلمات قصيرة جدًا.")
        return

    books = []
    try:
        # بحث دقيق أكثر: LIKE لكل كلمة مع ترتيب بحسب الأقرب للكلمة الأولى
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
        """)
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    # تقييم وزني صارم لزيادة الدقة
    scored_books = []
    for book in books:
        score = calculate_score(book['file_name'], keywords)
        if score > 0:  # تجاهل النتائج التي أقل من الصفر
            book_dict = dict(book)
            book_dict['score'] = score
            scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    found_results = bool(scored_books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not scored_books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث سريع ودقيق"
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
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
        """)
    except Exception as e:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    scored_books = []
    for book in books:
        score = calculate_score(book['file_name'], keywords)
        if score > 0:
            book_dict = dict(book)
            book_dict['score'] = score
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
