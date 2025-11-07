import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters, PicklePersistence
)
from functools import wraps

# ===============================================
#       إعدادات المشرفين
# ===============================================
ADMIN_USER_ID = 6166700051
BAN_USER = 1

# ===============================================
#       دوال مساعدة
# ===============================================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID:
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
                    "INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING",
                    update.effective_user.id
                )
            except Exception as e:
                print(f"Error tracking user {update.effective_user.id}: {e}")

# ===============================================
#       إدارة قاعدة البيانات وفهرسة الكتب
# ===============================================
async def init_db(app_context: ContextTypes):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing. Cannot connect to DB.")
            return

        conn = await asyncpg.connect(db_url)

        # إنشاء الإضافات والجداول والفهرس
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        await conn.execute("CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS arabic_simple (PARSER = default);")
        await conn.execute("ALTER TEXT SEARCH CONFIGURATION arabic_simple ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part WITH unaccent, simple;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,  
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                tsv_content tsvector
            );
        """)
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, joined_at TIMESTAMP DEFAULT NOW());")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);")
        await conn.execute("DROP TRIGGER IF EXISTS tsv_update_trigger ON books;")
        await conn.execute("DROP FUNCTION IF EXISTS update_books_tsv();")
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        app_context.bot_data['db_conn'] = conn
        print("✅ Database connection and FTS setup complete.")
    except Exception as e:
        print(f"❌ Database connection/setup error: {e}")

async def close_db(app: Application):
    conn = app.bot_data.get('db_conn')
    if conn:
        await conn.close()
        print("✅ Database connection closed.")

# --- PDF indexing ---
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        if conn:
            try:
                tsv_content = await conn.fetchval("SELECT to_tsvector('arabic_simple', $1);", document.file_name)
                await conn.execute(
                    "INSERT INTO books(file_id, file_name, tsv_content) VALUES($1,$2,$3) "
                    "ON CONFLICT (file_id) DO UPDATE SET file_name=EXCLUDED.file_name, tsv_content=EXCLUDED.tsv_content",
                    document.file_id, document.file_name, tsv_content
                )
                print(f"Book indexed: {document.file_name}")
            except Exception as e:
                print(f"❌ Error indexing book: {e}")

# ===============================================
#       البحث عن الكتب
# ===============================================
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return

    search_term = " ".join(context.args).strip()
    conn = context.bot_data.get('db_conn')
    if conn:
        query_text = search_term.replace(' ', ' & ')
        results = await conn.fetch(
            "SELECT file_id, file_name FROM books WHERE tsv_content @@ to_tsquery('arabic_simple', $1) "
            "ORDER BY file_name ASC LIMIT 10", query_text
        )

        if results:
            if len(results) == 1:
                try:
                    await update.message.reply_document(
                        document=results[0]['file_id'],
                        caption=f"✅ تم العثور على الكتاب: **{results[0]['file_name']}**"
                    )
                except Exception:
                    await update.message.reply_text("❌ لم أتمكن من إرسال الملف.")
            else:
                keyboard = [
                    [InlineKeyboardButton(f"🔗 {r['file_name']}", callback_data=f"file:{r['file_id']}")] 
                    for r in results
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"📚 تم العثور على {len(results)} كتاب يطابق بحثك '{search_term}':",
                    reply_markup=reply_markup
                )
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على كتاب يطابق '{search_term}'.")
    else:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات.")

# --- معالج الضغط على أزرار الكتب ---
async def book_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        data = query.data
        if data.startswith("file:"):
            file_id = data[5:]
            conn = context.bot_data.get('db_conn')
            if conn:
                try:
                    book = await conn.fetchrow("SELECT file_name, file_id FROM books WHERE file_id LIKE $1 LIMIT 1", f"{file_id}%")
                    if book:
                        await query.message.reply_document(
                            document=book['file_id'],
                            caption=f"✅ تم العثور على الكتاب: **{book['file_name']}**"
                        )
                    else:
                        await query.message.reply_text("❌ لم يتم العثور على الكتاب.")
                except Exception as e:
                    await query.message.reply_text(f"❌ خطأ أثناء إرسال الكتاب: {e}")

# ===============================================
#       أمر /start
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة البوت! 📚\n"
        "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب"
    )

# ===============================================
#       أوامر المشرفين
# ===============================================
@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get('db_conn')
    book_count = user_count = 0
    if conn:
        try:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        except Exception as e:
            print(f"Error fetching stats: {e}")

    stats_text = (
        "📊 **لوحة إحصائيات المشرف**\n"
        f"📚 عدد الكتب المفهرسة: **{book_count}**\n"
        f"👥 عدد المستخدمين: **{user_count}**"
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
    sent_count = failed_count = 0
    bot: Bot = context.bot
    await update.message.reply_text(f"بدء البث إلى {len(user_records)} مستخدم...")
    for r in user_records:
        try:
            await bot.send_message(r['user_id'], message_to_send)
            sent_count += 1
        except Exception:
            failed_count += 1
    await update.message.reply_text(f"✅ انتهى البث. تم الإرسال: {sent_count}, فشل: {failed_count}")

# الحظر
@admin_only
async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أرسل ID المستخدم لحظره الآن (رقمياً).")
    return BAN_USER

@admin_only
async def ban_user_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
        await update.message.reply_text(f"✅ تم حظر المستخدم ID: {user_id}")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون رقم صحيح. حاول مرة أخرى أو /cancel")
        return BAN_USER

async def ban_user_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء عملية الحظر.")
    return ConversationHandler.END

# ===============================================
#       تسجيل المعالجات
# ===============================================
def register_admin_handlers(application):
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await track_user(update, context)
        await start(update, context)

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

# ===============================================
#       تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    port = int(os.environ.get('PORT', 8080))
    base_url = os.environ.get('WEB_HOST')
    if not token:
        print("🚨 BOT_TOKEN مفقود.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(book_button_handler))

    register_admin_handlers(app)

    if base_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"https://{base_url}/{token}",
            secret_token=os.getenv("WEBHOOK_SECRET")
        )
    else:
        print("⚠️ WEB_HOST غير محدد، سيتم استخدام Polling.")
        app.run_polling(poll_interval=1.0)


if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"Fatal error: {e}")
