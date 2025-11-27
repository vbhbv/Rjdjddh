import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

BOOKS_PER_PAGE = 10

# ==============================
# تطبيع النص العربي
# ==============================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")  # تطبيع الهاء والتاء المربوطة
    # إزالة كلمات عامة لا تؤثر في البحث
    for word in ["كتاب", "رواية"]:
        text = text.replace(word, "")
    return text.strip()

# ==============================
# إرسال صفحة الكتب
# ==============================
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

# ==============================
# البحث الرئيسي
# ==============================
async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    normalized_query = normalize_text(query)

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
        # لا يوجد كتاب مطابق
        keyboard = [[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data=f"similar:{normalized_query}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"❌ لم أجد أي كتب تطابق: {query}\nيمكنك البحث عن كتب مشابهة بالضغط على الزر أدناه.",
            reply_markup=reply_markup
        )
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# ==============================
# البحث عن الكتب المشابهة
# ==============================
async def search_similar_books(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str):
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
ORDER BY uploaded_at DESC
LIMIT 50;
""", keyword)
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    if not books:
        await update.message.reply_text("❌ للأسف لم أجد أي كتب مشابهة.")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# ==============================
# التعامل مع أزرار البحث والتنقل
# ==============================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    elif data.startswith("similar:"):
        keyword = data.split("similar:")[1]
        await search_similar_books(update, context, keyword)
