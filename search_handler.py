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
    # كلمات لا نريدها أن تفسد البحث إذا كان العنوان طويلاً
    stop_words = {"رواية", "تحميل", "كتاب", "مجاني", "pdf", "نسخة"}
    words = text.split()
    if len(words) <= 2: return words # لا تحذف شيئاً في العناوين القصيرة
    return [w for w in words if w not in stop_words]

async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    user_id = update.effective_user.id
    pool = context.bot_data.get("db_conn")

    if not pool:
        await update.message.reply_text("❌ خطأ في الاتصال بقاعدة البيانات.")
        return

    # --- بداية عملية الربط وفحص القيود الصارمة لمدة 24 ساعة ---
    async with pool.acquire() as conn:
        # التحقق أولاً هل المستخدم مشترك مميز (Premium) لمنحه بحثاً مفتوحاً؟
        user_status = await conn.fetchrow("SELECT is_premium FROM users WHERE user_id = $1", user_id)
        
        # تجهيز رابط الدعوة الخاص بالمستخدم بشكل مسبق لاستخدامه في الأزرار والرسائل
        bot_username = context.bot.username
        referral_link = f"https://t.me/{bot_username}?start=inv_{user_id}"
        
        if not user_status or not user_status['is_premium']:
            now = datetime.now()
            block_until = context.user_data.get("block_until")
            
            # 1. التحقق هل المستخدم يمر بفترة حظر مفروضة حالياً؟
            if block_until and now < block_until:
                remaining = block_until - now
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                
                msg = (
                    f"⚠️ **تنبيه: لقد استنفدت حد البحث اليومي المجاني (10 عمليات).**\n\n"
                    f"الرجاء الانتظار **{hours} ساعة و {minutes} دقيقة** حتى ينتهي الحظر تلقائياً، أو يمكنك تفعيل اللامحدود الآن عبر أحد الخيارات التالية:\n\n"
                    f"💳 **الخيار السريع (الاشتراك المدفوع):**\n"
                    f"• اشترك في العضوية المميزة بمبلغ **5$ دولارات فقط شهرياً** للبحث بلا حدود.\n"
                    f"📩 للتفعيل الفوري تواصل معنا: @HMDALataar\n\n"
                    f"🎁 **الخيار المجاني (دعم البوت):**\n"
                    f"• شارك البوت مع أصدقائك أو في المجموعات عبر الزر أدناه.\n"
                    f"• بمجرد ضغط **أحد أصدقائك** على رابطك، سيقوم البوت تلقائياً بتفعيل **البريميوم لحسابك مجاناً لمدة أسبوعين كاملين!**"
                )
                
                share_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 انشر البوت مع أصدقائك الآن", switch_inline_query=f"\nأفضل بوت تليجرام لتحميل الكتب والروايات مجاناً! 📚\nادخل وجربه من هنا: {referral_link}")]
                ])
                
                await update.message.reply_text(msg, reply_markup=share_keyboard, parse_mode="Markdown")
                return

            # 2. إذا لم يكن محظوراً، نقوم بفحص الحد عبر الدالة الأساسية للبوت
            can_search = await check_search_limit(user_id, conn)
            if not can_search:
                # إذا استنفد حدوده الآن، نفرض عليه حظراً زمنياً دقيقاً لمدة 24 ساعة كاملة
                context.user_data["block_until"] = now + timedelta(days=1)
                
                msg = (
                    "⚠️ **تنبيه: لقد استنفدت حد البحث اليومي المجاني (10 عمليات).**\n\n"
                    "يمكنك تفعيل البحث اللامحدود فوراً وتخطي الحظر عبر أحد الخيارات التالية:\n\n"
                    "💳 **الخيار السريع (الاشتراك المدفوع):**\n"
                    "• اشترك في العضوية المميزة بمبلغ **5$ دولارات فقط شهرياً** للبحث بلا حدود.\n"
                    "📩 للتفعيل الفوري تواصل معنا: @HMDALataar\n\n"
                    "🎁 **الخيار المجاني (دعم البوت):**\n"
                    "• شارك البوت مع أصدقائك أو في المجموعات عبر الزر أدناه.\n"
                    "• بمجرد ضغط **أحد أصدقائك** على رابطك، سيقوم البوت تلقائياً بتفعيل **البريميوم لحسابك مجاناً لمدة أسبوعين كاملين!**"
                )
                
                share_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 انشر البوت مع أصدقائك الآن", switch_inline_query=f"\nأفضل بوت تليجرام لتحميل الكتب والروايات مجاناً! 📚\nادخل وجربه من هنا: {referral_link}")]
                ])
                
                await update.message.reply_text(msg, reply_markup=share_keyboard, parse_mode="Markdown")
                return
    # --- نهاية عملية الربط وفحص القيود ---

    norm_q = normalize_query(query)
    keywords = get_clean_keywords(norm_q)
    
    # تحويل الكلمات لصيغة البحث النصي (AND search)
    ts_query = ' & '.join([f"{w}:*" for w in keywords])

    try:
        # استخدام الـ pool لتنفيذ الاستعلام
        async with pool.acquire() as conn:
            # استعلام SQL هجين يجمع بين 3 تقنيات للبحث في آن واحد
            sql = """
            SELECT file_id, file_name,
                   -- 1. وزن البحث النصي (FTS)
                   ts_rank_cd(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) AS rank,
                   -- 2. نسبة التشابه الإملائي (Trigram)
                   similarity(file_name, $2) AS sim
            FROM books
            WHERE 
                to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1) -- البحث بالجذور
                OR file_name ILIKE $3 -- البحث عن الجملة كما هي (حل مشكلة لست اسفة)
                OR file_name % $2   -- البحث بالتشابه (حتى لو أخطأ المستخدم في حرف)
            ORDER BY 
                (file_name ILIKE $3) DESC, -- الأولوية المطلقة للتطابق التام
                rank DESC, 
                sim DESC
            LIMIT $4;
            """
            
            full_pattern = f"%{query.strip()}%"
            rows = await conn.fetch(sql, ts_query, norm_q, full_pattern, MAX_RESULTS)

        if not rows:
            # إذا لم نجد شيئاً، نستدعي نظام الاقتراحات الذكي
            from search_suggestions import send_search_suggestions
            context.user_data["last_query"] = query
            await send_search_suggestions(update, context)
            return

        # حفظ النتائج وعرض الصفحة الأولى
        context.user_data["search_results"] = [dict(r) for r in rows]
        context.user_data["current_page"] = 0
        context.user_data["search_stage"] = "✅ نتائج ذكية"
        await send_books_page(update, context)

    except Exception as e:
        logger.error(f"Search Error: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء البحث، يرجى المحاولة لاحقاً.")

# دالة عرض النتائج (صفحات)
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
        # تقصير الاسم الطويل جداً ليناسب أزرار تليجرام
        clean_name = b['file_name'] if len(b['file_name']) < 50 else b['file_name'][:47] + "..."
        key = hashlib.md5(b['file_id'].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b['file_id']
        keyboard.append([InlineKeyboardButton(f"📖 {clean_name}", callback_data=f"file:{key}")])

    # أزرار التنقل
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

# دالة معالجة الأزرار (التنقل والتحميل)
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            # إضافة زر المشاركة في كيبورد خاص تحت الملف المرسل
            share_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 مشاركة البوت", switch_inline_query="")]
            ])
            # إرسال الملف مع الكابشن والزر المطلوب بنظام الماركداون
            await query.message.reply_document(
                document=file_id,
                caption="تم التنزيل بواسطة @boooksfree1bot",
                reply_markup=share_keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("❌ عذراً، انتهت صلاحية هذا الرابط. ابحث مجدداً.")
            
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context)
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context)
