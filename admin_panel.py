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
# أوامر التفعيل ومنح البريميوم الزمني
# ===============================================
@admin_only
async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    تفعيل البريميوم الزمني لمستخدم:
    /set_premium ID month   -> بريميوم شهري (30 يوم)
    /set_premium ID half    -> بريميوم نصف سنوي (180 يوم)
    /set_premium ID year    -> بريميوم سنوي (365 يوم)
    """
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ **طريقة الاستخدام الصحيحة للأمر:**\n\n"
            "• شهري (30 يوم):\n`/set_premium ID month`\n"
            "• نصف سنوي (180 يوم):\n`/set_premium ID half`\n"
            "• سنوي (365 يوم):\n`/set_premium ID year`"
        )
        return
    
    try:
        user_id = int(context.args[0])
        duration_type = context.args[1].lower()
        
        # تم إصلاح تمرير الـ Interval برمجياً بشكل آمن متوافق مع محرك PostgreSQL و asyncpg
        if duration_type == "month":
            days_to_add = 30
            duration_text = "شهر واحد (30 يوم)"
        elif duration_type == "half":
            days_to_add = 180
            duration_text = "نصف سنة (180 يوم)"
        elif duration_type == "year":
            days_to_add = 365
            duration_text = "سنة كاملة (365 يوم)"
        else:
            await update.message.reply_text("❌ خيار غير صحيح! اختر إما: `month` أو `half` أو `year`.")
            return

        pool = context.bot_data.get('db_conn')
        
        async with pool.acquire() as conn:
            # هنا الإصلاح الحقيقي: نستخدم الدالة البرمجية لقاعدة البيانات لجمع الأيام بأمان
            await conn.execute("""
                UPDATE users 
                SET is_premium = TRUE, 
                    premium_expiry = NOW() + ($2 || ' days')::INTERVAL
                WHERE user_id = $1
            """, user_id, str(days_to_add))
        
        await update.message.reply_text(f"✅ تم تفعيل البريميوم بنجاح للمستخدم: {user_id}\n⏱ المدة الممنوحة: **{duration_text}**")
        
        # إرسال رسالة مباشرة للمستخدم لتنبيهه بالتفعيل والمدة الممنوحة له
        try:
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"🌟 **مبروك! تم تفعيل العضوية المميزة (Premium) لحسابك بنجاح.**\n\n⏳ المدة: **{duration_text}**\n🚀 يمكنك الآن الاستمتاع ببحث وتحميل غير محدود دون أي قيود!"
            )
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في قاعدة البيانات: {e}")

@admin_only
async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء البريموم الزمني تماماً لمستخدم معين: /rem_premium ID"""
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر.")
        return
    
    try:
        user_id = int(context.args[0])
        pool = context.bot_data.get('db_conn')
        
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users 
                SET is_premium = FALSE, premium_expiry = NULL 
                WHERE user_id = $1
            """, user_id)
            
        await update.message.reply_text(f"🚫 تم إلغاء البريميوم الزمني تماماً للمستخدم: {user_id}")
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
            # حساب الأعضاء البريميوم الفعليين الذين لم تنتهِ صلاحيتهم بعد
            premium_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_premium = TRUE AND (premium_expiry IS NULL OR premium_expiry > NOW())")
        
        stats_text = (
            "📊 **لوحة تحكم المكتبة الكبرى v3.0**\n"
            "--------------------------------------\n"
            f"📚 الكتب المفهرسة كلياً: **{book_count:,}**\n"
            f"👥 المستخدمين الكلي: **{total_users:,}**\n"
            f"⭐ الأعضاء المميزين (الزمني): **{premium_users:,}**\n"
            "--------------------------------------\n"
            "🛠 **أوامر الإدارة والتفعيل الزمني:**\n"
            "• شهري: `/set_premium ID month`\n"
            "• نصف سنوي: `/set_premium ID half`\n"
            "• سنوي: `/set_premium ID year`\n"
            "• لإلغاء البريميوم: `/rem_premium ID`\n"
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
