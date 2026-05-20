import hashlib
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultDocument, InlineQueryResultCachedDocument, InputTextMessageContent
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@iiollr"

async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        # حماية: في حال فشل الاتصال بتليجرام نعتبره مشتركاً لكي لا ننفر المستخدم
        return True

# ===============================================
# المعالج المحصن والقاطع للبحث المضمن
# ===============================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    inline_query = update.inline_query
    query = inline_query.query.strip()
    user_id = update.effective_user.id
    pool = context.bot_data.get("db_conn")

    results = []

    # 1. حالة الاستعداد الفورية (تعمل رغماً عن قاعدة البيانات)
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
        await inline_query.answer(results, cache_time=0)
        return

    # 2. التحقق من الاشتراك
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
        await inline_query.answer(results, cache_time=0)
        return

    # 3. فحص اتصال قاعدة البيانات (إذا لم تكن جاهزة، نظهر رسالة خطأ واضحة بدل الصمت)
    if not pool:
        results.append(
            InlineQueryResultDocument(
                id="db_error_inline",
                title="⚙️ السيرفر قيد التحديث أو قاعدة البيانات غير متصلة",
                description="يرجى المحاولة مرة أخرى خلال ثوانٍ...",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent("❌ عذراً، نواجه مشكلة مؤقتة في الاتصال بقاعدة البيانات.")
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    # 4. معالجة النصوص الآمنة (حتى لو فشل الاستيراد من search_handler)
    try:
        from search_handler import normalize_query, get_clean_keywords
        norm_q = normalize_query(query)
        keywords = get_clean_keywords(norm_q)
        ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else f"{norm_q}:*"
    except Exception as e:
        logger.error(f"Import failed, using emergency fallback normalization: {e}")
        # معالجة يدوية طارئة داخل الملف لحل أزمة "نظرية الفستق"
        norm_q = query.lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
        ts_query = f"{norm_q}:*"

    full_pattern = f"%{query}%"
    norm_pattern = f"%{norm_q}%"

    # 5. الاستعلام الفعلي
    async with pool.acquire() as conn:
        try:
            sql = """
            SELECT file_id, file_name
            FROM books
            WHERE 
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
                OR file_name ILIKE $2
                OR replace(replace(replace(replace(replace(lower(file_name), 'أ', 'ا'), 'إ', 'a'), 'آ', 'ا'), 'ة', 'ه'), 'ى', 'ي') ILIKE $3
            LIMIT 10;
            """
            rows = await conn.fetch(sql, ts_query, full_pattern, norm_pattern)
            
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
            logger.error(f"Database Query Crash: {e}")

    # 6. إذا اكتمل البحث ولم يتم العثور على نتائج
    if not results:
        results.append(
            InlineQueryResultDocument(
                id="no_results",
                title="❌ عذراً، لم يتم العثور على هذا الكتاب!",
                description="تأكد من كتابة الاسم بشكل صحيح أو جرب عنوان آخر.",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    f"🔍 بحثت عن: *{query}* ولم أعثر عليه في المكتبة الفورية."
                )
            )
        )

    # إرسال النتيجة مع تصفير الكاش تماماً لإجبار التطبيق على التحديث الفوري
    await inline_query.answer(results, cache_time=0)
