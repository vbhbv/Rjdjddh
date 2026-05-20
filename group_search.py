import os
import re
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# إعداد اللوج لتعقب عمليات البحث داخل المجموعات
logger = logging.getLogger(__name__)

# اسم القناة الداعمة للاشتكار الإجباري
CHANNEL_USERNAME = "@iiollr"

# ===============================================
# دالة معالجة وتطهير النص لمنع مشاكل الهمزات والحركات
# ===============================================
def normalize_group_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ة': 'ه',
        'ى': 'ي',
        'ئ': 'ء', 'ؤ': 'ء'
    }
    for search, replace in replacements.items():
        text = text.replace(search, replace)
    text = re.sub(r"[ًٌٍَُِّْ]", "", text)
    return text.strip()

# ===============================================
# دالة فحص الاشتراك الإجباري لمن يطلب البحث في المجموعة
# ===============================================
async def is_user_subscribed(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"⚠️ فشل فحص اشتراك المستخدم {user_id} في المجموعة: {e}")
        return True  # تمرير آمن في حال تعطل الـ API مؤقتاً

# ===============================================
# المعالج الرئيسي لأمر /search داخل المجموعات
# ===============================================
async def group_search_books(update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    # التأكد التام من أن الرسالة من مجموعة أو سوبرجروب
    if message.chat.type not in ["group", "supergroup"]:
        return

    user = update.effective_user
    user_id = user.id if user else 0
    
    # استخراج نص البحث بعد أمر /search
    parts = message.text.split(maxsplit=1)
    
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text(
            "⚠️ **طريقة استخدام البحث في المجموعة:**\n"
            "اكتب الأمر متبوعاً باسم الكتاب.\n\n"
            "💡 *مثال:* `/search دليل رام`",
            parse_mode="Markdown"
        )
        return

    query = parts[1].strip()
    logger.info(f"👥 [بحث مجموعة]: المستخدم {user_id} يبحث عن: '{query}' في مجموعة '{message.chat.title}'")

    # 1️⃣ التحقق من الاشتراك الإجباري لصاحب الأمر
    subscribed = await is_user_subscribed(user_id, context.bot)
    if not subscribed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة أولاً", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        ])
        await message.reply_text(
            f"🚫 عذراً يا {user.mention_markdown()}!\n"
            f"يجب عليك الاشتراك في قناة البوت الرسمية {CHANNEL_USERNAME} أولاً لتتمكن من استخدام أمر البحث داخل المجموعات.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # 2️⃣ جلب اتصال قاعدة البيانات من bot_data المشترك
    pool = context.bot_data.get("db_conn")
    if not pool:
        logger.error("🚨 اتصال قاعدة البيانات مفقود أثناء البحث في المجموعة!")
        return

    # تهيئة الكلمات للبحث النصي المرن والسريع
    norm_q = normalize_group_text(query)
    search_pattern = f"%{query}%"
    norm_pattern = f"%{norm_q}%"

    try:
        async with pool.acquire() as conn:
            # استعلام الـ SQL المطهّر بالكامل والمثالي للمقارنة النصية المباشرة
            sql = """
            SELECT file_id, file_name
            FROM books
            WHERE 
                file_name ILIKE $1
                OR replace(replace(replace(replace(replace(lower(file_name), 'أ', 'ا'), 'إ', 'ا'), 'آ', 'ا'), 'ة', 'ه'), 'ى', 'ي') ILIKE $2
            ORDER BY (file_name ILIKE $1) DESC, file_name ASC
            LIMIT 5;
            """
            rows = await conn.fetch(sql, search_pattern, norm_pattern)

            if not rows:
                await message.reply_text(
                    f"🔍 عذراً، بحثت عن *{query}* ولم أعثر على نتائج مطابقة في مكتبتنا حالياً.",
                    parse_mode="Markdown"
                )
                return

            # 3️⃣ جلب الكتب وإرسالها فوراً كملفات PDF داخل المجموعة
            for row in rows:
                file_id = row['file_id']
                file_name = row['file_name']
                
                try:
                    await context.bot.send_document(
                        chat_id=message.chat_id,
                        document=file_id,
                        caption=f"📖 **{file_name}**\n\nطلبك جاهز بواسطة: {user.mention_markdown()}",
                        parse_mode="Markdown",
                        reply_to_message_id=message.message_id  # الرد على نفس رسالة الطلب
                    )
                except Exception as send_err:
                    logger.error(f"❌ فشل إرسال الملف {file_name} للمجموعة: {send_err}")

    except Exception as db_error:
        logger.error(f"💥 خطأ أثناء تنفيذ استعلام مجموعة: {db_error}")
        await message.reply_text("❌ عذراً، واجهنا مشكلة مؤقتة في محرك البحث، حاول مجدداً لاحقاً.")
