import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

BOOKS_PER_PAGE = 10

# ===============================
# التطبيع العربي
# ===============================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

# ===============================
# البحث عن الكتب
# ===============================
async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    # إزالة كلمات شائعة مثل "كتاب" أو "رواية" من بداية البحث
    for word in ["كتاب", "رواية"]:
        if query.startswith(word):
            query = query[len(word):].strip()

    normalized_query = normalize_text(query)

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    try:
        books = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE LOWER(REPLACE(
        REPLACE(REPLACE(REPLACE(REPLACE(file_name,'أ','ا'),'إ','ا'),'آ','ا'),'ى','ي'),'_',' ')
    ) LIKE '%' || $1 || '%'
ORDER BY uploaded_at DESC;
""", normalized_query)
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    if not books:
        # لا توجد نتائج، عرض زر البحث عن كتب مشابهة
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 البحث عن كتب مشابهة", callback_data=f"suggest:{normalized_query}")]
        ])
        await update.message.reply_text(
            f"❌ لم أجد أي كتب تطابق: {query}\nيمكنك البحث عن كتب مشابهة:",
            reply_markup=keyboard
        )
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# ===============================
# عرض صفحة الكتب
# ===============================
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

# ===============================
# ميزة البحث عن كتب مشابهة
# ===============================
async def suggest_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_data = update.callback_query.data
    await update.callback_query.answer()
    if not query_data.startswith("suggest:"):
        return

    original_query = query_data.split(":", 1)[1]

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.callback_query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    try:
        # البحث عن كتب تحتوي على أي كلمة من النص الأصلي
        words = original_query.split()
        like_clauses = " OR ".join([f"LOWER(file_name) LIKE '%{w}%'" for w in words])
        query_str = f"SELECT id, file_id, file_name FROM books WHERE {like_clauses} ORDER BY uploaded_at DESC;"
        books = await conn.fetch(query_str)
    except Exception:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    if not books:
        await update.callback_query.message.reply_text("❌ لم أجد أي كتب مشابهة.")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# ===============================
# التعامل مع أزرار التحميل والتنقل
# ===============================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @Boooksfree1bot"
            await query.message.reply_document(document=file_id, caption=caption)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
    elif data.startswith("suggest:"):
        await suggest_books(update, context)
