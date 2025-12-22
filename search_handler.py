import hashlib
import re
import logging
import os
import asyncpg
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
    bad_words = {"رواية", "نسخة", "مجموعة", "اريد", "جزء", "طبعة", "مجاني", "كبير", "صغير"}
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

    text = f"📚 **النتائج ({len(books)} كتاب)**\n{search_stage}\nالصفحة {page + 1} من {total_pages}\n\n"
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
# محرك البحث الذكي
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": 
        return

    # 🔒 تحقق الاشتراك (المكان الوحيد المضاف)
    from admin_panel import check_subscription
    if not await check_subscription(update, context):
        return
    # 🔒 نهاية التحقق

    query = update.message.text.strip()
    if not query or len(query) < 2: 
        return

    conn = context.bot_data.get("db_conn")
    
    # --- إصلاح انقطاع الاتصال ---
    if not conn or conn.is_closed():
        logger.info("🔄 الاتصال مقطوع، محاولة إعادة الاتصال بقاعدة البيانات...")
        try:
            db_url = os.getenv("DATABASE_URL")
            context.bot_data["db_conn"] = await asyncpg.connect(db_url)
            conn = context.bot_data["db_conn"]
        except Exception as e:
            logger.error(f"❌ فشل إعادة الاتصال: {e}")
            await update.message.reply_text("⚠️ حدث خطأ في الاتصال بقاعدة البيانات، يرجى المحاولة لاحقاً.")
            return
    # --------------------------

    norm_q = normalize_text(query)
    keywords = clean_query_smart(norm_q)
    ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else norm_q

    try:
        await conn.execute("SET pg_trgm.similarity_threshold = 0.3;")

        sql = """
        SELECT id, file_id, file_name,
               ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
               similarity(file_name, $2) AS sim
        FROM books
        WHERE 
            to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
            OR file_name ILIKE $3
            OR file_name % $2
        ORDER BY 
            (file_name ILIKE $3) DESC,
            rank DESC, 
            sim DESC
        LIMIT 200;
        """
        
        partial_pattern = f"%{keywords[-1]}%" if keywords else f"%{norm_q}%"
        rows = await conn.fetch(sql, ts_query, norm_q, partial_pattern)
        
        if not rows:
            await send_search_suggestions(update, context)
            return

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "⚡ نتائج بحث ذكي فائقة السرعة"
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search error: {e}")
        try:
            simple_rows = await conn.fetch(
                "SELECT * FROM books WHERE file_name ILIKE $1 LIMIT 50", 
                f"%{norm_q}%"
            )
            if simple_rows:
                context.user_data["search_results"] = [dict(r) for r in simple_rows]
                await send_books_page(update, context)
            else:
                await update.message.reply_text("⚠️ لم يتم العثور على نتائج، جرب كلمات أخرى.")
        except:
            await update.message.reply_text("⚠️ حدث خطأ فني، يرجى المحاولة لاحقاً.")

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
                    caption="تم تنزيل الكتاب بواسطة @boooksfree1bot",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                    ])
                )
            except Exception as e:
                logger.error(f"Download error: {e}")
                await query.message.reply_text("❌ عذراً، فشل تحميل الملف.")
        else:
            await query.message.reply_text("❌ انتهت الجلسة، يرجى إعادة البحث.")
    
    elif data == "next_page":
        context.user_data["current_page"] = context.user_data.get("current_page", 0) + 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] = max(0, context.user_data.get("current_page", 0) - 1)
        await send_books_page(update, context)
    elif data in ("home_index", "show_index"):
        try:
            from index_handler import show_index
            await show_index(update, context)
        except ImportError:
            await query.message.reply_text("🏠 العودة للقائمة الرئيسية...")
