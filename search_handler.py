import hashlib
import re
import logging
import os
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# الإعدادات الأساسية
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOOKS_PER_PAGE = 10
ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))

class BookSearchEngine:
    """محرك بحث هجين يدمج بين التشابه اللفظي والبحث النصي الكامل"""
    
    @staticmethod
    def normalize_for_db(text: str) -> str:
        """تجهيز النص ليتوافق مع أسلوب تخزين البيانات"""
        if not text: return ""
        text = text.lower().strip()
        # توحيد الحروف العربية الصعبة
        replacements = str.maketrans("أإآةى", "اااوه")
        text = text.translate(replacements)
        # تنظيف الرموز
        text = re.sub(r'[^\w\s]', ' ', text)
        return ' '.join(text.split())

    @classmethod
    async def perform_search(cls, conn, query: str):
        normalized_q = cls.normalize_for_db(query)
        keywords = [f"{w}:*" for w in normalized_q.split() if len(w) > 1]
        fts_query = " & ".join(keywords) if keywords else normalized_q

        # استعلام SQL واحد يجمع كل المراحل ويرتبها حسب الأهمية (Weighting)
        # 1. المطابقة التامة تأخذ الوزن الأعلى
        # 2. التشابه (Trigram) يعالج الأخطاء الإملائية
        # 3. الترتيب النصي (Rank) يعالج دقة الكلمات
        sql = """
        SELECT id, file_id, file_name,
               (CASE WHEN file_name ILIKE $1 THEN 1.0 ELSE 0 END) as exact_score,
               similarity(file_name, $2) as sim_score,
               ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $3)) as fts_score
        FROM books
        WHERE 
            file_name % $2  -- استخدام index trgm
            OR to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $3)
            OR file_name ILIKE $4
        ORDER BY 
            exact_score DESC, 
            (sim_score * 0.6 + fts_score * 0.4) DESC
        LIMIT 150;
        """
        like_query = f"%{normalized_q}%"
        exact_query = f"{normalized_q}"
        
        return await conn.fetch(sql, exact_query, normalized_q, fts_query, like_query)

# ==========================
# معالجة واجهة التليجرام
# ==========================

async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    query = update.message.text.strip()
    conn = context.bot_data.get("db_conn")
    
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    # إظهار حالة "جاري البحث" لتحسين تجربة المستخدم
    status_msg = await update.message.reply_text("🔎 جاري البحث في المكتبة...")

    try:
        results = await BookSearchEngine.perform_search(conn, query)
        
        if not results:
            from search_suggestions import send_search_suggestions
            await status_msg.delete()
            await send_search_suggestions(update, context)
            return

        # تخزين النتائج
        context.user_data["search_results"] = [dict(b) for b in results]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "✅ نتائج ذكية متقدمة"

        await status_msg.delete()
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search Error: {e}")
        await status_msg.edit_text("⚠️ حدث خطأ أثناء معالجة طلبك.")

async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    # (نفس دالة send_books_page السابقة مع تحسين بسيط في عرض الأسماء)
    data = context.user_data
    books = data.get("search_results", [])
    page = data.get("current_page", 0)
    
    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_batch = books[start:end]
    total_pages = (len(books) + BOOKS_PER_PAGE - 1) // BOOKS_PER_PAGE

    text = f"📚 النتائج ({len(books)} كتاب)\n{data.get('search_stage')}\nالصفحة {page + 1} من {total_pages}"
    
    keyboard = []
    for b in current_batch:
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:12]
        context.bot_data[f"f_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📖 {b['file_name'][:60]}", callback_data=f"file:{key}")])

    # أزرار التنقل
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books): nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav: keyboard.append(nav)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
