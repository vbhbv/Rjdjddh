# ================== search.py ==================
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
import math

PAGE_SIZE = 10  # عدد الكتب في كل صفحة


# 🔍 دالة البحث (تتصل مباشرة بقاعدة البيانات الموجودة في main)
async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بحث الكتب من قاعدة البيانات مع عرض صفحات."""
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("📚 أرسل اسم الكتاب بعد الأمر مثل:\n`/search نهج البلاغة`", parse_mode="Markdown")
        return

    query = " ".join(context.args).strip()
    conn = context.bot_data.get("db_conn")

    if not conn:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات.")
        return

    # جلب جميع النتائج بدون حد (الصفحات تتولى التقسيم)
    results = await conn.fetch(
        "SELECT file_id, file_name FROM books WHERE file_name ILIKE '%' || $1 || '%' ORDER BY uploaded_at DESC;",
        query
    )

    if not results:
        await update.message.reply_text(f"❌ لم يتم العثور على أي كتاب بعنوان '{query}'.")
        return

    # حفظ البيانات مؤقتًا
    context.user_data["search_results"] = results
    context.user_data["query"] = query
    await send_page(update, context, 1)


# 📖 عرض صفحة من النتائج
async def send_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    results = context.user_data.get("search_results", [])
    query = context.user_data.get("query", "")
    if not results:
        await update.message.reply_text("⚠️ لا توجد نتائج محفوظة.")
        return

    total_pages = math.ceil(len(results) / PAGE_SIZE)
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_results = results[start:end]

    text = f"🔍 نتائج البحث عن: *{query}*\n\n"
    keyboard = []

    for i, r in enumerate(page_results, start=start + 1):
        file_id = r["file_id"]
        file_name = r["file_name"]
        keyboard.append([InlineKeyboardButton(f"{i}. {file_name}", callback_data=f"book:{file_id}")])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"page:{page-1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"page:{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    markup = InlineKeyboardMarkup(keyboard)
    text += f"📄 الصفحة {page}/{total_pages}"

    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text=text, reply_markup=markup, parse_mode="Markdown")


# 📘 عند الضغط على كتاب
async def send_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    file_id = query.data.split(":")[1]
    await query.answer()
    try:
        await query.message.reply_document(document=file_id)
    except Exception:
        await query.message.reply_text("⚠️ تعذر إرسال الملف. ربما تم حذفه أو أصبح غير صالح.")


# ⏩ التنقل بين الصفحات
async def change_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    page = int(query.data.split(":")[1])
    await send_page(update, context, page)
    await query.answer()


# 🧩 تسجيل الأوامر في التطبيق
def register_search_handlers(app):
    app.add_handler(CommandHandler("search", search_books))
    app.add_handler(CallbackQueryHandler(change_page, pattern=r"^page:"))
    app.add_handler(CallbackQueryHandler(send_book, pattern=r"^book:"))
