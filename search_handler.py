import hashlib
import re
import logging
from typing import List
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# استيراد دالة الفحص من الملف المنفرد
from limit_handler import check_search_limit

# إعداد اللوج لتتبع أي أخطاء
logger = logging.getLogger(__name__)

# الإعدادات
BOOKS_PER_PAGE = 10
MAX_RESULTS = 500  # عدد كافٍ جداً وشامل ودقيق

# دالة التطبيع (يجب أن تتطابق مع منطق قاعدة البيانات)
def normalize_query(text: str) -> str:
    if not text: return ""
    text = text.lower().strip()
    repls = str.maketrans("أإآةى", "اااوه")
    text = text.translate(repls)
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())

# تنظيف الكلمات الجانبية
def get_clean_keywords(text: str) -> List[str]:
    stop_words = {"رواية", "تحميل", "كتاب", "مجاني", "pdf", "نسخة"}
    words = text.split()
    if len(words) <= 2: return words
    return [w for w in words if w not in stop_words]

async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    user_id = update.effective_user.id
    pool = context.bot_data.get("db_conn")

    if not pool:
        await update.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    async with pool.acquire() as conn:

        # 🔥 فحص البريميوم الحقيقي
        user_status = await conn.fetchrow(
            "SELECT is_premium FROM users WHERE user_id = $1",
            user_id
        )

        is_premium = user_status and user_status["is_premium"]

        bot_username = context.bot.username
        referral_link = f"https://t.me/{bot_username}?start=inv_{user_id}"

        if not is_premium:
            now = datetime.now()
            block_until = context.user_data.get("block_until")

            if block_until and now < block_until:
                remaining = block_until - now
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60

                msg = (
                    f"⚠️ **تنبيه: لقد استنفدت حد البحث اليومي المجاني (10 عمليات).**\n\n"
                    f"الرجاء الانتظار **{hours} ساعة و {minutes} دقيقة**\n"
                    f"أو فعّل البريميوم."
                )

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 مشاركة", switch_inline_query=f"انضم للبوت {referral_link}")]
                ])

                await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
                return

            can_search = await check_search_limit(user_id, conn)

            if not can_search:
                context.user_data["block_until"] = now + timedelta(days=1)

                msg = (
                    "⚠️ **لقد استنفدت حد البحث اليومي (10 عمليات).**\n\n"
                    "🎁 شارك البوت لتفعيل البريميوم مجاناً"
                )

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 انشر البوت", switch_inline_query=f"{referral_link}")]
                ])

                await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
                return

    norm_q = normalize_query(query)
    keywords = get_clean_keywords(norm_q)
    ts_query = ' & '.join([f"{w}:*" for w in keywords])

    try:
        async with pool.acquire() as conn:

            sql = """
            SELECT file_id, file_name,
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
            LIMIT $4;
            """

            full_pattern = f"%{query.strip()}%"
            rows = await conn.fetch(sql, ts_query, norm_q, full_pattern, MAX_RESULTS)

        if not rows:
            from search_suggestions import send_search_suggestions
            context.user_data["last_query"] = query
            await send_search_suggestions(update, context)
            return

        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "✅ نتائج ذكية"
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search Error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث، يرجى المحاولة لاحقاً.")


async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    results = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_batch = results[start:end]
    total_pages = (len(results) - 1) // BOOKS_PER_PAGE + 1

    text = f"📚 **نتائج البحث ({len(results)} نتيجة):**\n"
    text += f"صفحة {page + 1} من {total_pages}\n\n"

    keyboard = []

    for b in current_batch:
        clean_name = b['file_name'] if len(b['file_name']) < 50 else b['file_name'][:47] + "..."
        key = hashlib.md5(b['file_id'].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b['file_id']
        keyboard.append([InlineKeyboardButton(f"📖 {clean_name}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(results):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")

        if file_id:
            share_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
            ])

            await query.message.reply_document(
                document=file_id,
                caption="تم التنزيل بواسطة @boooksfree1bot",
                reply_markup=share_keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("❌ انتهت صلاحية الرابط.")

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)

    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
