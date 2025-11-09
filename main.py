# =================== (الأكواد المستوردة والإعدادات بقيت كما هي) ===================
import os
import asyncpg
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    PicklePersistence, ContextTypes, filters
)

# ... (إعدادات logging و init_db و close_db و handle_pdf تبقى كما هي) ...

# رابط القناة مباشرة للاشتراك الإجباري
CHANNEL_USERNAME = "@iiollr"

# ===============================================
# البحث عن الكتب (تم تعديل send_books_page)
# ===============================================
BOOKS_PER_PAGE = 10

async def search_books_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    # 💡 التحقق من الاشتراك قبل البحث
    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ])
        await update.message.reply_text(
            f"🚫 الاشتراك في القناة {CHANNEL_USERNAME} إلزامي للبحث.\nاضغط على الزر ثم أعد المحاولة.",
            reply_markup=keyboard
        )
        return

    mode = context.user_data.get("mode", "normal")
    query = update.message.text.strip()
    conn = context.bot_data.get('db_conn')

    # ... (باقي منطق جلب الكتب من قاعدة البيانات يبقى كما هو) ...

    if not books:
        await update.message.reply_text(f"❌ لم أجد أي كتب تطابق: {query}")
        return

    context.user_data["search_results"] = books
    context.user_data["current_page"] = 0
    await send_books_page(update, context)

async def send_books_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    text = f"📚 النتائج ({len(books)} كتاب)\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        # 💡 التعديل: استخدام ID الكتاب بدلاً من المفتاح المؤقت
        book_id = b["id"]
        keyboard.append([
            InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"book_id:{book_id}")
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        # استخدام edit_text لتحديث الرسالة عند التنقل بين الصفحات
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# ===============================================
# أزرار القائمة الرئيسية (تم تعديل callback_handler)
# ===============================================
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 بحث عادي", callback_data="search_normal")],
        [InlineKeyboardButton("🤖 البحث بالذكاء الاصطناعي", callback_data="search_ai")],
        [InlineKeyboardButton("💡 اقتراح كتاب", callback_data="suggest_book")],
        [InlineKeyboardButton("📖 البحث بالكلمات المفتاحية", callback_data="search_keywords")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    # استخدام message.reply_text بدلاً من message.edit_text في القائمة الرئيسية
    if update.callback_query:
        await update.callback_query.message.edit_text("👋 أهلاً بك! كيف تريد أن تبحث عن الكتاب؟", reply_markup=reply_markup)
    else:
        await update.message.reply_text("👋 أهلاً بك! كيف تريد أن تبحث عن الكتاب؟", reply_markup=reply_markup)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = context.bot_data.get('db_conn')

    # 1. معالجة أوضاع البحث (تم تعديل edit_text لرسائل التوجيه)
    if data == "search_normal":
        context.user_data["mode"] = "normal"
        await query.message.edit_text("✏️ وضع البحث العادي: اكتب اسم الكتاب أو المؤلف للبحث:")
    elif data == "search_ai":
        context.user_data["mode"] = "ai"
        await query.message.edit_text("🤖 وضع الذكاء الاصطناعي: اكتب اسم الكتاب ليقوم بجلب الوصف:")
    elif data == "suggest_book":
        context.user_data["mode"] = "suggest"
        await query.message.edit_text("💡 وضع الاقتراح: اكتب المجال الذي تريد اقتراح كتب فيه:")
    elif data == "search_keywords":
        context.user_data["mode"] = "keywords"
        await query.message.edit_text("📖 وضع الكلمات المفتاحية: اكتب كلمات مفتاحية عن الكتاب أو أحداثه:")

    # 2. معالجة زر طلب الملف (تم التعديل ليجلب من DB)
    elif data.startswith("book_id:"):
        if not conn:
            await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
            return

        book_id = int(data.split(":")[1])
        try:
            result = await conn.fetchrow("SELECT file_id FROM books WHERE id = $1", book_id)
            file_id = result['file_id'] if result else None

            if file_id:
                caption = "📥 تم التنزيل بواسطة @Boooksfree1bot"
                await query.message.reply_document(document=file_id, caption=caption)
            else:
                await query.message.reply_text("❌ الملف غير متوفر حالياً.")
        except Exception as e:
            logger.error(f"❌ Error retrieving book file: {e}")
            await query.message.reply_text("❌ حدث خطأ أثناء جلب الملف.")

    # 3. معالجة أزرار التنقل (تم إزالة حذف الرسالة)
    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_books_page(update, context) # سيقوم edit_text بتحديث الرسالة
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_books_page(update, context) # سيقوم edit_text بتحديث الرسالة

# ===============================================
# الاشتراك الإجباري (تم تحسين التحقق)
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        # التحقق من أن الحالة هي عضو، إداري، أو منشئ (لضمان أنه ليس غادر/مطرود)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        # إذا فشل الجلب (البوت ليس إدارياً)، نفترض أنه غير مشترك
        logger.error(f"❌ Subscription check failed (Check Bot Admin Status): {e}")
        return False

# ===============================================
# أوامر البوت (تم تطبيق الاشتراك الإجباري على start)
# ===============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update.effective_user.id, context.bot):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ])
        await update.message.reply_text(
            f"🚫 الاشتراك في القناة {CHANNEL_USERNAME} إلزامي.\nاضغط على الزر ثم أعد إرسال الأمر.",
            reply_markup=keyboard
        )
        return
    await main_menu(update, context)

# ===============================================
# تشغيل البوت (تم تصحيح CallbackQueryHandler)
# ===============================================
def run_bot():
    # ... (الجزء العلوي من الدالة) ...

    app = (
        Application.builder()
        # ...
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books_handler))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    # 💡 التعديل: إزالة النمط المعقد
    app.add_handler(CallbackQueryHandler(callback_handler))

    # ... (باقي كود run_bot) ...
