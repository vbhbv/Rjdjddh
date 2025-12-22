# search_suggestions.py
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
# اقتراح الكتب بسرعة (بحث بالكلمات المفتاحية)
# -----------------------------
async def send_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE):
    last_query = context.user_data.get("last_query", "")
    if not last_query:
        await update.message.reply_text(
            "ℹ️ لا يوجد بحث سابق.\n\n"
            "📌 طريقة الاستخدام الصحيحة:\n"
            "- اكتب اسم الكتاب مباشرة.\n"
            "- أو اكتب كلمتين أساسيتين من العنوان.\n"
            "- تجنب كلمات مثل: كتاب، رواية، تحميل، أريد."
        )
        return

    # جلب قائمة الكتب من الذاكرة لتسريع البحث
    if "all_books" not in context.bot_data:
        conn = context.bot_data.get("db_conn")
        if not conn:
            await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
            return
        try:
            rows = await conn.fetch("SELECT file_id, file_name FROM books;")
            context.bot_data["all_books"] = [
                {"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows
            ]
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ أثناء جلب الكتب: {e}")
            return

    all_books = context.bot_data["all_books"]

    # اقتراحات بناءً على كلمات البحث
    query_words = remove_stopwords(normalize_text(last_query).split())
    suggested_books_set = set()

    for book in all_books:
        book_name_norm = normalize_text(book["file_name"])
        if any(w in book_name_norm for w in query_words):
            suggested_books_set.add((book["file_id"], book["file_name"]))

    suggested_books = list(suggested_books_set)[:10]

    # -------- النص الجديد عند الفشل --------
    if not suggested_books:
        help_text = (
            "📚 لم يتم العثور على كتاب مطابق لبحثك.\n\n"
            "✅ للحصول على نتائج دقيقة:\n"
            "1️⃣ اكتب اسم الكتاب مباشرة دون إضافات.\n"
            "2️⃣ استخدم كلمتين أو ثلاث من العنوان فقط.\n"
            "3️⃣ تجنب الكلمات الجانبية مثل:\n"
            "   (كتاب، رواية، تحميل، أريد، نسخة، مجاني).\n\n"
            "✍️ مثال صحيح:\n"
            "فن اللامبالاة\n"
            "جريمة الولادة\n"
            "مدخل إلى الفلسفة"
        )
        if update.message:
            await update.message.reply_text(help_text)
        elif update.callback_query:
            await update.callback_query.message.edit_text(help_text)
        return

    # إنشاء أزرار لإرسال الكتب مباشرة عند الضغط
    keyboard = []
    for file_id, file_name in suggested_books:
        key = hashlib.md5(file_id.encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = file_id
        keyboard.append([InlineKeyboardButton(file_name, callback_data=f"file:{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    suggestion_text = (
        "ℹ️ لم نجد تطابقًا مباشرًا، لكن يمكنك تجربة أحد العناوين التالية:"
    )

    if update.message:
        await update.message.reply_text(suggestion_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(suggestion_text, reply_markup=reply_markup)

# -----------------------------
# التعامل مع أزرار الاقتراحات
# -----------------------------
async def handle_suggestion_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("suggest:"):
        suggested_title = data.split(":", 1)[1]
        update.message = update.callback_query.message
        update.message.text = suggested_title
        from search_handler import search_books
        await search_books(update, context)
