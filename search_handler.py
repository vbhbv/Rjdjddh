import re
import logging
from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

BOOKS_PER_PAGE = 10
MAX_RESULTS = 500

# -----------------------------
# التطبيع
# -----------------------------
def normalize_query(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    repls = str.maketrans("أإآةى", "اااوه")
    text = text.translate(repls)
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())

def get_clean_keywords(text: str) -> List[str]:
    stop_words = {"رواية", "تحميل", "كتاب", "مجاني", "pdf", "نسخة", "اريد"}
    words = text.split()
    if len(words) <= 2:
        return words
    return [w for w in words if w not in stop_words]

# -----------------------------
# البحث
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    conn = context.bot_data.get("db_conn")

    if not conn:
        await update.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    norm_q = normalize_query(query)
    keywords = get_clean_keywords(norm_q)

    ts_and = " & ".join([f"{w}:*" for w in keywords])
    ts_or = " | ".join([f"{w}:*" for w in keywords])
    full_pattern = f"%{norm_q}%"

    try:
        sql = """
        WITH candidates AS (
            SELECT id, file_id, file_name
            FROM books
            WHERE
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
                OR file_name ILIKE $2
                OR file_name % $3
            LIMIT 1000
        )
        SELECT id, file_id, file_name,
               ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
               similarity(file_name, $3) AS sim
        FROM candidates
        ORDER BY
            (file_name ILIKE $2) DESC,
            rank DESC,
            sim DESC
        LIMIT $4;
        """

        rows = await conn.fetch(sql, ts_and, full_pattern, norm_q, MAX_RESULTS)

        if not rows:
            rows = await conn.fetch(sql, ts_or, full_pattern, norm_q, MAX_RESULTS)

        if not rows:
            from search_suggestions import send_search_suggestions
            context.user_data["last_query"] = query
            await send_search_suggestions(update, context)
            return

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث.")

# -----------------------------
# عرض النتائج
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    results = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    batch = results[start:end]
    total_pages = (len(results) - 1) // BOOKS_PER_PAGE + 1

    text = f"📚 **نتائج البحث ({len(results)} نتيجة)**\n"
    text += f"الصفحة {page + 1} من {total_pages}\n\n"

    keyboard = []
    for b in batch:
        name = b["file_name"]
        name = name if len(name) < 48 else name[:45] + ".."
        keyboard.append([
            InlineKeyboardButton(
                f"📖 {name}",
                callback_data=f"file:{b['id']}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(results):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav:
        keyboard.append(nav)

    markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")

# -----------------------------
# callbacks (الإرسال مقتبس من الكود القديم)
# -----------------------------
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = context.bot_data.get("db_conn")

    await query.answer()  # ✅ نفس القديم حرفيًا

    if data.startswith("file:"):
        book_id = int(data.split(":")[1])
        row = await conn.fetchrow(
            "SELECT file_id, file_name FROM books WHERE id = $1",
            book_id
        )

        if row:
            try:
                await query.message.reply_document(
                    document=row["file_id"],
                    caption="تم تنزيل الكتاب بواسطة @boooksfree1bot",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                    ])
                )
            except Exception as e:
                logger.error(f"Download error: {e}")
                await query.message.reply_text("❌ فشل إرسال الملف.")
        else:
            await query.message.reply_text("❌ الملف غير موجود.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
