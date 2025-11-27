import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackContext
import re

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
# إزالة كلمات عامة
# -----------------------------
def remove_common_words(text: str) -> str:
    for word in ["كتاب", "رواية"]:
        text = text.replace(word, "")
    return text.strip()

# -----------------------------
# استخراج الكلمات المفتاحية
# -----------------------------
def extract_keywords(text: str):
    text = normalize_text(remove_common_words(text))
    words = re.findall(r'\b\w{3,}\b', text)  # كلمات >= 3 أحرف
    return list(set(words))  # إزالة التكرار

# -----------------------------
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update, context: CallbackContext):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if not current_books:
        await update.callback_query.message.reply_text("❌ لا توجد كتب للعرض.")
        return

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
# البحث الذكي عن الكتب
# -----------------------------
async def search_books(update, context: CallbackContext):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if not query:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    keywords = extract_keywords(query)
    context.user_data["last_keywords"] = keywords

    if not keywords:
        await update.message.reply_text("❌ لا يوجد كلمات مفتاحية صالحة للبحث.")
        return

    # البحث باستخدام كلمات مفتاحية مع حساب درجة التطابق
    try:
        conditions = " OR ".join([f"LOWER(file_name) LIKE '%' || $1 || '%'" for _ in keywords])
        # سيستخدم أول كلمة كمثال، سنعالج التطابق في البايثون بعد الاستعلام
        books_raw = await conn.fetch("""
            SELECT id, file_id, file_name
            FROM books
        """)
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    # تقييم الكتب بناءً على عدد الكلمات المفتاحية الموجودة
    results = []
    for book in books_raw:
        score = 0
        name_norm = normalize_text(book["file_name"])
        for kw in keywords:
            if kw in name_norm:
                score += 1
        if score > 0:
            results.append({"book": book, "score": score})

    # ترتيب النتائج حسب أعلى درجة
    results.sort(key=lambda x: x["score"], reverse=True)
    books = [r["book"] for r in results]

    if not books:
        # اقتراح كتب مشابهة حسب أي كلمة موجودة
        await update.message.reply_text("❌ لم أجد كتب مطابقة بالضبط، اضغط زر البحث عن كتب مشابهة.")
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

# -----------------------------
# معالجة أزرار الكتب والصفحات
# -----------------------------
async def handle_callbacks(update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            # زر المشاركة
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 شارك هذا الكتاب", switch_inline_query=file_id)]])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=keyboard)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
