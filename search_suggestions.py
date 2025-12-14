# search_suggestions.py
import difflib
import re
import hashlib
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# -----------------------------
# إعدادات Stop Words
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
    text = text.lower()
    text = text.replace("_", " ").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ـ", "")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def remove_stopwords(words: List[str]) -> List[str]:
    return [w for w in words if w not in ARABIC_STOP_WORDS and len(w) > 1]

# -----------------------------
# اقتراح الكلمات القريبة
# -----------------------------
def suggest_similar_words(word: str, all_titles: List[str], n: int = 3) -> List[str]:
    normalized_titles = [normalize_text(title) for title in all_titles]
    suggestions = difflib.get_close_matches(word, normalized_titles, n=n, cutoff=0.6)
    return suggestions

# -----------------------------
# إرسال اقتراحات عند عدم وجود نتائج
# -----------------------------
async def send_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE):
    last_query = context.user_data.get("last_query", "")
    if not last_query:
        await update.message.reply_text("❌ لم يتم العثور على بحث سابق.")
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    try:
        rows = await conn.fetch("SELECT id, file_id, file_name FROM books;")
        all_books = [dict(r) for r in rows]
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء اقتراح الكتب: {e}")
        return

    query_words = remove_stopwords(normalize_text(last_query).split())
    suggestions_set = set()
    suggested_books = []

    for w in query_words:
        matches = suggest_similar_words(w, [b["file_name"] for b in all_books], n=3)
        for match in matches:
            for b in all_books:
                if normalize_text(b["file_name"]) == match and b not in suggested_books:
                    suggested_books.append(b)
                    break

    if not suggested_books:
        await update.message.reply_text(f"❌ لم نجد أي كتب مشابهة لبحثك: {last_query}")
        return

    context.user_data["suggested_books"] = suggested_books  # حفظ للاستخدام في callbacks
    keyboard = []

    for b in suggested_books[:10]:  # الحد الأعلى للاقتراحات
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(
            f"⚠️ لم يتم العثور على كتب مطابقة. إليك بعض الاقتراحات بناءً على بحثك: '{last_query}'",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.message.edit_text(
            f"⚠️ لم يتم العثور على كتب مطابقة. إليك بعض الاقتراحات بناءً على بحثك: '{last_query}'",
            reply_markup=reply_markup
        )

# -----------------------------
# التعامل مع أزرار الاقتراحات
# -----------------------------
async def handle_suggestion_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("suggest:") or data.startswith("file:"):
        key = data.split(":", 1)[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            share_button = InlineKeyboardMarkup([[InlineKeyboardButton("شارك البوت مع أصدقائك", switch_inline_query="")]])
            await query.message.reply_document(document=file_id, caption=caption, reply_markup=share_button)
        else:
            await query.message.reply_text("❌ الملف غير متوفر حالياً.")
