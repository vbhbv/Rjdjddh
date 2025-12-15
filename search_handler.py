import hashlib
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging

BOOKS_PER_PAGE = 10
MAX_RESULTS = 500

logger = logging.getLogger(__name__)

# ======================
# تنظيف ذكي
# ======================
def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("أ","ا").replace("إ","ا").replace("آ","ا")
    text = text.replace("ة","ه").replace("ى","ي")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_keywords(q: str):
    words = normalize(q).split()
    return [w for w in words if len(w) >= 2]

# ======================
# عرض النتائج
# ======================
async def send_books_page(update, context):
    books = context.user_data["results"]
    page = context.user_data.get("page",0)

    total_pages = (len(books)-1)//BOOKS_PER_PAGE + 1
    start = page*BOOKS_PER_PAGE
    end = start+BOOKS_PER_PAGE

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page+1} من {total_pages}\n\n"
    keyboard = []

    for b in books[start:end]:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[key] = b["file_id"]
        keyboard.append([InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")])

    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev"))
    if end < len(books):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next"))
    if nav:
        keyboard.append(nav)

    await update.callback_query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ======================
# البحث العالمي الحقيقي
# ======================
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    q = update.message.text.strip()
    conn = context.bot_data["db_conn"]

    keywords = extract_keywords(q)
    phrase = " ".join(keywords)

    results = []

    # 1️⃣ PHRASE MATCH (أعلى دقة)
    sql_phrase = """
    SELECT *, ts_rank(search_vector, phraseto_tsquery('arabic', $1)) AS rank
    FROM books
    WHERE search_vector @@ phraseto_tsquery('arabic', $1)
    ORDER BY rank DESC
    LIMIT $2;
    """
    rows = await conn.fetch(sql_phrase, phrase, MAX_RESULTS)
    if rows:
        results = rows
    else:
        # 2️⃣ ALL WORDS (AND)
        ts_and = " & ".join(keywords)
        sql_and = """
        SELECT *, ts_rank(search_vector, to_tsquery('arabic', $1)) AS rank
        FROM books
        WHERE search_vector @@ to_tsquery('arabic', $1)
        ORDER BY rank DESC
        LIMIT $2;
        """
        rows = await conn.fetch(sql_and, ts_and, MAX_RESULTS)
        if rows:
            results = rows
        else:
            # 3️⃣ ANY WORD (OR – أضعف)
            ts_or = " | ".join(keywords)
            sql_or = """
            SELECT *, ts_rank(search_vector, to_tsquery('arabic', $1)) AS rank
            FROM books
            WHERE search_vector @@ to_tsquery('arabic', $1)
            ORDER BY rank DESC
            LIMIT $2;
            """
            results = await conn.fetch(sql_or, ts_or, MAX_RESULTS)

    if not results:
        await update.message.reply_text("❌ لا توجد نتائج دقيقة")
        return

    context.user_data["results"] = [dict(r) for r in results]
    context.user_data["page"] = 0

    fake_update = update
    fake_update.callback_query = update
    await send_books_page(fake_update, context)

# ======================
# أزرار
# ======================
async def handle_callbacks(update, context):
    q = update.callback_query
    await q.answer()

    if q.data=="next":
        context.user_data["page"]+=1
        await send_books_page(update, context)

    elif q.data=="prev":
        context.user_data["page"]-=1
        await send_books_page(update, context)

    elif q.data.startswith("file:"):
        fid = context.bot_data.get(q.data.split(":")[1])
        if fid:
            await q.message.reply_document(fid)
