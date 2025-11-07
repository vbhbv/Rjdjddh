import os
from telegram import Update, Bot
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
from functools import wraps

# ===============================================
#       إعدادات المشرفين
# ===============================================

# 🚨 هام: يجب استبدال هذا بمعرف مشرفك (user ID) أو قراءته من متغير بيئة
# تأكد من تعيين متغير البيئة ADMIN_ID بالقيمة الصحيحة
try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_ID", "0")) # Default to 0 if not found
except ValueError:
    ADMIN_USER_ID = 0 
    print("Warning: ADMIN_ID environment variable is not a valid integer.")


# حالات محادثة الحظر
BAN_USER = 1

# ===============================================
#       وظائف مساعدة للمشرفين
# ===============================================

def admin_only(func):
    """Decorator للتحقق من أن المستخدم هو المشرف."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # We check against ADMIN_USER_ID which is loaded from environment
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID and ADMIN_USER_ID != 0:
            return await func(update, context, *args, **kwargs)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ أمر خاص بالمشرفين فقط.")
        return
    return wrapper

async def get_user_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    """الحصول على عدد المستخدمين المسجلين في جدول users."""
    conn = context.bot_data.get('db_conn')
    if conn:
        try:
            result = await conn.fetchval("SELECT COUNT(*) FROM users")
            return result
        except Exception as e:
            print(f"Error fetching user count: {e}")
            return 0
    return 0

# ===============================================
#       معالجات أوامر المشرفين
# ===============================================

@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض إحصائيات البوت للمشرف."""
    
    # 1. الحصول على عدد الكتب
    conn = context.bot_data.get('db_conn')
    book_count = 0
    if conn:
        try:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
        except Exception as e:
            print(f"Error fetching book count: {e}")

    # 2. الحصول على عدد المستخدمين (المفترض أن يتم تسجيلهم في مكان ما)
    user_count = await get_user_count(context)
    
    stats_text = (
        "📊 **لوحة إحصائيات المشرف**\n"
        "--------------------------------------\n"
        f"📚 عدد الكتب المفهرسة: **{book_count:,}**\n"
        f"👥 عدد المستخدمين الكلي: **{user_count:,}**\n"
        "--------------------------------------\n"
        "لإرسال رسالة: /broadcast رسالتك هنا\n"
        "لحظر مستخدم: /ban_user\n"
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# وظيفة تسجيل المستخدم (يجب أن تستدعى من معالج /start)
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل المستخدم الجديد في قاعدة البيانات."""
    if update.effective_user and update.effective_user.id:
        user_id = update.effective_user.id
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                # إضافة المستخدم في حالة عدم وجوده (ON CONFLICT DO NOTHING)
                await conn.execute(
                    "INSERT INTO users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", 
                    user_id
                )
            except Exception as e:
                print(f"Error tracking user {user_id}: {e}")

# ===============================================
#       وظائف البث (Broadcast)
# ===============================================

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يرسل رسالة بث لجميع المستخدمين."""
    if not context.args:
        await update.message.reply_text("الرجاء إرسال رسالة البث بعد الأمر. مثال: /broadcast رسالة هامة.")
        return
    
    message_to_send = " ".join(context.args)
    
    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ فشل البث: البوت غير متصل بقاعدة البيانات.")
        return

    try:
        # 1. جلب جميع المستخدمين
        user_records = await conn.fetch("SELECT user_id FROM users")
        user_ids = [r['user_id'] for r in user_records]
        
        sent_count = 0
        failed_count = 0
        bot: Bot = context.bot
        
        # 2. إرسال الرسالة
        await update.message.reply_text(f"بدء عملية البث إلى {len(user_ids)} مستخدم...")

        for user_id in user_ids:
            try:
                await bot.send_message(chat_id=user_id, text=message_to_send, parse_mode='Markdown')
                sent_count += 1
            except Exception:
                failed_count += 1
                # لا نطبع كل فشل لتجنب إغراق الـ Logs

        await update.message.reply_text(
            f"✅ انتهى البث.\n"
            f"تم الإرسال بنجاح: **{sent_count}**\n"
            f"فشل الإرسال (حظر البوت): **{failed_count}**",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ غير متوقع أثناء البث: {e}")


# ===============================================
#       وظائف الحظر (Ban)
# ===============================================

@admin_only
async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ محادثة للحصول على ID المستخدم لحظره."""
    await update.message.reply_text("أرسل الآن ID المستخدم الذي تريد حظره (رقمياً).")
    return BAN_USER

@admin_only
async def ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ عملية حظر المستخدم."""
    user_id_to_ban = update.message.text
    
    try:
        user_id = int(user_id_to_ban)
        
        # تنفيذ الحظر - يجب إضافة منطق الحظر الفعلي هنا
        
        await update.message.reply_text(f"✅ تم تنفيذ الإجراء لحظر المستخدم ID: {user_id}.")
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ ID المستخدم يجب أن يكون رقماً صحيحاً. حاول مرة أخرى أو أرسل /cancel للإلغاء.")
        return BAN_USER
    
async def ban_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء عملية الحظر."""
    await update.message.reply_text("تم إلغاء عملية الحظر.")
    return ConversationHandler.END

# ===============================================
#       دالة التسجيل الرئيسية
# ===============================================

def register_admin_handlers(application, original_start_handler):
    """تسجيل جميع معالجات المشرفين والدوال المساعدة."""
    
    # دمج وظيفة تتبع المستخدم مع دالة /start الأصلية
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await track_user(update, context) # تتبع وتسجيل المستخدم
        await original_start_handler(update, context) # تنفيذ وظيفة /start الأصلية
        
    application.add_handler(CommandHandler("start", start_with_tracking))
    
    # معالجات الأوامر المباشرة للمشرفين
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    
    # معالج المحادثة لحظر المستخدم
    ban_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('ban_user', ban_user_start)],
        states={
            BAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_execute)],
        },
        fallbacks=[CommandHandler('cancel', ban_user_cancel)]
    )
    application.add_handler(ban_conv_handler)
    
    print("✅ تم تسجيل معالجات المشرفين بنجاح.")
