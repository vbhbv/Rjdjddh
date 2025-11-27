import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncpg

BOOKS_PER_PAGE = 10
BOT_USERNAME = "@boooksfree1bot"

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
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
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

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الرئيسي
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn: asyncpg.Connection = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
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
    except Exception:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    if not books:
        # البحث السياقي الذكي: اقتراح كتب مشابهة حسب كلمات الاستعلام
        await search_similar_books(update, context)
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# البحث السياقي الذكي
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    conn: asyncpg.Connection = context.bot_data.get("db_conn")
    last_query = context.user_data.get("last_query")
    if not last_query or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    words = last_query.split()

    # البحث عن أي كلمة موجودة في اسم الكتاب
    where_clause = " OR ".join([f"file_name ILIKE '%' || '{w}' || '%'" for w in words])

    try:
        books = await conn.fetch(f"""
        SELECT id, file_id, file_name
        FROM books
        WHERE {where_clause}
        ORDER BY uploaded_at DESC;
        """)
    except Exception:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    if not books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# معالجة أزرار الكتب
# -----------------------------
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = f"تم التنزيل بواسطة {BOT_USERNAME}"
            # زر مشاركة
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 شارك هذا الكتاب", switch_inline_query=f"{file_id}")
            ]])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=keyboard)
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
