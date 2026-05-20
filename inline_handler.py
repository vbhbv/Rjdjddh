import hashlib
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultDocument, InlineQueryResultCachedDocument, InputTextMessageContent
from telegram.ext import ContextTypes

# إعداد اللوج للملف الجديد لتعقب أي أخطاء
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@iiollr"

# دالة التحقق من الاشتراك الإجباري
async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

# ===============================================
# المعالج المستقل للبحث المضمن (Inline Mode)
# ===============================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    inline_query = update.inline_query
    query = inline_query.query.strip()
    user_id = update.effective_user.id
    pool = context.bot_data.get("db_conn")

    if not pool:
        return

    results = []

    # 1. حماية البوت: التحقق من الاشتراك الإجباري بالقناة
    if not await check_subscription(user_id, context.bot):
        results.append(
            InlineQueryResultDocument(
                id="sub_required",
                title="⚠️ يجب الاشتراك في القناة أولاً لاستخدام البحث المضمن!",
                description=f"انقر هنا للاشتراك في {CHANNEL_USERNAME}",
                document_url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    f"🚫 **عذراً، يجب عليك الاشتراك أولاً في قناة البوت الرسمية {CHANNEL_USERNAME}** لتتمكن من استخدام ميزة البحث الفوري وتحميل الكتب من أي مكان!"
                )
            )
        )
        await inline_query.answer(results, cache_time=1)
        return

    # 2. حالة الاستعداد: إذا كتب المستخدم المعرف فقط ولم يكتب اسم الكتاب بعد
    if not query:
        results.append(
            InlineQueryResultDocument(
                id="waiting_query",
                title="🔍 أهلاً بك في البحث الفوري للمكتبة!",
                description="ابدأ بكتابة اسم الكتاب أو الرواية هنا للبحث...",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    "💡 ابدأ بكتابة اسم أي كتاب تريد تحميله مباشرة بعد معرف البوت في حقل النص."
                )
            )
        )
        await inline_query.answer(results, cache_time=1)
        return

    # 3. الربط بملف البحث: استيراد دالات التطبيع وتنظيف النصوص لضمان المطابقة الكاملة
    try:
        from search_handler import normalize_query, get_clean_keywords
        norm_q = normalize_query(query)
        keywords = get_clean_keywords(norm_q)
        ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else f"{norm_q}:*"
    except Exception as e:
        logger.error(f"Error importing from search_handler: {e}")
        # حل بديل (Fallback) في حال اختلف مسمى الدالات داخل ملف البحث لديك
        norm_q = query.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
        ts_query = f"{norm_q}:*"

    full_pattern = f"%{query}%"
    norm_pattern = f"%{norm_q}%"

    # 4. الاتصال بقاعدة البيانات والبحث العابر للهمزات والحروف
    async with pool.acquire() as conn:
        try:
            sql = """
            SELECT file_id, file_name,
                   ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
                   similarity(file_name, $2) AS sim
            FROM books
            WHERE 
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
                OR file_name ILIKE $3
                OR file_name % $2
                OR replace(replace(replace(replace(replace(lower(file_name), 'أ', 'ا'), 'إ', 'ا'), 'آ', 'ا'), 'ة', 'ه'), 'ى', 'ي') ILIKE $4
            ORDER BY 
                (file_name ILIKE $3) DESC, 
                rank DESC, 
                sim DESC
            LIMIT 10;
            """
            
            rows = await conn.fetch(sql, ts_query, norm_q, full_pattern, norm_pattern)
            
            for i, row in enumerate(rows):
                results.append(
                    InlineQueryResultCachedDocument(
                        id=f"inline_bk_{i}_{hashlib.md5(row['file_id'].encode()).hexdigest()[:8]}",
                        title=row['file_name'],
                        file_id=row['file_id'],
                        caption=f"📖 **{row['file_name']}**\n\nتم التحميل بواسطة: @boooksfree1bot",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                        ])
                    )
                )

        except Exception as e:
            logger.error(f"Inline Database Search Error: {e}")

    # 5. إذا لم يجد نتائج (إظهار رسالة واضحة للمستخدم بدلاً من الاختفاء المبهم)
    if not results:
        results.append(
            InlineQueryResultDocument(
                id="no_results",
                title="❌ عذراً، لم يتم العثور على هذا الكتاب!",
                description="تأكد من كتابة الاسم بشكل صحيح أو جرب كتابة عنوان آخر.",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    f"🔍 بحثت عن: *{query}* ولم أعثر عليه.\nتأكد من عنوان الكتاب وابحث مجدداً داخل البوت الرئيسي."
                )
            )
        )

    await inline_query.answer(results, cache_time=1)
