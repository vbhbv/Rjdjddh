from telegram import Update, Bot
from telegram.ext import ContextTypes, CommandHandler, ConversationHandler, MessageHandler, filters
from functools import wraps

# ==========================
# Fixed Admin ID
# ==========================
ADMIN_USER_ID = 6166700051

BAN_USER = 1

# ==========================
# Decorator للتحقق من المشرف
# ==========================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_USER_ID:
            await update.message.reply_text("❌ أمر خاص بالمشرفين فقط.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ==========================
# إحصائيات
# ==========================
@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متاحة حالياً.")
        return
    book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
    user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
    text = (
        f"📊 **لوحة إحصائيات المشرف**\n"
        f"--------------------------------------\n"
        f"📚 عدد الكتب المفهرسة: **{book_count}**\n"
        f"👥 عدد المستخدمين: **{user_count}**\n"
        f"--------------------------------------\n"
        "لإرسال رسالة: /broadcast رسالتك هنا\n"
        "لحظر مستخدم: /ban_user"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# ==========================
# Broadcast
# ==========================
@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الرجاء إرسال رسالة البث بعد الأمر.")
        return
    message = " ".join(context.args)
    conn = context.bot_data.get('db_conn')
    if not conn:
        await update.message.reply_text("❌ فشل البث: البوت غير متصل بقاعدة البيانات.")
        return
    user_ids = [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users")]
    sent, failed = 0, 0
    bot: Bot = context.bot
    await update.message.reply_text(f"بدء عملية البث إلى {len(user_ids)} مستخدم...")
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message, parse_mode='Markdown')
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ انتهى البث.\nتم الإرسال بنجاح: {sent}\nفشل الإرسال: {failed}")

# ==========================
# Ban User Conversation
# ==========================
@admin_only
async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أرسل ID المستخدم لحظره (رقمياً).")
    return BAN_USER

@admin_only
async def ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
        await update.message.reply_text(f"✅ تم حظر المستخدم ID: {user_id}.")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ ID المستخدم يجب أن يكون رقماً صحيحاً. أرسل /cancel للإلغاء.")
        return BAN_USER

async def ban_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء عملية الحظر.")
    return ConversationHandler.END

# ==========================
# تسجيل Handlers
# ==========================
def register_admin_handlers(app, original_start_handler):
    # تعديل /start لتسجيل المستخدم
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                await conn.execute(
                    "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                    update.effective_user.id
                )
            except Exception as e:
                print(f"Error tracking user: {e}")
        await original_start_handler(update, context)

    app.add_handler(CommandHandler("start", start_with_tracking))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))

    ban_conv = ConversationHandler(
        entry_points=[CommandHandler("ban_user", ban_user_start)],
        states={BAN_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_execute)]},
        fallbacks=[CommandHandler("cancel", ban_user_cancel)]
    )
    app.add_handler(ban_conv)

    print("✅ تم تسجيل معالجات المشرفين بنجاح.")
