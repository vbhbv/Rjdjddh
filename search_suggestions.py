# search_suggestions.py
import difflib
import re
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
    """
    إرجاع قائمة بأقرب الكلمات للعنوان المدخل
    باستخدام خوارزمية difflib للحصول على أعلى تطابق
    """
    normalized_titles = [normalize_text(title) for title in all_titles]
    suggestions = difflib.get_close_matches(word, normalized_titles, n=n, cutoff=0.6)
    return suggestions

# -----------------------------
# إرسال اقتراحات عند عدم وجود نتائج
# -----------------------------
async def send_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE):
    last_query = context.user_data.get("last_query", "")
    if not last_query:
        return
    
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return
    
    # جلب كل عناوين الكتب لتوليد الاقتراحات
    try:
        rows = await conn.fetch("SELECT file_name FROM books;")
        all_titles = [r["file_name"] for r in rows]
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء اقتراح الكتب: {e}")
        return
    
    # اقتراحات بناءً على آخر كلمة في البحث
    query_words = remove_stopwords(normalize_text(last_query).split())
    suggestions_set = set()
    for w in query_words:
        matches = suggest_similar_words(w, all_titles, n=3)
        suggestions_set.update(matches)
    
    if not suggestions_set:
        await update.message.reply_text(f"❌ لم نجد أي كتب مشابهة لبحثك: {last_query}")
        return
    
    keyboard = []
    for title in list(suggestions_set)[:10]:  # الحد الأعلى للاقتراحات
        keyboard.append([InlineKeyboardButton(title, callback_data=f"suggest:{title}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"⚠️ لم يتم العثور على كتب مطابقة. إليك بعض الاقتراحات الممكنة بناءً على بحثك: '{last_query}'",
        reply_markup=reply_markup
    )

# -----------------------------
# التعامل مع أزرار الاقتراحات
# -----------------------------
async def handle_suggestion_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("suggest:"):
        suggested_title = data.split(":", 1)[1]
        # تحويل اقتراح إلى رسالة بحث جديدة
        update.message = update.callback_query.message
        update.message.text = suggested_title
        
        # استدعاء البحث الرئيسي (search_books) في الملف الرئيسي
        from search_handler import search_books
        await search_books(update, context)
