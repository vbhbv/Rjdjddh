from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_handler import send_books_page
from search_handler import normalize_text, remove_common_words
import re

INDEXES = [
    ("قواعد اللغة العربية", "arabic_grammar", ["قواعد", "نحو", "صرف", "إملاء", "لغوي"]),
    ("كتب إنكليزية", "english_books", ["english", "grammar", "literature", "novel"]),
    ("البرمجة", "programming", ["برمجة", "كود", "python", "java", "algorithm"]),
    # أضف باقي الفهارس هنا...
]

def normalize_keywords(keywords):
    return [normalize_text(remove_common_words(k)) for k in keywords]

async def show_index(update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(name, callback_data=f"index:{key}")] for name, key, _ in INDEXES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📚 اختر الفهرس الذي تريد استعراضه:", reply_markup=reply_markup)

async def search_by_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    index_key = query.data.replace("index:", "")

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    keywords = []
    for name, key, kws in INDEXES:
        if key == index_key:
            keywords = kws
            break
    if not keywords:
        await query.message.reply_text("❌ لا توجد كلمات مفتاحية لهذا الفهرس.")
        return

    keywords = normalize_keywords(keywords)
    or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{k}%'" for k in keywords])
    try:
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
        """)
    except:
        await query.message.reply_text("❌ حدث خطأ أثناء البحث عن الكتب.")
        return

    if not books:
        await query.message.reply_text("❌ لم يتم العثور على أي كتب ضمن هذا الفهرس.")
        return

    context.user_data["search_results"] = [dict(b) for b in books]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"فهرس: {index_key}"

    await send_books_page(update, context)
