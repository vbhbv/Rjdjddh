import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List
import os

# -----------------------------
# الإعدادات
# -----------------------------
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = text.replace("ـ", "")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_common_words(text: str) -> str:
    if not text:
        return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء", "طبعة", "مجاني", "كبير", "صغير"]:
        text = text.replace(word, "")
    return text.strip()

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
# المرادفات
# -----------------------------
SYNONYMS = {
    "مهندس": ["هندسة", "مقاول", "معماري"],
    "الهندسة": ["مهندس", "معمار", "بناء"],
    "المهدي": ["المنقذ", "القائم"],
    "عدمية": ["نيتشه", "موت", "عبث"],
    "دين": ["إسلام", "مسيحية", "يهودية", "فقه"],
    "فلسفة": ["منطق", "مفهوم", "متافيزيقا"],
    "اكتئاب": ["حزن", "ضيق", "هم", "كآبة"]
}

def expand_keywords_with_synonyms(keywords: List[str]) -> List[str]:
    expanded = set(keywords)
    for k in keywords:
        if k in SYNONYMS:
            expanded.update(SYNONYMS[k])
    return list(expanded)

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
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    stage_note = "🔎 نتائج البحث الذكي"
    text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"{b['file_name']}", callback_data=f"file:{key}")])

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
# البحث الذكي داخلي مع ترتيب دلالي
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
    words_in_query = [w for w in normalize_text(query).split() if w not in ARABIC_STOP_WORDS and len(w) > 1]
    expanded_keywords = expand_keywords_with_synonyms(words_in_query)
    stemmed_keywords = [light_stem(k) for k in expanded_keywords]

    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = words_in_query

    try:
        books = await conn.fetch("SELECT id, file_id, file_name, uploaded_at FROM books")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في البحث: {e}")
        return

    results = []
    for b in books:
        title = normalize_text(b["file_name"])
        score = 0

        # تطابق الجملة بالكامل
        if normalized_query in title:
            score += 5

        # تطابق الكلمات الأساسية
        for k in stemmed_keywords:
            if k in title:
                score += 2

        # تطابق المرادفات
        for k in expanded_keywords:
            if k in title and k not in stemmed_keywords:
                score += 1

        # أجزاء متتابعة من الجملة
        query_parts = normalized_query.split()
        match_parts = sum(1 for part in query_parts if part in title)
        score += match_parts * 0.5

        if score > 0:
            results.append({**b, "score": score})

    # ترتيب النتائج حسب أقرب صلة
    results.sort(key=lambda x: x["score"], reverse=True)

    found_results = bool(results)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not results:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    context.user_data["search_results"] = results
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع داخلي دلالي"
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
            share_button = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")]])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=share_button)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif data in ("home_index", "show_index"):
        await query.message.reply_text("🏠 العودة للفهرس")

    elif data == "search_similar":
        await query.message.reply_text("🔎 ميزة البحث عن كتب مشابهة")
