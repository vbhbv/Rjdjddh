import os
from telegram import Update, Bot
from telegram.ext import (
    ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
)
from functools import wraps

# ===============================================
#       إعدادات المشرفين
# ===============================================

try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

BAN_USER = 1

# ===============================================
#       دوال مساعدة
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
    if update.effective_user and update.effective_user.id:
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                await conn.execute(
                    "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", update.effective_user.id
                )
            except Exception as e:
                print(f"Error tracking user {update.effective_user.id}: {e}")

# ===============================================
#       أوامر المشرفين
# ===============================================

@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get('db_conn')
    book_count = 0
    user_count = 0
    if conn:
        try:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        except Exception as e:
            print(f"Error fetching stats: {e}")

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

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
#       الحظر
# ===============================================

@admin_only
async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أرسل ID المستخدم لحظره الآن (رقمياً).")
    return BAN_USER

@admin_only
async def ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
        # ضع هنا منطق الحظر الفعلي إذا لزم
        await update.message.reply_text(f"✅ تم حظر المستخدم ID: {user_id}")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون رقم صحيح. حاول مرة أخرى أو /cancel")
        return BAN_USER

async def ban_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء عملية الحظر.")
    return ConversationHandler.END

# ===============================================
#       التسجيل الرئيسي
# ===============================================

def register_admin_handlers(application, original_start_handler):
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await track_user(update, context)
        await original_start_handler(update, context)

    application.add_handler(CommandHandler("start", start_with_tracking))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))

    ban_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('ban_user', ban_user_start)],
        states={BAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_execute)]},
        fallbacks=[CommandHandler('cancel', ban_user_cancel)]
    )
    application.add_handler(ban_conv_handler)
    print("✅ لوحة التحكم والمشرفين جاهزة للعمل.")
