import hashlib
import re
import logging
import os
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_suggestions import send_search_suggestions

# =========================
# Logging
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# إعدادات عامة
# =========================
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

# =========================
# دوال التطبيع والتنظيف
# =========================
def normalize_text(text: str) -> str:
    if not text: return ""
    text = str(text).lower().replace("_", " ")
    repls = str.maketrans("أإآةى", "اااوه")
    text = text.translate(repls)
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())

def remove_common_words(text: str) -> str:
    if not text: return ""
    bad_words = {"كتاب", "رواية", "نسخة", "مجموعة", "اريد", "جزء", "طبعة", "مجاني", "كبير", "صغير"}
    return ' '.join([w for w in text.split() if w not in bad_words])

def light_stem(word: str) -> str:
    if len(word) <= 3: return word
    suffixes = ("ية", "ون", "ات", "ان", "ين")
    for suf in suffixes:
        if word.endswith(suf): return word[:-len(suf)]
    if word.startswith("ال"): return word[2:]
    return word

# =========================
# إرسال صفحة الكتب
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "✅ نتائج مطابقة")
    
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1
    start, end = page * BOOKS_PER_PAGE, (page + 1) * BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\n{search_stage}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📖 {b['file_name'][:60]}", callback_data=f"file:{key}")])

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books): nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav: keyboard.append(nav)

    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup)

# =========================
# البحث الذكي المطور (السرعة + الذكاء)
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query: return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    norm_q = normalize_text(query)
    clean_q = remove_common_words(norm_q)
    keywords = [light_stem(w) for w in clean_q.split() if w not in ARABIC_STOP_WORDS and len(w) >= 2]
    ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else norm_q

    try:
        # 1. رفع مستوى الحساسية لمنع النتائج الغبية (0.4 هو توازن مثالي)
        await conn.execute("SET pg_trgm.similarity_threshold = 0.4;")

        # 2. استعلام ذكي يعتمد على الأوزان (Scoring System)
        sql = """
        SELECT id, file_id, file_name,
               (CASE 
                    WHEN file_name ILIKE $3 THEN 1.0  -- تطابق تام (قمة الذكاء)
                    WHEN file_name ILIKE $4 THEN 0.7  -- يبدأ بنفس الكلمة
                    ELSE 0 
                END) AS exact_score,
               ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS fts_rank,
               similarity(file_name, $2) AS sim_score
        FROM books
        WHERE 
            to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            OR file_name % $2
            OR file_name ILIKE $4
        ORDER BY 
            exact_score DESC, 
            fts_rank DESC, 
            sim_score DESC
        LIMIT 200;
        """
        # المعاملات: ts_query, normalized_query, exact_match, starts_with
        rows = await conn.fetch(sql, ts_query, norm_q, norm_q, f"{norm_q}%")
        
        if not rows:
            await send_search_suggestions(update, context)
            return

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "🎯 نتائج دقيقة (تم ترتيبها حسب الأهمية)"
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث.")

# ==========================
# التعامل مع أزرار الكتاب
# ==========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(
                document=file_id, 
                caption="تم تنزيل هذا الكتاب بواسطة @boooksfree1bot",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("شارك البوت", switch_inline_query="")]])
            )
        else:
            await query.message.reply_text("❌ الرابط قديم، ابحث مجدداً.")
    
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] = max(0, context.user_data.get("current_page", 0) - 1)
        await send_books_page(update, context)
    elif data in ("home_index", "show_index"):
        from index_handler import show_index
        await show_index(update, context)
