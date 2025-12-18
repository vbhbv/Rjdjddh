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

BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي"
}

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

def clean_query_smart(text: str) -> List[str]:
    bad_words = {"رواية", "نسخة", "مجموعة", "اريد", "جزء", "طبعة", "مجاني", "كبير", "صغير", "تحميل", "تنزيل"}
    words = text.split()
    return [w for w in words if w not in bad_words and w not in ARABIC_STOP_WORDS]

# =========================
# إرسال صفحة الكتب (UI)
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "✅ نتائج مطابقة")
    
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1
    start, end = page * BOOKS_PER_PAGE, (page + 1) * BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 **{search_stage}**\n"
    text += f"📄 الصفحة {page + 1} من {total_pages}\n\n"
    
    keyboard = []
    for b in current_books:
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        display_name = (b['file_name'][:57] + '..') if len(b['file_name']) > 60 else b['file_name']
        keyboard.append([InlineKeyboardButton(f"📖 {display_name}", callback_data=f"file:{key}")])

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books): nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav: keyboard.append(nav)

    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

# =========================
# محرك البحث الذكي + نظام الاقتراح التلقائي
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query or len(query) < 2: return

    conn = context.bot_data.get("db_conn")
    if not conn: return

    norm_q = normalize_text(query)
    keywords = clean_query_smart(norm_q)
    
    # تحويل الكلمات للبحث النصي الكامل
    ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else norm_q

    try:
        # المرحلة 1: البحث عن العنوان المطلوب حرفياً أو دلالياً
        sql = """
        SELECT id, file_id, file_name,
               ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
               similarity(file_name, $2) AS sim
        FROM books
        WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
           OR file_name ILIKE $3
           OR file_name % $2
        ORDER BY (file_name ILIKE $3) DESC, rank DESC, sim DESC
        LIMIT 150;
        """
        partial_pattern = f"%{keywords[-1]}%" if keywords else f"%{norm_q}%"
        rows = await conn.fetch(sql, ts_query, norm_q, partial_pattern)
        
        # المرحلة 2: إذا لم توجد نتائج، نبحث عن "كتب في نفس المجال" (نظام الاقتراحات الذكي)
        if not rows and keywords:
            search_stage = "💡 لم نجد العنوان بالضبط، لكن إليك كتب في نفس المجال:"
            # نأخذ الكلمات المفتاحية ونبحث عن أي كتاب يحتوي على "أي" منها بدلاً من "كلها"
            or_ts_query = ' | '.join([f"{w}:*" for w in keywords])
            
            sql_recommend = """
            SELECT id, file_id, file_name,
                   ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank
            FROM books
            WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            ORDER BY rank DESC
            LIMIT 50;
            """
            rows = await conn.fetch(sql_recommend, or_ts_query)
        else:
            search_stage = f"🔍 تم العثور على {len(rows)} نتيجة لـ '{query}':"

        # إرسال النتائج النهائية (سواء كانت بحثاً مباشراً أو اقتراحات)
        if rows:
            context.user_data["search_results"] = [dict(r) for r in rows]
            context.user_data["current_page"] = 0
            context.user_data["search_stage"] = search_stage
            await send_books_page(update, context)
        else:
            # إذا فشل حتى الاقتراح، نرسل اقتراحات عشوائية من ملف search_suggestions
            await send_search_suggestions(update, context)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة طلبك.")

# ==========================
# التعامل مع أزرار التنقل والتحميل
# ==========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            try:
                await query.message.reply_document(
                    document=file_id, 
                    caption="📖 تم استخراج الكتاب بنجاح من المكتبة",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 شارك البوت", switch_inline_query="")]])
                )
            except:
                await query.message.reply_text("❌ حدث خطأ أثناء إرسال الملف.")
        else:
            await query.message.reply_text("❌ عذراً، انتهت جلسة البحث. يرجى إعادة البحث.")
    
    elif data == "next_page":
        context.user_data["current_page"] = context.user_data.get("current_page", 0) + 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] = max(0, context.user_data.get("current_page", 0) - 1)
        await send_books_page(update, context)
    elif data in ("home_index", "show_index"):
        from index_handler import show_index
        await show_index(update, context)
