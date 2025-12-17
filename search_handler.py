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
ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))

# =========================
# محرك التطبيع والبحث الذكي
# =========================
def fast_normalize(text: str) -> str:
    """تطبيع النصوص للبحث السريع والدقيق"""
    if not text: return ""
    text = text.lower().strip()
    # توحيد الحروف العربية المتشابهة
    repls = str.maketrans("أإآةى", "اااوه")
    text = text.translate(repls)
    # إزالة الرموز والتشكيل
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())

async def hybrid_search_logic(conn, query: str, limit: int = 200):
    """استعلام هجين يجمع بين التشابه النصي والبحث الدلالي في خطوة واحدة"""
    norm_q = fast_normalize(query)
    # تجهيز كلمات البحث لـ Full Text Search
    words = [f"{w}:*" for w in norm_q.split() if len(w) > 1]
    fts_q = " & ".join(words) if words else norm_q

    sql = """
    SELECT id, file_id, file_name,
           similarity(file_name, $1) as sim_score,
           ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $2)) as fts_score
    FROM books
    WHERE 
        file_name % $1 
        OR to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $2)
        OR file_name ILIKE $3
    ORDER BY 
        (file_name ILIKE $3) DESC, 
        (sim_score * 0.7 + fts_score * 0.3) DESC
    LIMIT $4;
    """
    return await conn.fetch(sql, norm_q, fts_q, f"%{norm_q}%", limit)

# =========================
# إرسال صفحة الكتب (UI)
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = (f"📚 **نتائج البحث ({len(books)} كتاب)**\n"
            f"🔍 الدقة: بحث هجين متطور\n"
            f"📄 الصفحة {page + 1} من {total_pages}\n")

    keyboard = []
    for b in current_books:
        # إنشاء مفتاح فريد قصير للملف لتجنب تجاوز حجم CallbackData
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:12]
        context.bot_data[f"f_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📖 {b['file_name'][:60]}", callback_data=f"file:{key}")])

    # أزرار التنقل
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books): nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav: keyboard.append(nav)

    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# =========================
# الدالة الرئيسية للبحث
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query or len(query) < 2: return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    try:
        results = await hybrid_search_logic(conn, query)
        
        if not results:
            await send_search_suggestions(update, context)
            context.user_data["search_results"] = []
            return

        context.user_data["search_results"] = [dict(b) for b in results]
        context.user_data["current_page"] = 0
        
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search Error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ فني أثناء البحث.")

# =========================
# معالجة الأزرار (handle_callbacks)
# =========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    """هذه هي الدالة التي كانت مفقودة وتسببت في انهيار البوت"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"f_{key}")
        if file_id:
            await query.message.reply_document(
                document=file_id, 
                caption="📖 تم الاستخراج بواسطة محرك البحث الذكي",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("شارك البوت", switch_inline_query="")
                ]])
            )
        else:
            await query.message.reply_text("❌ انتهت صلاحية الجلسة، ابحث عن الكتاب مجدداً.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] = max(0, context.user_data.get("current_page", 0) - 1)
        await send_books_page(update, context)

    elif data in ("home_index", "show_index"):
        try:
            from index_handler import show_index
            await show_index(update, context)
        except ImportError:
            await query.message.reply_text("🏠 القائمة الرئيسية")
