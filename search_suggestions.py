# search_suggestions.py
import hashlib
import re
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# -----------------------------
# قائمة Stop Words
# -----------------------------
ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

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
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "جزء", "طبعة", "مجاني", "كبير", "صغير"]:
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
# إرسال صفحة الاقتراحات
# -----------------------------
async def show_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE, suggestions: List[dict]):
    if not suggestions:
        await update.message.reply_text("❌ لم يتم العثور على أي اقتراحات.")
        return

    keyboard = []
    for b in suggestions[:10]:  # عرض أول 10 اقتراحات فقط لتقليل استهلاك الموارد
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"{b['file_name']}", callback_data=f"file:{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ لم نجد نتائج دقيقة. إليك بعض الاقتراحات الأقرب لما كتبته:",
        reply_markup=reply_markup
    )

# -----------------------------
# البحث مع اقتراحات ذكية
# -----------------------------
async def search_books_with_suggestions(update, context: ContextTypes.DEFAULT_TYPE):
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
    all_words_in_query = normalize_text(query).split()
    keywords = [w for w in all_words_in_query if w not in ARABIC_STOP_WORDS and len(w) >= 1]

    # تجميع الكلمة للبحث في DB
    ts_query = ' & '.join([light_stem(k) for k in keywords])

    # البحث الأساسي
    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            ORDER BY ts_rank(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) DESC
            LIMIT 200;
        """, ts_query)
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في البحث: {e}")
        return

    if books:
        # حفظ النتائج للمستخدم وعرضها
        context.user_data["search_results"] = [dict(b) for b in books]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "بحث متقدم (FTS + Trigram + مرادفات)"
        from search_handler import send_books_page
        await send_books_page(update, context)
        return

    # -----------------------------
    # إذا لم توجد نتائج -> اقتراحات ذكية
    # -----------------------------
    try:
        # استخدام pg_trgm للبحث عن كلمات مشابهة هجائياً
        suggestions = await conn.fetch(f"""
            SELECT id, file_id, file_name
            FROM books
            WHERE file_name % $1
            ORDER BY similarity(file_name, $1) DESC
            LIMIT 20;
        """, query)
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في اقتراحات البحث: {e}")
        return

    # عرض الاقتراحات
    await show_search_suggestions(update, context, [dict(b) for b in suggestions])
