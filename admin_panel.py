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

async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل المستخدمين في قاعدة البيانات (لإحصائيات البث لاحقاً)."""
    if update.effective_user and update.effective_user.id:
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                await conn.execute(
                    "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", update.effective_user.id
                )
            except Exception as e:
                print(f"Error tracking user {update.effective_user.id}: {e}")

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحقق من اشتراك المستخدم بالقناة الإلزامية."""
    if REQUIRED_CHANNEL_ID is None:
        return True  # إذا لم يُحدد معرف القناة، تخطي الاشتراك
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL_ID, update.effective_user.id)
        if member.status in ["left", "kicked"]:
            await update.message.reply_text(
                "❌ يجب الاشتراك في القناة أولاً قبل استخدام البوت."
            )
            return False
        return True
    except Exception:
        await update.message.reply_text("❌ حدث خطأ أثناء التحقق من الاشتراك.")
        return False

# ===============================================
# دالة إحصائيات المستخدمين اليومية والأسبوعية
# ===============================================
async def get_user_stats(conn):
    """إرجاع عدد المستخدمين الكلي واليومي والأسبوعي"""
    try:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        daily_users = await conn.fetchval("""
            SELECT COUNT(*) FROM users
            WHERE joined_at >= CURRENT_DATE
        """)
        weekly_users = await conn.fetchval("""
            SELECT COUNT(*) FROM users
            WHERE joined_at >= CURRENT_DATE - INTERVAL '7 days'
        """)
        return total_users, daily_users, weekly_users
    except Exception as e:
        print(f"Error fetching user stats: {e}")
        return 0, 0, 0

# ===============================================
# أوامر المشرفين
# ===============================================
@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم الخاصة بالمشرف."""
    conn = context.bot_data.get('db_conn')
    book_count = 0
    total_users = daily_users = weekly_users = 0

    if conn:
        try:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            total_users, daily_users, weekly_users = await get_user_stats(conn)
        except Exception as e:
            print(f"Error fetching stats: {e}")

    stats_text = (
        "📊 **لوحة تحكم المشرف**\n"
        "--------------------------------------\n"
        f"📚 عدد الكتب المفهرسة: **{book_count:,}**\n"
        f"👥 عدد المستخدمين الكلي: **{total_users:,}**\n"
        f"📅 مستخدمو اليوم: **{daily_users:,}**\n"
        f"🗓️ مستخدمو الأسبوع: **{weekly_users:,}**\n"
        "--------------------------------------\n"
        "لإرسال رسالة للمستخدمين: /broadcast رسالتك هنا\n"
        "لتحديد القناة للاشتراك الإجباري: /setchannel\n"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بث رسالة لجميع المستخدمين."""
    if not context.args:
        await update.message.reply_text("الرجاء إرسال رسالة بعد /broadcast")
        return

    message_to_send = " ".join(context.args)
    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات.")
        return

    user_records = await conn.fetch("SELECT user_id FROM users")
    sent_count = 0
    failed_count = 0
    bot: Bot = context.bot
    await update.message.reply_text(f"بدء البث إلى {len(user_records)} مستخدم...")
    for r in user_records:
        try:
            await bot.send_message(r['user_id'], message_to_send)
            sent_count += 1
        except Exception:
            failed_count += 1

    await update.message.reply_text(f"✅ انتهى البث.\nتم الإرسال بنجاح: {sent_count}\nفشل الإرسال: {failed_count}")

# ===============================================
# تحديد القناة للاشتراك الإجباري
# ===============================================
@admin_only
async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديد القناة للاشتراك الإجباري عن طريق الرد/معرف القناة."""
    global REQUIRED_CHANNEL_ID
    if not context.args:
        await update.message.reply_text("الرجاء إرسال معرف القناة الرقمي أو الرابط @channel_username بعد /setchannel")
        return
    channel_arg = context.args[0]
    try:
        # إذا كان @username
        if channel_arg.startswith("@"):
            chat = await context.bot.get_chat(channel_arg)
            REQUIRED_CHANNEL_ID = chat.id
        else:
            REQUIRED_CHANNEL_ID = int(channel_arg)
        await update.message.reply_text(f"✅ تم تعيين القناة للاشتراك الإجباري: {REQUIRED_CHANNEL_ID}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في تحديد القناة: {e}")

# ===============================================
# التسجيل الرئيسي
# ===============================================
def register_admin_handlers(application, original_start_handler):
    """تسجيل جميع أوامر المشرفين مع الاشتراك الإجباري وتتبع المستخدمين."""
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        subscribed = await check_subscription(update, context)
        if not subscribed:
            return
        await track_user(update, context)
        await original_start_handler(update, context)

    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(CommandHandler("setchannel", set_channel))
    application.add_handler(CommandHandler("start", start_with_tracking))

    print("✅ لوحة التحكم والمشرفين جاهزة للعمل.")
