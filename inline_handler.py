import re
import hashlib
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedDocument,
    InputTextMessageContent
)

from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@iiollr"


# =========================================
# تطبيع النص العربي
# =========================================
def normalize(text: str) -> str:

    if not text:
        return ""

    text = text.lower().strip()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "ء",
        "ئ": "ء"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[ًٌٍَُِّْ]", "", text)

    return text


# =========================================
# التحقق من الاشتراك
# =========================================
async def check_subscription(user_id, bot):

    try:

        member = await bot.get_chat_member(
            CHANNEL_USERNAME,
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except:
        return True


# =========================================
# عنصر نصي مساعد
# =========================================
def article(id_, title, desc, text):

    return InlineQueryResultArticle(
        id=id_,
        title=title,
        description=desc,
        input_message_content=InputTextMessageContent(
            text
        )
    )


# =========================================
# البحث المضمن
# =========================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):

    inline_query = update.inline_query

    if not inline_query:
        return

    query = inline_query.query.strip()

    user_id = (
        update.effective_user.id
        if update.effective_user
        else 0
    )

    results = []

    # قاعدة البيانات
    pool = context.bot_data.get("db_conn")

    # =====================================
    # بدون نص
    # =====================================
    if not query:

        results.append(
            article(
                "welcome",
                "🔍 البحث الفوري للمكتبة",
                "اكتب اسم أي كتاب",
                "📚 اكتب اسم الكتاب بعد معرف البوت مباشرة."
            )
        )

        await inline_query.answer(
            results,
            cache_time=0,
            is_personal=True
        )

        return

    # =====================================
    # تحقق الاشتراك
    # =====================================
    subscribed = await check_subscription(
        user_id,
        context.bot
    )

    if not subscribed:

        results.append(
            article(
                "sub_required",
                "⚠️ يجب الاشتراك بالقناة",
                CHANNEL_USERNAME,
                f"اشترك أولاً في {CHANNEL_USERNAME}"
            )
        )

        await inline_query.answer(
            results,
            cache_time=0,
            is_personal=True
        )

        return

    # =====================================
    # تحقق قاعدة البيانات
    # =====================================
    if not pool:

        results.append(
            article(
                "db_error",
                "⚙️ السيرفر غير متصل",
                "قاعدة البيانات غير جاهزة",
                "حدث خطأ مؤقت."
            )
        )

        await inline_query.answer(
            results,
            cache_time=0,
            is_personal=True
        )

        return

    # =====================================
    # البحث
    # =====================================
    try:

        normalized = normalize(query)

        pattern1 = f"%{query}%"
        pattern2 = f"%{normalized}%"

        async with pool.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT file_id, file_name
                FROM books
                WHERE
                    lower(file_name) ILIKE lower($1)

                    OR

                    lower(name_normalized) ILIKE lower($2)

                LIMIT 15
                """,
                pattern1,
                pattern2
            )

            for i, row in enumerate(rows):

                file_id = str(row["file_id"])
                file_name = str(row["file_name"])

                unique_id = hashlib.md5(
                    f"{file_id}_{i}".encode()
                ).hexdigest()

                results.append(

                    InlineQueryResultCachedDocument(

                        id=unique_id,

                        title=file_name,

                        document_file_id=file_id,

                        description="إرسال الكتاب PDF",

                        caption=f"📚 {file_name}",

                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton(
                                    "📤 مشاركة البوت",
                                    switch_inline_query=""
                                )
                            ]
                        ])
                    )
                )

    except Exception as e:

        logger.error(f"INLINE ERROR: {e}")

        await inline_query.answer(
            [],
            cache_time=0,
            is_personal=True
        )

        return

    # =====================================
    # لا توجد نتائج
    # =====================================
    if not results:

        results.append(
            article(
                "no_results",
                "❌ لا توجد نتائج",
                query,
                f"لم يتم العثور على: {query}"
            )
        )

    # =====================================
    # إرسال النتائج
    # =====================================
    try:

        await inline_query.answer(
            results,
            cache_time=0,
            is_personal=True
        )

    except Exception as e:

        logger.error(f"INLINE SEND ERROR: {e}")
