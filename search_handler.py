import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, Update

BOOKS_PER_PAGE = 10

# -----------------------------
# تطبيع النص العربي
# -----------------------------
def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

# -----------------------------
# إزالة كلمات عامة مثل كتاب/رواية
# -----------------------------
def remove_common_words(text: str) -> str:
    for word in ["كتاب", "رواية"]:
        text = text.replace(word, "")
    return text.strip()

# -----------------------------
# حساب درجة التشابه بين كلمتين/عبارتين
# -----------------------------
def similarity_score(query_words, book_name_words):
    matches = sum(1 for w in query_words if w in book_name_words)
    return matches / len(query_words) if query_words else 0

# -----------------------------
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
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
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الرئيسي
# -----------------------------
async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    # تطبيع وإزالة الكلمات العامة
    normalized_query = normalize_text(remove_common_words(query))
    context.user_data["last_query"] = normalized_query

    # تجاهل الكلمات القصيرة جدًا
    query_words = [w for w in normalized_query.split() if len(w) > 2]

    try:
        # جلب كل الكتب أولاً
        books_raw = await conn.fetch("SELECT id, file_id, file_name FROM books ORDER BY uploaded_at DESC;")
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    # -----------------------------
    # فلترة وترتيب النتائج حسب درجة التشابه
    # -----------------------------
    filtered_books = []
    for b in books_raw:
        book_name_norm = normalize_text(b["file_name"])
        book_words = [w for w in book_name_norm.split() if len(w) > 2]
        score = similarity_score(query_words, book_words)
        if score > 0:
            filtered_books.append((score, b))

    # ترتيب النتائج من الأكثر تشابهًا إلى الأقل
    filtered_books.sort(key=lambda x: x[0], reverse=True)
    books = [b for _, b in filtered_books]

    if not books:
        # إذا لم توجد نتائج، إرسال رسالة مع زر البحث عن كتب مشابهة
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب تطابق: {query}\nيمكنك البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة
# -----------------------------
async def search_similar_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    last_query = context.user_data.get("last_query")
    if not last_query or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    words = [w for w in last_query.split() if len(w) > 2]
    if not words:
        await update.callback_query.message.reply_text("❌ لا توجد كلمات كافية للبحث.")
        return

    try:
        books_raw = await conn.fetch("SELECT id, file_id, file_name FROM books ORDER BY uploaded_at DESC;")
    except Exception as e:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    filtered_books = []
    for b in books_raw:
        book_name_norm = normalize_text(b["file_name"])
        book_words = [w for w in book_name_norm.split() if len(w) > 2]
        score = similarity_score(words, book_words)
        if score > 0:
            filtered_books.append((score, b))

    filtered_books.sort(key=lambda x: x[0], reverse=True)
    books = [b for _, b in filtered_books]

    if not books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# معالجة أزرار الملفات والاقتراحات
# -----------------------------
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            share_button = InlineKeyboardMarkup([[InlineKeyboardButton("📤 شارك هذا الملف", switch_inline_query=file_id)]])
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
