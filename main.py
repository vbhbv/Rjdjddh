import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # 🛑 تم إضافة InlineButton و InlineKeyboardMarkup هنا
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 🛑 الاستيراد من وحدة التحكم الجديدة
from admin_panel import register_admin_handlers 

# ... (بقية تعريفات الدوال تبقى كما هي) ...

# 1. تهيئة قاعدة البيانات والاتصال
async def init_db(app_context: ContextTypes):
    """تهيئة اتصال قاعدة البيانات وتخزينه في سياق التطبيق."""
    try:
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        
        # 📝 أمر إنشاء الجدول اليدوي (تم إضافة جدول users وجدول settings)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,  
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        
        app_context.bot_data['db_conn'] = conn
        print("✅ تم الاتصال بقاعدة البيانات وتهيئة الجدول بنجاح.")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
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
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        
        if conn:
            try:
                # هذا الاستعلام يتطلب وجود القيد UNIQUE في تعريف الجدول
                await conn.execute(
                    "INSERT INTO books(file_id, file_name) VALUES($1, $2) ON CONFLICT (file_id) DO NOTHING", 
                    document.file_id, 
                    document.file_name
                )
                print(f"تمت فهرسة الكتاب: {document.file_name}")
            except Exception as e:
                # لن يتكرر هذا الخطأ إذا كان الجدول محدثًا
                print(f"خطأ في فهرسة الكتاب: {e}") 

# 4. أمر /search (لإرسال الملف للمستخدم)
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يبحث عن ما يصل إلى 10 كتب مطابقة ويعرضها في أزرار Inline.
    """
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return
    
    search_term = " ".join(context.args)
    conn = context.bot_data.get('db_conn')

    if conn:
        # 🛑 تم التعديل هنا: جلب ما يصل إلى 10 نتائج مع الترتيب وإزالة LIMIT 1
        results = await conn.fetch(
            "SELECT file_id, file_name FROM books WHERE file_name ILIKE $1 ORDER BY file_name ASC LIMIT 10",
            f"%{search_term}%" 
        )

        if results:
            if len(results) == 1:
                # إذا كانت نتيجة واحدة، أرسل الملف مباشرة
                file_id = results[0]['file_id']
                book_name = results[0]['file_name']
                
                try:
                    await update.message.reply_document(
                        document=file_id, 
                        caption=f"✅ تم العثور على الكتاب: **{book_name}**"
                    )
                except Exception:
                    await update.message.reply_text("❌ لم أتمكن من إرسال الملف. قد يكون الملف غير صالح أو واجهت مشكلة في تيليجرام.")
            
            else:
                # 🛑 إذا كانت نتائج متعددة، عرضها في أزرار Inline
                
                message_text = f"📚 تم العثور على **{len(results)}** كتاباً يطابق بحثك '{search_term}':\n\n"
                message_text += "الرجاء اختيار النسخة المطلوبة من القائمة أدناه:"
                
                keyboard = []
                for idx, result in enumerate(results):
                    # نستخدم نمط callback_data فريد: "file:<file_id_partial>"
                    # بما أن callback_data محدودة، نستخدم أول 50 حرف من file_id
                    callback_data = f"file:{result['file_id'][:50]}" 
                    
                    # نضع اسم الملف في الزر
                    keyboard.append([InlineKeyboardButton(f"🔗 {result['file_name']}", callback_data=callback_data)])
                    
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        else:
            await update.message.reply_text(f"❌ لم يتم العثور على كتاب يطابق '{search_term}'.")
    else:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات حالياً. حاول لاحقاً.")

# 5. أمر /start (الدالة الأصلية)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة البوت! 📚\n"
        "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب"
    )

# 6. دالة التشغيل الرئيسية
def run_bot():
    """هذه الدالة تستخدم run_polling وهي آمنة للاستخدام في Railway."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN غير متوفر في متغيرات البيئة.")

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)     # لفتح الاتصال وإنشاء الجدول
        .post_shutdown(close_db) # لإغلاق الاتصال
        .build()
    )
    
    # 1. تخزين الدالة الأصلية في متغير
    original_start_handler = start
    
    # 2. معالج البحث ومعالج PDF (كما هي)
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.ChatType.CHANNEL,
        handle_pdf
    ))

    # 3. تسجيل معالجات المشرفين (Admin Handlers)
    # 🛑 هذه الدالة ستقوم بإضافة معالج /start الجديد الذي يتحقق من المشرفين
    register_admin_handlers(app, original_start_handler)


    print("🤖 البوت يعمل الآن...")
    app.run_polling(poll_interval=1.0) 

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"حدث خطأ فادح: {e}")
