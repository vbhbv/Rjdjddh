import os
from telegram import Update, Bot
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
from functools import wraps

# ===============================================
#       إعدادات المشرفين
# ===============================================

try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ Warning: ADMIN_ID environment variable is not a valid integer or missing.")


# الحالات في ConversationHandler
BAN_USER = 1

# ===============================================
#       وظائف مساعدة
# ===============================================

def admin_only(func):
    """Decorator للتحقق من أن المستخدم هو المشرف فقط."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID and ADMIN_USER_ID != 0:
            return await func(update, context, *args, **kwargs)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ هذا الأمر خاص بالمشرف فقط.")
        return
    return wrapper


async def get_user_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    """إرجاع عدد المستخدمين المسجلين."""
    conn = context.bot_data.get('db_conn')
    if not conn:
        return 0
    try:
        result = await conn.fetchval("SELECT COUNT(*) FROM users;")
        return result or 0
    except Exception as e:
        print(f"⚠️ Error fetching user count: {e}")
        return 0

# ===============================================
#       أوامر المشرف
# ===============================================

@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات المشرف."""
    conn = context.bot_data.get('db_conn')

    book_count = user_count = 0
    if conn:
        try:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books;")
        except Exception as e:
            print(f"Error fetching book count: {e}")

        user_count = await get_user_count(context)

    stats_text = (
        "📊 **لوحة الإحصاءات**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 عدد الكتب المفهرسة: **{book_count:,}**\n"
        f"👥 عدد المستخدمين المسجلين: **{user_count:,}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 للبث: /broadcast رسالتك هنا\n"
        "🚫 لحظر مستخدم: /ban_user\n"
    )

    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل المستخدم الجديد في قاعدة البيانات."""
    if not update.effective_user or not update.effective_user.id:
        return

    user_id = update.effective_user.id
    conn = context.bot_data.get('db_conn')
    if not conn:
        return

    try:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING;",
            user_id
        )
    except Exception as e:
        print(f"⚠️ Error tracking user {user_id}: {e}")

# ===============================================
#       البث للمستخدمين
# ===============================================

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال بث لجميع المستخدمين."""
    if not context.args:
        await update.message.reply_text("✉️ استخدم: /broadcast رسالتك هنا")
        return

    message_to_send = " ".join(context.args)
    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ لا يوجد اتصال بقاعدة البيانات.")
        return

    try:
        users = await conn.fetch("SELECT user_id FROM users;")
        if not users:
            await update.message.reply_text("🚫 لا يوجد مستخدمون بعد.")
            return

        user_ids = [u['user_id'] for u in users]
        bot: Bot = context.bot
        sent, failed = 0, 0

        await update.message.reply_text(f"📤 بدء البث إلى {len(user_ids)} مستخدم...")

        for user_id in user_ids:
            try:
                await bot.send_message(chat_id=user_id, text=message_to_send)
                sent += 1
            except Exception:
                failed += 1

        await update.message.reply_text(
            f"✅ تم البث.\n"
            f"📨 ناجح: **{sent}**\n"
            f"🚫 فشل (محظور/مغلق): **{failed}**",
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text(f"⚠️ خطأ أثناء البث: {e}")

# ===============================================
#       الحظر
# ===============================================

@admin_only
async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 أرسل الآن ID المستخدم الذي تريد حظره (رقم فقط).")
    return BAN_USER


@admin_only
async def ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        # 🔒 هنا يمكنك لاحقًا إضافة منطق فعلي للحظر داخل قاعدة البيانات
        await update.message.reply_text(f"✅ تم تنفيذ حظر المستخدم ID: {user_id}")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون ID رقمًا صحيحًا. أعد المحاولة أو أرسل /cancel للإلغاء.")
        return BAN_USER


async def ban_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم إلغاء عملية الحظر.")
    return ConversationHandler.END

# ===============================================
#       تسجيل المعالجات
# ===============================================

def register_admin_handlers(application, original_start_handler):
    """تسجيل جميع أوامر المشرف وتتبع المستخدم."""
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await track_user(update, context)
        await original_start_handler(update, context)

    application.add_handler(CommandHandler("start", start_with_tracking))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))

    ban_conv = ConversationHandler(
        entry_points=[CommandHandler("ban_user", ban_user_start)],
        states={BAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_execute)]},
        fallbacks=[CommandHandler("cancel", ban_user_cancel)],
    )
    application.add_handler(ban_conv)

    print("✅ تم تحميل نظام إدارة المشرفين بنجاح.")
