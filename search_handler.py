import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
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
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    if not text: return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    if not text: return []
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين"]
    for suf in suffixes:
        if word.endswith(suf):
            word = word[:-len(suf)]
            break
    if word.startswith("ال"): word = word[2:]
    return word

def calculate_score(book: Dict[str, Any], keywords: List[str], normalized_query: str) -> int:
    score = 0
    book_name = normalize_text(book.get('file_name', ''))
    if normalized_query == book_name:
        score += 50
    elif normalized_query in book_name:
        score += 20
    title_words = book_name.split()
    for k in keywords:
        k_stem = light_stem(k)
        for t_word in title_words:
            t_stem = light_stem(t_word)
            if t_stem.startswith(k_stem):
                score += 10
            elif k_stem in t_stem:
                score += 8
    return score

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
# إرسال صفحة الكتب (موحدة للفهرس والبحث)
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    show_index_button = context.user_data.get("show_index_button", False)  # زر العودة للفهرس
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    stage_note = {
        "بحث موسع": "⚠️ نتائج بحث موسع (بحثنا بالكلمات المفتاحية)",
        "تطابق جميع الكلمات": "✅ نتائج دلالية (تطابق جميع كلماتك)"
    }.get(search_stage, "✅ نتائج مطابقة (تطابق العبارة كاملة)")

    text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"): continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if show_index_button:  # إضافة زر العودة للفهرس فقط للكتب الناتجة من الفهرس
        nav_buttons.append(InlineKeyboardButton("🏠 العودة للفهرس", callback_data="show_index"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الذكي
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query: return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    normalized_query = normalize_text(remove_common_words(query))
    keywords = extract_keywords(normalized_query)
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords
    context.user_data["show_index_button"] = False  # البحث الحر لا يظهر زر العودة للفهرس

    books, search_stage_text = [], "تطابق دقيق"

    try:
        books = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE LOWER(file_name) LIKE '%' || $1 || '%'
            ORDER BY uploaded_at DESC;
        """, normalized_query)

        if not books and keywords:
            search_stage_text = "تطابق جميع الكلمات"
            and_conditions = " AND ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
            books = await conn.fetch(f"""
                SELECT id, file_id, file_name, uploaded_at
                FROM books
                WHERE {and_conditions}
                ORDER BY uploaded_at DESC;
            """)
        if not books and keywords:
            search_stage_text = "بحث موسع"
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

    found_results = bool(books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data.update({"search_results": [], "current_page": 0})
        return

    scored_books = []
    for book in books:
        score = calculate_score(book, keywords, normalized_query)
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    context.user_data.update({"search_results": scored_books, "current_page": 0, "search_stage": search_stage_text})
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
        score = calculate_score(book, keywords, context.user_data.get("last_query", ""))
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)

    if not scored_books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data.update({
        "search_results": scored_books,
        "current_page": 0,
        "search_stage": "بحث موسع (مشابه)",
        "show_index_button": False
    })
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار الكتب
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
