import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List
import os

# -----------------------------
# إعدادات وقائمة Stop Words
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
# دالة اقتراحات البحث
# -----------------------------
async def send_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE, query: str, conn):
    """
    تعرض اقتراحات البحث عند عدم وجود نتائج مطابقة
    """
    normalized_query = normalize_text(query)
    query_words = normalized_query.split()
    stemmed_query = [light_stem(w) for w in query_words if w not in ARABIC_STOP_WORDS]

    if not stemmed_query:
        await update.message.reply_text("❌ لا توجد اقتراحات للبحث.")
        return

    # إنشاء tsquery مشابه باستخدام OR للجذور
    ts_query = ' | '.join(stemmed_query)

    try:
        results = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            ORDER BY ts_rank(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) DESC
            LIMIT 10;
        """, ts_query)
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء اقتراح البحث: {e}")
        return

    if not results:
        await update.message.reply_text("❌ للأسف، لا توجد اقتراحات مطابقة.")
        return

    # بناء لوحة الأزرار للكتب المقترحة
    keyboard = []
    for b in results:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"{b['file_name']}", callback_data=f"file:{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🔍 لم نجد نتائج مطابقة تمامًا لبحثك '{query}' لكن إليك بعض الاقتراحات:",
        reply_markup=reply_markup
        )
