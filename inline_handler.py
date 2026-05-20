import os
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

# إعداد اللوج الخاص بالملف لتعقب العمليات بدقة كاملة في السجلات
logger = logging.getLogger(__name__)

# اسم القناة الداعمة للاشتراك الإجباري
CHANNEL_USERNAME = "@iiollr"

# ===============================================
# دالة تطبيق وتطهير النص داخلياً لتفادي مشاكل الإملاء
# ===============================================
def local_normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    
    # خريطة استبدال وتوحيد الحروف المتشابهة
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ة': 'ه',
        'ى': 'ي',
        'ئ': 'ء', 'ؤ': 'ء'
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
        
    # إزالة الحركات والتنوين بالكامل لتوحيد البحث النصي
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    # إزالة الفراغات الزائدة والرموز المزعجة
    text = re.sub(r"\s+", " ", text)
        
    return text.strip()

# دالة استخراج الكلمات المفتاحية النظيفة للبحث المتقدم
def local_get_keywords(text: str) -> list:
    cleaned = local_normalize_text(text)
    words = [w for w in cleaned.split() if len(w) > 1]
    return words

# ===============================================
# دالة التحقق الآمن من الاشتراك الإجباري
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"⚠️ [نقطة تتبع]: فشل فحص الاشتراك للمستخدم {user_id} بسبب: {e}")
        return True

# ===============================================
# دالة مساعدة لتوليد كائنات النصوص الآمنة (Articles)
# ===============================================
def make_article_result(result_id: str, title: str, description: str, message_text: str):
    return InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(message_text, parse_mode="Markdown")
    )

# ===============================================
# معالج البحث المضمن الجذري والمحصن بالكامل
# ===============================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    inline_query = update.inline_query
    if not inline_query:
        return

    query = inline_query.query.strip()
    user = update.effective_user
    user_id = user.id if user else 0
    
    logger.info(f"📥 [طلب جديد]: مستخدم [{user_id}] يبحث عن بُعد عن: '{query}'")

    pool = context.bot_data.get("db_conn") or context.bot_data.get("db_pool")
    results = []

    # 🛑 1. حالة الاستعداد الفوري (إذا لم يكتب المستخدم شيئاً بعد المعرف)
    if not query:
        logger.info(f"⏱️ [نقطة تتبع 2]: حقل النص فارغ، عرض واجهة الاستعداد للمستخدم [{user_id}]")
        results.append(
            make_article_result(
                result_id="welcome_waiting_state",
                title="🔍 أهلاً بك في البحث الفوري للمكتبة!",
                description="ابدأ بكتابة اسم الكتاب أو الرواية هنا للبحث الفوري...",
                message_text="💡 **طريقة استخدام البحث عن بُعد:**\nاكتب اسم أي كتاب تريده مباشرة بعد معرف البوت في حقل النص داخل أي شات.\n\n*مثال:* `@boooksfree1bot نظرية الفستق`"
            )
        )
        await inline_query.answer(results, cache_time=0, is_personal=True)
        return

    # 🛑 2. التحقق من الاشتراك الإجباري
    is_subbed = await check_subscription(user_id, context.bot)
    if not is_subbed:
        logger.warning(f"🚫 [نقطة تتبع 3]: المستخدم [{user_id}] غير مشترك في القناة الداعمة. تم حجب النتائج.")
        results.append(
            make_article_result(
                result_id="sub_required_state",
                title="⚠️ يجب الاشتراك في القناة أولاً لاستخدام البحث!",
                description=f"انقر هنا للاشتراك في {CHANNEL_USERNAME} لتفعيل ميزة البحث.",
                message_text=f"🚫 **عذراً، يجب عليك الاشتراك أولاً في قناة البوت الرسمية {CHANNEL_USERNAME}** لتتمكن من استخدام ميزة البحث الفوري وتحميل الكتب من أي مكان!"
            )
        )
        await inline_query.answer(results, cache_time=0, is_personal=True)
        return

    # 🛑 3. التحقق من استقرار اتصال قاعدة البيانات في السيرفر
    if not pool:
        logger.error(f"🚨 [خطأ فادح]: اتصال قاعدة البيانات (db_conn/db_pool) مفقود في الـ bot_data!")
        results.append(
            make_article_result(
                result_id="db_disconnect_state",
                title="⚙️ السيرفر قيد الصيانة أو التحديث المؤقت",
                description="نعمل على تحسين النظام، يرجى المحاولة مرة أخرى خلال ثوانٍ...",
                message_text="❌ عذراً، نواجه صيانة مؤقتة في محرك البحث الفوري عن بُعد، يرجى استخدام البحث الاعتيادي داخل شات البوت حالياً."
            )
        )
        await inline_query.answer(results, cache_time=0, is_personal=True)
        return

    # ⚙️ 4. معالجة وتطهير النص داخلياً للبحث الاستعلامي الذكي
    norm_q = local_normalize_text(query)
    keywords = local_get_keywords(query)
    
    ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else f"{norm_q}:*"
    full_pattern = f"%{query}%"
    norm_pattern = f"%{norm_q}%"

    # 🛑 5. تنفيذ استعلام قاعدة البيانات
    try:
        logger.info(f"⚡ [نقطة تتبع 4]: جاري إرسال الاستعلام لـ PostgreSQL للنص المطهر: '{norm_q}'")
        
        async with pool.acquire() as conn:
            sql = """
            SELECT file_id, file_name
            FROM books
            WHERE 
                ($1 != '' AND to_tsvector('simple', lower(file_name)) @@ to_tsquery('simple', $1))
                OR file_name ILIKE $2
                OR replace(replace(replace(replace(replace(lower(file_name), 'أ', 'ا'), 'إ', 'a'), 'آ', 'a'), 'ة', 'ه'), 'ى', 'ي') ILIKE $3
            ORDER BY (file_name ILIKE $2) DESC, file_name ASC
            LIMIT 15;
            """
            rows = await conn.fetch(sql, ts_query, full_pattern, norm_pattern)
            
            logger.info(f"📊 [نقطة تتبع 5]: اكتمل الاستعلام بنجاح. عثرنا على ({len(rows)}) كتاب.")

            for i, row in enumerate(rows):
                file_id = str(row['file_id'])
                file_name = str(row['file_name'])
                
                unique_id = hashlib.md5(f"{file_id}_{i}".encode()).hexdigest()
                
                results.append(
                    InlineQueryResultCachedDocument(
                        id=unique_id,
                        title=file_name,
                        document_file_id=file_id,  # ✅ تم التثبيت والتصحيح الجذري هنا
                        description="اضغط هنا لإرسال الكتاب فوراً كملف PDF",
                        caption=f"📖 **{file_name}**\n\nتم التحميل بواسطة: @boooksfree1bot",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                        ])
                    )
                )
                
    except Exception as db_error:
        import traceback
        logger.error(f"💥 [انهيار برمي داخل الاستعلام]: {traceback.format_exc()}")
        
        results = [
            make_article_result(
                result_id="query_crash_state",
                title="⚠️ حدث عطل داخلي مؤقت أثناء معالجة البحث",
                description="فريق الدعم يعمل على حل العطل حالياً، جرب كتابة اسم الكتاب مجدداً.",
                message_text="❌ عذراً، فشلت عملية معالجة طلبك الفوري بسبب ضغط أو صيانة مؤقتة في خادم قاعدة البيانات."
            )
        ]
        await inline_query.answer(results, cache_time=0, is_personal=True)
        return

    # 🛑 6. في حال لم يتم العثور على أي نتائج مطابقة في النظام
    if not results:
        logger.info(f"🔍 [نقطة تتبع 6]: لا توجد أي نتائج مطابقة لـ '{query}' في الفهارس.")
        results.append(
            make_article_result(
                result_id="no_results_found_state",
                title=f"❌ لم يتم العثور على نتائج لـ: '{query}'",
                description="تأكد من كتابة الحروف بشكل صحيح أو ابحث عن اسم كتاب آخر.",
                message_text=f"🔍 بحثت عن: *{query}* في المكتبة الفورية ولم أعثر على نتائج مطابقة.\n\n💡 *نصيحة:* جرب كتابة كلمة واحدة فريدة من اسم الكتاب، أو ابحث عبر الفهرس الذكي داخل البوت الرئيسي."
            )
        )

    # إرسال البيانات النهائية الآمنة للتليجرام
    try:
        await inline_query.answer(results, cache_time=0, is_personal=True)
        logger.info(f"🚀 [نقطة تتبع 7]: تم تسليم وتمرير قائمة النتائج الفورية إلى تليجرام بنجاح.")
    except Exception as telegram_error:
        logger.error(f"🚨 [خطأ واجهة تليجرام]: فشل البوت في تسليم الإجابة عبر الـ API: {telegram_error}")
