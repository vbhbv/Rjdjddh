import os
import asyncpg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. تهيئة قاعدة البيانات والاتصال
async def init_db(app_context: ContextTypes):
    """تهيئة اتصال قاعدة البيانات وتخزينه في سياق التطبيق."""
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        # إنشاء جدول الكتب
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # تخزين الاتصال في سياق التطبيق لاستخدامه في المعالجات
        app_context.bot_data['db_conn'] = conn
        print("✅ تم الاتصال بقاعدة البيانات وتهيئة الجدول بنجاح.")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
        # إنهاء التطبيق إذا فشل الاتصال بالقاعدة
        raise RuntimeError("فشل تهيئة قاعدة البيانات")

# 2. إغلاق اتصال قاعدة البيانات
async def close_db(app: Application):
    """إغلاق اتصال قاعدة البيانات عند إيقاف تشغيل البوت."""
    conn = app.bot_data.get('db_conn')
    if conn:
        await conn.close()
        print("✅ تم إغلاق اتصال قاعدة البيانات.")

# 3. معالج رسائل PDF (للفهرسة التلقائية)
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يفهرس أي ملف PDF جديد يصل إلى القناة."""
    # نتحقق من وجود الرسالة في القناة وأنها PDF
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn') # جلب الاتصال من السياق
        
        if conn:
            try:
                # فهرسة في قاعدة البيانات، مع تجاهل التكرار
                await conn.execute(
                    "INSERT INTO books(file_id, file_name) VALUES($1, $2) ON CONFLICT (file_id) DO NOTHING", 
                    document.file_id, 
                    document.file_name
                )
                print(f"تمت فهرسة الكتاب: {document.file_name}")
            except Exception as e:
                # لا ينبغي أن يحدث هذا طالما الاتصال مفتوح
                print(f"خطأ في فهرسة الكتاب: {e}")

# 4. أمر /search (لإرسال الملف للمستخدم)
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """البحث عن كتاب وإرسال الملف للمستخدم."""
    
    # تأكد أن الطلب ليس من القناة نفسها
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return
    
    search_term = " ".join(context.args)
    conn = context.bot_data.get('db_conn')

    if conn:
        # البحث في قاعدة البيانات (ILKE للبحث الجزئي وغير الحساس لحالة الأحرف)
        result = await conn.fetchrow(
            "SELECT file_id, file_name FROM books WHERE file_name ILIKE $1 LIMIT 1",
            f"%{search_term}%" 
        )

        if result:
            file_id = result['file_id']
            book_name = result['file_name']
            
            try:
                # إرسال الملف
                await update.message.reply_document(
                    document=file_id, 
                    caption=f"✅ تم العثور على الكتاب: **{book_name}**"
                )
            except Exception:
                 # في حالة فشل الإرسال (قد يكون الملف ضخمًا جدًا أو تم حذفه من سيرفرات تيليجرام)
                await update.message.reply_text("❌ لم أتمكن من إرسال الملف. قد يكون الملف غير صالح أو واجهت مشكلة في تيليجرام.")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على كتاب يطابق '{search_term}'.")
    else:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات حالياً. حاول لاحقاً.")

# 5. أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة البوت! 📚\n"
        "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب"
    )

# 6. دالة التشغيل الرئيسية
def run_bot():
    """هذه الدالة تستخدم run_polling وهي آمنة للاستخدام في Railway."""
    # متغيرات البيئة مطلوبة
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN غير متوفر في متغيرات البيئة.")

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)     # يتم تنفيذها قبل تشغيل البوت (للاتصال بالقاعدة)
        .post_shutdown(close_db) # يتم تنفيذها عند إيقاف البوت (لإغلاق الاتصال)
        .build()
    )
    
    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book))
    
    # المعالج الخاص بأرشفة القناة (يستمع فقط لـ PDF في القنوات)
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.ChatType.CHANNEL,
        handle_pdf
    ))

    print("🤖 البوت يعمل الآن...")
    # استخدام run_polling لحلقة الأحداث، وهو أكثر موثوقية في بيئات الاستضافة
    app.run_polling(poll_interval=1.0) 

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"حدث خطأ فادح: {e}")
