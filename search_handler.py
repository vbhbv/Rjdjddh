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
# إزالة كلمات مثل (كتاب / رواية)
# -----------------------------
def remove_common_words(text: str) -> str:
    for word in ["كتاب", "رواية"]:
        text = text.replace(word, "")
    return text.strip()

# -----------------------------
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]

        keyboard.append([
            InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # زر البحث عن مشابهات
    if not books and context.user_data.get("last_query"):
        keyboard.append([
            InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

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
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    normalized_query = normalize_text(remove_common_words(query))
    context.user_data["last_query"] = normalized_query

    try:
        books = await conn.fetch("""
        SELECT id, file_id, file_name
        FROM books
        WHERE LOWER(REPLACE(
            REPLACE(REPLACE(REPLACE(REPLACE(file_name,'أ','ا'),'إ','ا'),'آ','ا'),'ى','ي'),'_',' ')
        ) LIKE '%' || $1 || '%'
        ORDER BY uploaded_at DESC;
        """, normalized_query)

    except:
        await update.message.reply_text("❌ حدث خطأ أثناء البحث.")
        return

    if not books:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]
        ])
        await update.message.reply_text(
            f"❌ لا توجد نتائج للبحث: {query}",
            reply_markup=keyboard
        )
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

    if not conn or not last_query:
        await update.callback_query.message.reply_text("❌ لا يوجد ما أبحث عنه.")
        return

    words = last_query.split()

    try:
        books = await conn.fetch("""
        SELECT id, file_id, file_name
        FROM books
        WHERE """ + " OR ".join([f"file_name ILIKE '%{w}%'" for w in words]) + """
        ORDER BY uploaded_at DESC;
        """)
    except:
        await update.callback_query.message.reply_text("❌ خطأ أثناء البحث عن مشابهات.")
        return

    if not books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0

    await send_books_page(update, context)

# -----------------------------
# معالج الأزرار بالكامل
# -----------------------------
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # فتح ملف PDF
    if data.startswith("file:"):
        key = data.split("file:")[1]
        file_id = context.bot_data.get(f"file_{key}")

        await query.answer()
        await query.message.reply_document(file_id)
        return

    # التالي
    if data == "next_page":
        context.user_data["current_page"] += 1
        await query.answer()
        await send_books_page(update, context)
        return

    # السابق
    if data == "prev_page":
        context.user_data["current_page"] -= 1
        await query.answer()
        await send_books_page(update, context)
        return

    # بحث مشابهات
    if data == "search_similar":
        await query.answer()
        await search_similar_books(update, context)
        return

    await query.answer("❌ أمر غير معروف.")
