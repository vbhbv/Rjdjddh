import os
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from functools import wraps

logger = logging.getLogger(__name__)

# ===============================================
# إعدادات المشرفين
# ===============================================
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "5493390715"))  # تم ضبط المعرف الافتراضي الخاص بك
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# ===============================================
# متغير القناة الاشتراك الإجباري
# ===============================================
REQUIRED_CHANNEL_ID = None  # سيُحدد عبر /setchannel

# ===============================================
# دوال مساعدة
# ===============================================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID and ADMIN_USER_ID != 0:
            return await func(update, context, *args, **kwargs)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ أمر خاص بالمشرفين فقط.")
        return
    return wrapper

# ===============================================
# أوامر التفعيل ومنح المحاولات الإضافية (محدث لنظام الـ Credits)
# ===============================================
@admin_only
async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمنح مستخدم 10 محاولات بحث إضافية فوراً: /set_premium ID"""
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر، مثال:\n/set_premium 12345678")
        return
    
    try:
        user_id = int(context.args[0])
        pool = context.bot_data.get('db_conn')
        
        # استخدام الـ Pool بطريقة صحيحة لحقن الـ 10 محاولات في الداتابيز
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users 
                SET search_credits = search_credits + 10 
                WHERE user_id = $1
            """, user_id)
        
        await update.message.reply_text(f"✅ تم منح **10 محاولات بحث إضافية** بنجاح للمستخدم: {user_id}")
        
        # إرسال إشعار فوري للمستخدم في الخاص
        try:
            await context.bot.send_message(
                chat_id=user_id, 
                text="🎁 **مفاجأة!** تم منح حسابك **10 محاولات بحث إضافية** من قبل إدارة المكتبة مجاناً لمواصلة التصفح والتحميل."
            )
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في قاعدة البيانات: {e}")

@admin_only
async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصفير محاولات البحث لمستخدم معين: /rem_premium ID"""
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر.")
        return
    
    try:
        user_id = int(context.args[0])
        pool = context.bot_data.get('db_conn')
        
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET search_credits = 0 WHERE user_id = $1", user_id)
            
        await update.message.reply_text(f"🚫 تم تصفير رصيد محاولات البحث تماماً للمستخدم: {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# ===============================================
# بقية المهام (تتبع، اشتراك، إحصائيات) محدثة بـ Pool Connection
# ===============================================
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id:
        pool = context.bot_data.get('db_conn')
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", update.effective_user.id)
            except: pass

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if REQUIRED_CHANNEL_ID is None: return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL_ID, update.effective_user.id)
        if member.status in ["left", "kicked"]:
            await update.message.reply_text("❌ يجب الاشتراك في القناة أولاً قبل استخدام البوت.")
            return False
        return True
    except: return False

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_conn')
    if pool:
        async with pool.acquire() as conn:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            # جلب إجمالي المستخدمين الذين لديهم رصيد محاولات أكبر من صفر
            active_credited_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE search_credits > 0")
        
        stats_text = (
            "📊 **لوحة تحكم المكتبة الكبرى v2.5**\n"
            "--------------------------------------\n"
            f"📚 الكتب المفهرسة كلياً: **{book_count:,}**\n"
            f"👥 المستخدمين الكلي: **{total_users:,}**\n"
            f"🎁 الحسابات ذات المحاولات النشطة: **{active_credited_users:,}**\n"
            "--------------------------------------\n"
            "🛠 **أوامر الإدارة الحصية:**\n"
            "• لمنح شخص 10 محاولات: `/set_premium ID`\n"
            "• لتصفير محاولات شخص: `/rem_premium ID`\n"
            "• للبث الشامل: `/broadcast نص الرسالة`"
        )
        await update.message.reply_text(stats_text, parse_mode='Markdown')

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    pool = context.bot_data.get('db_conn')
    
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
        
    await update.message.reply_text(f"🚀 جاري بث الرسالة لـ {len(users)} مستخدم...")
    for r in users:
        try: await context.bot.send_message(r['user_id'], msg)
        except: pass
    await update.message.reply_text("✅ تم الانتهاء من إرسال البث لجميع المستخدمين.")

@admin_only
async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REQUIRED_CHANNEL_ID
    if context.args:
        try:
            arg = context.args[0]
            if arg.startswith("@"):
                chat = await context.bot.get_chat(arg)
                REQUIRED_CHANNEL_ID = chat.id
            else: REQUIRED_CHANNEL_ID = int(arg)
            await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري بنجاح: {REQUIRED_CHANNEL_ID}")
        except: await update.message.reply_text("❌ معرف القناة غير صحيح أو البوت ليس مشرفاً بها.")

def register_admin_handlers(application, original_start_handler):
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await check_subscription(update, context):
            await track_user(update, context)
            await original_start_handler(update, context)

    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("set_premium", set_premium))
    application.add_handler(CommandHandler("rem_premium", remove_premium))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("setchannel", set_channel))
    application.add_handler(CommandHandler("start", start_with_tracking))
