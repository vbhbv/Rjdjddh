import os
import hashlib
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultDocument, InlineQueryResultCachedDocument, InputTextMessageContent
from telegram.ext import ContextTypes

# إعداد اللوج الخاص بالملف لتعقب العمليات بدقة
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@iiollr"

# ===============================================
# دالة تطبيق وتطهير النص داخلياً (الأساس الجذري لحل مشاكل الإملاء)
# ===============================================
def local_normalize_text(text: str) -> str:
    if not text:
        return ""
    # تحويل الحروف إلى حالاتها الصغيرة وإزالة الفراغات الزائدة
    text = text.strip().lower()
    
    # خريطة استبدال الحروف المتشابهة لتجاوز الأخطاء الإملائية (نظرية الفستق / أحمد)
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ة': 'ه',
        'ى': 'ي',
        'ئ': 'ء', 'ؤ': 'ء'
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
        
    # إزالة الحركات والتنوين تماماً لتوحيد البحث النصي
    vowels = ['َ', 'ُ', 'ِ', 'ّ', 'ً', 'ٌ', 'ٍ', 'ْ']
    for vowel in vowels:
        text = text.replace(vowel, '')
        
    return text

# دالة استخراج الكلمات المفتاحية النظيفة للبحث المتقدم
def local_get_keywords(text: str) -> list:
    cleaned = local_normalize_text(text)
    # تقسيم النص إلى كلمات وتجاهل الكلمات الصغيرة جداً (الزائدة)
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
        logger.error(f"Subscription check bypass/error: {e}")
        # في حال حدوث أي خطأ في الاتصال بتليجرام، نمرر المستخدم لتفادي تعطيل البوت
        return True

# ===============================================
# معالج البحث المضمن الجذري والمحصن بالكامل
# ===============================================
async def inline_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    inline_query = update.inline_query
    if not inline_query:
        return

    query = inline_query.query.strip()
    user_id = update.effective_user.id if update.effective_user else 0
    pool = context.bot_data.get("db_conn")
    results = []

    # 🛑 1. حالة الاستعداد الفوري (إذا لم يكتب المستخدم شيئاً بعد المعرف)
    if not query:
        results.append(
            InlineQueryResultDocument(
                id="emergency_waiting_state",
                title="🔍 أهلاً بك في البحث الفوري للمكتبة!",
                description="ابدأ بكتابة اسم الكتاب أو الرواية هنا للبحث الفوري...",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    "💡 **طريقة الاستخدام:**\nاكتب اسم أي كتاب تريده مباشرة بعد معرف البوت في حقل النص (مثال: `@boooksfree1bot نظرية الفستق`)."
                )
            )
        )
        # cache_time=0 يضمن عدم تخزين تليجرام لأي شاشة بيضاء أو حالة فارغة
        await inline_query.answer(results, cache_time=0)
        return

    # 🛑 2. التحقق من الاشتراك الإجباري
    if not await check_subscription(user_id, context.bot):
        results.append(
            InlineQueryResultDocument(
                id="emergency_sub_required",
                title="⚠️ يجب الاشتراك في القناة أولاً لاستخدام البحث!",
                description=f"انقر هنا للاشتراك في {CHANNEL_USERNAME} لتفعيل الميزة.",
                document_url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    f"🚫 **عذراً، يجب عليك الاشتراك أولاً في قناة البوت الرسمية {CHANNEL_USERNAME}** لتتمكن من استخدام ميزة البحث الفوري وتحميل الكتب من أي مكان!"
                )
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    # 🛑 3. التحقق من استقرار اتصال قاعدة البيانات
    if not pool:
        logger.error("🚨 Inline Mode failure: Database pool is NOT initialized or missing in bot_data.")
        results.append(
            InlineQueryResultDocument(
                id="emergency_db_disconnect",
                title="⚙️ السيرفر قيد التحديث المؤقت",
                description="نعمل على تحسين النظام، يرجى المحاولة مرة أخرى خلال ثوانٍ...",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent("❌ عذراً، نواجه صيانة مؤقتة في محرك البحث الفوري، يرجى استخدام البحث داخل البوت حالياً.")
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    # ⚙️ 4. معالجة وتطبيق النص داخلياً للبحث الاستعلامي الذكي
    norm_q = local_normalize_text(query)
    keywords = local_get_keywords(query)
    
    # بناء استعلام tsquery المتوافق مع الفهرس العربي
    ts_query = ' & '.join([f"{w}:*" for w in keywords]) if keywords else f"{norm_q}:*"
    full_pattern = f"%{query}%"
    norm_pattern = f"%{norm_q}%"

    # 🛑 5. تنفيذ استعلام قاعدة البيانات داخل كتلة Try-Except محصنة كلياً لمنع الـ Crash
    try:
        async with pool.acquire() as conn:
            # استعلام فائق الذكاء يطابق الفهرس العربي، الـ ILIKE، والتطهير النصي للحروف مجتمعين
            sql = """
            SELECT file_id, file_name
            FROM books
            WHERE 
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
                OR file_name ILIKE $2
                OR replace(replace(replace(replace(replace(lower(file_name), 'أ', 'a'), 'إ', 'a'), 'آ', 'a'), 'ة', 'ه'), 'ى', 'ي') ILIKE $3
            ORDER BY (file_name ILIKE $2) DESC
            LIMIT 15;
            """
            rows = await conn.fetch(sql, ts_query, full_pattern, norm_pattern)
            
            for i, row in enumerate(rows):
                # توليد معرف فريد وآمن لكل نتيجة لمنع التضارب داخلياً
                unique_id = f"in_bk_{i}_{hashlib.md5(row['file_id'].encode()).hexdigest()[:6]}"
                
                results.append(
                    InlineQueryResultCachedDocument(
                        id=unique_id,
                        title=row['file_name'],
                        file_id=row['file_id'], # إرسال الملف الفوري الأصلي دون رفع أو روابط
                        caption=f"📖 **{row['file_name']}**\n\nتم التحميل بواسطة: @boooksfree1bot",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
                        ])
                    )
                )
    except Exception as db_error:
        logger.error(f"💥 Critical Inline Database Query Exception: {db_error}", exc_info=True)
        # منع الصمت المبهم: حتى لو انهارت قاعدة البيانات أثناء الاستعلام، نبلغ المستخدم فوراً بدل التجمد
        results = [
            InlineQueryResultDocument(
                id="emergency_query_crash",
                title="⚠️ حدث خطأ غير متوقع أثناء معالجة البحث",
                description="جاري إصلاح العطل تلقائياً، يرجى محاولة كتابة اسم الكتاب مجدداً.",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent("❌ عذراً، فشلت عملية معالجة استعلامك الفوري بسبب ضغط مؤقت.")
            )
        ]
        await inline_query.answer(results, cache_time=0)
        return

    # 🛑 6. في حال لم يتم العثور على أي نتائج مطابقة في النظام
    if not results:
        results.append(
            InlineQueryResultDocument(
                id="emergency_no_results_found",
                title=f"❌ لم يتم العثور على: '{query}'",
                description="تأكد من كتابة الاسم بشكل صحيح أو ابحث عن عنوان كتاب آخر.",
                document_url="https://t.me/boooksfree1bot",
                mime_type="text/html",
                input_message_content=InputTextMessageContent(
                    f"🔍 بحثت عن: *{query}* في المكتبة الفورية ولم أعثر عليه.\nتأكد من عنوان الكتاب بدقة أو جرب البحث داخل البوت الرئيسي."
                )
            )
        )

    # إرسال البيانات النهائية للتليجرام مع إلغاء الكاش لضمان الاستجابة اللحظية مع كل حرف
    try:
        await inline_query.answer(results, cache_time=0)
    except Exception as telegram_error:
        logger.error(f"🚨 Failed to send inline response to Telegram: {telegram_error}")
