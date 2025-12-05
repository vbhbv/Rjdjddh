import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os
import asyncio

# -----------------------------
# الإعدادات
# -----------------------------
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

# إعدادات المشرف
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
    return word

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
    "صوفية": ["تصوف", "طرق صوفية", "الأولياء", "روحانية"]
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
# عرض صفحة الكتب
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (context.user_data.get("total_books", 0) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "بحث موسع" in search_stage or "الجذور" in search_stage:
        stage_note = "⚠️ نتائج بحث موسع (الجذور والمرادفات)"
    else:
        stage_note = "✅ نتائج دقيقة"

    text = f"📚 النتائج ({context.user_data.get('total_books', 0)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        # إزالة الكتاب الأزرق واستبداله بعلامة 🔹
        keyboard.append([InlineKeyboardButton(f"🔹 {b['file_name']}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < context.user_data.get("total_books", 0):
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
# البحث الذكي مع Pagination
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

    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    except:
        pass

    normalized_query = normalize_text(remove_common_words(query))
    all_words_in_query = normalize_text(query).split()
    keywords = [w for w in all_words_in_query if w not in ARABIC_STOP_WORDS and len(w) >= 1]
    expanded_keywords = expand_keywords_with_synonyms(keywords)

    # بناء استعلام FTS مع المرادفات
    tsquery = ' & '.join([f"{k}:*" for k in expanded_keywords])
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords
    context.user_data["current_page"] = 0

    # جلب أول صفحة
    page = 0
    offset = page * BOOKS_PER_PAGE

    try:
        total_books = await conn.fetchval("""
            SELECT COUNT(*) FROM books
            WHERE tsv_content @@ to_tsquery('arabic', $1)
        """, tsquery)

        rows = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at,
            (ts_rank(tsv_content, to_tsquery('arabic', $1)) * 0.7
            + similarity(file_name, $2) * 0.3) AS final_score
            FROM books
            WHERE tsv_content @@ to_tsquery('arabic', $1)
            OR similarity(file_name, $2) > 0.3
            ORDER BY final_score DESC, uploaded_at DESC
            LIMIT $3 OFFSET $4
        """, tsquery, normalized_query, BOOKS_PER_PAGE, offset)

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في البحث: {e}")
        return

    found_results = bool(rows)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not rows:
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}")
        context.user_data["search_results"] = []
        context.user_data["total_books"] = 0
        return

    context.user_data["search_results"] = [dict(row) for row in rows]
    context.user_data["total_books"] = total_books
    context.user_data["search_stage"] = "بحث دقيق FTS + Trigram"
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
            share_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 شارك البوت مع أصدقائك", switch_inline_query="")]
            ])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=share_button)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await search_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await search_books_page(update, context)
    elif data == "home_index" or data == "show_index":
        from index_handler import show_index
        await show_index(update, context)

# -----------------------------
# جلب الصفحة التالية مباشرة من DB
# -----------------------------
async def search_books_page(update, context):
    query = context.user_data.get("last_query", "")
    if not query:
        return
    page = context.user_data.get("current_page", 0)
    offset = page * BOOKS_PER_PAGE
    conn = context.bot_data.get("db_conn")
    if not conn:
        return

    all_words_in_query = context.user_data.get("last_keywords", [])
    tsquery = ' & '.join([f"{k}:*" for k in all_words_in_query])

    rows = await conn.fetch("""
        SELECT id, file_id, file_name, uploaded_at,
        (ts_rank(tsv_content, to_tsquery('arabic', $1)) * 0.7
        + similarity(file_name, $2) * 0.3) AS final_score
        FROM books
        WHERE tsv_content @@ to_tsquery('arabic', $1)
        OR similarity(file_name, $2) > 0.3
        ORDER BY final_score DESC, uploaded_at DESC
        LIMIT $3 OFFSET $4
    """, tsquery, query, BOOKS_PER_PAGE, offset)

    context.user_data["search_results"] = [dict(row) for row in rows]
    await send_books_page(update, context)
