import os
import openai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# ===============================================
# إعداد مفتاح OpenAI
# ===============================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# ===============================================
# البحث عن الكتب بالذكاء الاصطناعي
# ===============================================
async def ai_book_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if not user_input:
        await update.message.reply_text("❌ الرجاء كتابة وصف أو كلمات مفتاحية للبحث.")
        return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    # طلب من الذكاء الاصطناعي اختيار أفضل 5 كتب من المكتبة
    try:
        # نحصل على جميع الكتب من قاعدة البيانات
        books = await conn.fetch("SELECT id, file_id, file_name FROM books")
        book_list = [b["file_name"] for b in books]

        # نص الاستعلام للنموذج
        prompt = (
            f"لدي قائمة كتب: {book_list}\n"
            f"المستخدم وصف له: {user_input}\n"
            "أعطني أفضل 5 كتب تتطابق مع وصفه. أجب فقط بأسماء الكتب من القائمة."
        )

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=200
        )

        text = response.choices[0].message.content.strip()
        selected_books = []
        for line in text.split("\n"):
            line = line.strip()
            if line in book_list:
                selected_books.append(line)
            if len(selected_books) >= 5:
                break

        if not selected_books:
            await update.message.reply_text("❌ لم أتمكن من إيجاد كتب مطابقة لوصفك.")
            return

        # عرض الكتب المختارة مع أزرار التحميل
        keyboard = []
        for name in selected_books:
            book = next((b for b in books if b["file_name"] == name), None)
            if book:
                key = book["id"]
                context.bot_data[f"file_{key}"] = book["file_id"]
                keyboard.append([InlineKeyboardButton(f"📘 {name}", callback_data=f"file:{key}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📚 أفضل كتب مطابقة لوصفك:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ AI search error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء البحث بالذكاء الاصطناعي.")
