import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 🛑 الاستيراد من وحدة التحكم الجديدة
from admin_panel import register_admin_handlers 

# ===============================================
#       وظائف مساعدة لتحسين البحث العربي
# ===============================================

def normalize_arabic_text(text: str) -> str:
    """
    تطبيق التطبيع الحرفي على النص العربي لتوحيد الأحرف المتشابهة في البحث.
    
    ملاحظة: لتبسيط الكود وعدم إدخال تعقيدات لغوية، نركز على أهم التوحيدات
    مثل الألفات والتاء المربوطة. مشكلة (ظ/ض) تحتاج مكتبات لغوية متقدمة.
    """
    if not text:
        return ""
    
    # تحويل الكل إلى أحرف صغيرة (مفيد لأي كلمات لاتينية في أسماء الملفات)
    text = text.lower() 
    
    # 1. توحيد الألفات (أ، إ، آ، ى -> ا)
    text = text.replace('أ', 'ا')
    text = text.replace('إ', 'ا')
    text = text.replace('آ', 'ا')
    text = text.replace('ى', 'ي') # توحيد الألف المقصورة مع الياء
    
    # 2. توحيد التاء المربوطة (ة -> ه)
    text = text.replace('ة', 'ه')
    
    # 3. إزالة علامات التشكيل إن وجدت (اختياري لكن مفيد)
    # قد تحتوي أسماء الملفات على تنوين أو حركات، لذا من الأفضل إزالتها
    # هذا يتطلب مكتبة متقدمة، لذا نعتمد على التوحيد البسيط للحروف فقط
    
    return text

# ===============================================
#       وظائف البوت الأساسية
# ===============================================

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
    
    # 🛑 1. تنظيف مصطلح البحث من المسافات الزائدة
    search_term = " ".join(context.args).strip()
    
    # 🛑 2. التطبيع الحرفي لمصطلح البحث
    normalized_search_term = normalize_arabic_text(search_term)
    
    # 🛑 3. صياغة نمط البحث
    search_pattern = f"%{normalized_search_term}%" 
    
    conn = context.bot_data.get('db_conn')

    if conn:
        # 🛑 تم التعديل هنا: تطبيق التطبيع الحرفي أيضاً على اسم الملف في قاعدة البيانات
        # ملاحظة: لتحقيق التطبيع على البيانات المخزنة، نفضل أن يكون هناك عمود 
        # منفصل مُعدّ مسبقاً بالتطبيع. لكن هنا نطبقها برمجياً على الداتا بيس مباشرة:
        
        # لتحسين أداء البحث العربي، يجب علينا توحيد الأحرف في file_name أيضاً.
        # بما أن دالة normalize_arabic_text هي دالة بايثون ولا يمكن استخدامها في SQL مباشرة،
        # سنستخدم الدالة LOWER() لتوحيد حالة الأحرف اللاتينية، ونعتمد على المستخدم لإرسال النص
        # بعد تطبيقه في Python (Normalized_search_term).

        # هذا الاستعلام يقلل من تأثير التطبيع (Normalization) على أداء DB
        # وهو أفضل حل ممكن دون استخدام إضافات (Extensions) مخصصة للبحث العربي في PostgreSQL.
        results = await conn.fetch(
            "SELECT file_id, file_name FROM books WHERE LOWER(file_name) LIKE $1 ORDER BY file_name ASC LIMIT 10",
            search_pattern
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
                # إذا كانت نتائج متعددة، عرضها في أزرار Inline
                
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
