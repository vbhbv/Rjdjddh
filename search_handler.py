import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os

BOOKS_PER_PAGE = 10

# ==============================
# إعدادات المشرف
# ==============================
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# ==============================
# دوال التطبيع والتنظيف
# ==============================
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
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

def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين"]
    for suf in suffixes:
        if word.endswith(suf):
            word = word[:-len(suf)]
            break
    if word.startswith("ال"):
        word = word[2:]
    return word

# ==============================
# دالة البحث التحليلي الذكي
# ==============================
def calculate_advanced_score(book: Dict[str, Any], query: str, keywords: List[str]) -> int:
    book_title = normalize_text(book.get('file_name', ''))
    book_words = [light_stem(w) for w in book_title.split()]
    query_words = [light_stem(w) for w in keywords]

    score = 0

    # 1- تطابق كامل للجملة
    if normalize_text(book_title) == normalize_text(query):
        score += 50

    # 2- تطابق جميع الكلمات بأي ترتيب
    if all(q in book_words for q in query_words):
        score += 30

    # 3- التطابق الجزئي للكلمات والجذر
    for q in query_words:
        for i, bw in enumerate(book_words):
            if bw.startswith(q):
                score += 12
            elif q in bw:
                score += 10

    # 4- ترتيب الكلمات الجزئي
    for i in range(len(query_words)-1):
        if query_words[i] in book_words and query_words[i+1] in book_words:
            idx1 = book_words.index(query_words[i])
            idx2 = book_words.index(query_words[i+1])
            if idx2 - idx1 == 1:  # متجاورة
                score += 5

    return score

# ==============================
# إشعار المشرف
# ==============================
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

# ==============================
# إرسال صفحة الكتب
# ==============================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "تطابق جميع الكلمات" in search_stage:
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

# ==============================
# البحث الذكي
# ==============================
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

    books = []
    search_stage_text = "تطابق دقيق"

    try:
        # المرحلة 1: البحث عن تطابق الجملة أو الكلمات كلها
        and_conditions = " AND ".join([f"LOWER(file_name) LIKE '%{normalize_text(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
        SELECT id, file_id, file_name, uploaded_at
        FROM books
        WHERE {and_conditions}
        ORDER BY uploaded_at DESC;
        """)

        if books:
            search_stage_text = "تطابق جميع الكلمات"

    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    # إشعار المشرف
    found_results = bool(books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not books:
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}")
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    # التقييم باستخدام الخوارزمية المتقدمة
    scored_books = []
    for book in books:
        score = calculate_advanced_score(book, normalized_query, keywords)
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    # ترتيب النتائج حسب الدرجة
    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = search_stage_text
    await send_books_page(update, context)

# ==============================
# التعامل مع أزرار الكتب
# ==============================
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
