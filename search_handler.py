import hashlib
import re
import logging
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

# =========================
# إعدادات المشرف
# =========================
import os
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0

# =========================
# التطبيع السريع (متوافق مع DB)
# =========================
def fast_normalize(text: str) -> str:
    """تحويل الأحرف المتشابهة، إزالة التشكيل، وتنظيف النص"""
    if not text:
        return ""
    text = text.lower().strip()
    text = text.translate(str.maketrans("أإآةى", "اااهي"))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text)

# =========================
# إرسال صفحة الكتب
# =========================
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "نتائج بحث")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\n{search_stage}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_id"):
            continue
        key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([
            InlineKeyboardButton(b["file_name"][:80], callback_data=f"file:{key}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.callback_query.message.edit_text(text, reply_markup=markup)

# =========================
# محرك البحث الهجين
# =========================
async def hybrid_search(conn, user_query: str, limit: int = 200):
    norm_q = fast_normalize(user_query)
    words = [w for w in norm_q.split() if len(w) > 1]
    fts_q = " & ".join(f"{w}:*" for w in words)  # البحث على الجذور

    sql = """
    WITH ranked AS (
        SELECT
            id,
            file_id,
            file_name,
            similarity(name_normalized, $1) AS sim_score,
            ts_rank(search_vector, to_tsquery('arabic', $2)) AS fts_score
        FROM books
        WHERE
            name_normalized % $1
            OR search_vector @@ to_tsquery('arabic', $2)
    )
    SELECT *
    FROM ranked
    ORDER BY
        (name_normalized = $1) DESC,       -- التطابق التام أولاً
        sim_score * 0.7 + fts_score * 0.3 DESC  -- ترتيب حسب التشابه + FTS
    LIMIT $3;
    """
    return await conn.fetch(sql, norm_q, fts_q or norm_q, limit)

# =========================
# البحث (واجهة التليجرام)
# =========================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    query = update.message.text.strip()
    if len(query) < 2:
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    try:
        results = await hybrid_search(conn, query)

        if not results:
            await send_search_suggestions(update, context)
            context.user_data["search_results"] = []
            context.user_data["current_page"] = 0
            return

        context.user_data["search_results"] = [dict(r) for r in results]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "🔍 نتائج بحث ذكي"

        await send_books_page(update, context)

    except Exception as e:
        logger.exception("Search error")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث، حاول لاحقاً.")

# =========================
# التعامل مع أزرار الكتب والفهرس
# =========================
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            await query.message.reply_document(
                document=file_id,
                caption="📖 تم التنزيل بواسطة @boooksfree1bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("شارك البوت مع أصدقائك", switch_inline_query="")]
                ])
            )
        else:
            await query.message.reply_text("❌ الملف غير متوفر.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)

    elif data in ("home_index", "show_index"):
        from index_handler import show_index
        await show_index(update, context)
