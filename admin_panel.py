import os
from telegram import Update, Bot
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, filters
)
from functools import wraps

# ===============================================
# إعدادات المشرفين
# ===============================================
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))  # معرف المشرف
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
# أوامر التفعيل (Premium) - سهلة جداً
# ===============================================
@admin_only
async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل البريموم لمستخدم: /set_premium ID"""
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر، مثال:\n/set_premium 12345678")
        return
    
    try:
        user_id = int(context.args[0])
        pool = context.bot_data.get('db_conn')
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE users 
                SET is_premium = TRUE, premium_expiry = NOW() + INTERVAL '30 days' 
                WHERE user_id = $1
            """, user_id)
        
        await update.message.reply_text(f"✅ تم تفعيل البريموم بنجاح للمستخدم: {user_id}")
        # إرسال رسالة للمستخدم
        try:
            await context.bot.send_message(user_id, "🌟 مبروك! تم تفعيل العضوية المميزة لحسابك بنجاح لمدة شهر.")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

@admin_only
async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء البريموم لمستخدم: /rem_premium ID"""
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر.")
        return
    
    try:
        user_id = int(context.args[0])
        pool = context.bot_data.get('db_conn')
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_premium = FALSE WHERE user_id = $1", user_id)
        await update.message.reply_text(f"🚫 تم إلغاء البريموم للمستخدم: {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# ===============================================
# بقية المهام (تتبع، اشتراك، إحصائيات)
# ===============================================
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id:
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
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
    conn = context.bot_data.get('db_conn')
    if conn:
        book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        premium_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_premium = TRUE")
        
        stats_text = (
            "📊 **لوحة تحكم المكتبة v2.0**\n"
            "--------------------------------------\n"
            f"📚 الكتب المفهرسة: **{book_count:,}**\n"
            f"👥 المستخدمين الكلي: **{total_users:,}**\n"
            f"⭐ الأعضاء المميزين: **{premium_users:,}**\n"
            "--------------------------------------\n"
            "🛠 **أوامر التفعيل السريع:**\n"
            "• لتفعيل شخص: `/set_premium ID`\n"
            "• لإلغاء تفعيل: `/rem_premium ID`\n"
            "• للبث: `/broadcast نص الرسالة`"
        )
        await update.message.reply_text(stats_text, parse_mode='Markdown')

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    msg = " ".join(context.args)
    conn = context.bot_data.get('db_conn')
    users = await conn.fetch("SELECT user_id FROM users")
    await update.message.reply_text(f"🚀 جاري الإرسال لـ {len(users)} مستخدم...")
    for r in users:
        try: await context.bot.send_message(r['user_id'], msg)
        except: pass
    await update.message.reply_text("✅ تم الانتهاء من البث.")

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
            await update.message.reply_text(f"✅ تم تعيين القناة: {REQUIRED_CHANNEL_ID}")
        except: await update.message.reply_text("❌ معرف غير صحيح.")

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
