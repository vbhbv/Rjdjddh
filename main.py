import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
# إضافة الـ Webhook
from telegram.ext._updater import Updater
from telegram.ext import PicklePersistence

# 🛑 الاستيراد من وحدة التحكم الجديدة
from admin_panel import register_admin_handlers 

# ===============================================
#       وظائف مساعدة
# ===============================================

# تمت إزالة دالة normalize_arabic_text لأن البحث يتم بالكامل في قاعدة البيانات الآن

# ===============================================
#       وظائف البوت الأساسية
# ===============================================

# 1. تهيئة قاعدة البيانات والاتصال
async def init_db(app_context: ContextTypes):
    """تهيئة اتصال قاعدة البيانات، تفعيل إضافات البحث النصي الكامل، وتخزينه في سياق التطبيق."""
    try:
        if not os.getenv("DATABASE_URL"):
            raise ValueError("DATABASE_URL غير متوفر.")
            
        conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
        
        # 📝 1. تفعيل الإضافات اللازمة للبحث النصي الكامل (FTS)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        # 📝 2. إنشاء قالب بحث عربي مخصص يتجاهل التشكيل (Simple Arabic Config)
        await conn.execute("""
            CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS arabic_simple (PARSER = default);
            ALTER TEXT SEARCH CONFIGURATION arabic_simple 
            ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part 
            WITH unaccent, simple;
        """)

        # 📝 3. إنشاء الجداول
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,  
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                -- إضافة عمود فهرسة لتحسين أداء البحث النصي
                tsv_content tsvector
            );
            
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            
            -- إنشاء فهرس GIN على عمود tsv_content لأداء سريع
            CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);
        """)
        
        # 📝 4. إنشاء Trigger لتحديث عمود tsv_content تلقائياً عند إضافة كتاب
        # يتم استخدام التكوين المخصص (arabic_simple) لتجاهل الهمزات والتشكيل
        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_books_tsv() RETURNS trigger AS $$
            BEGIN
                NEW.tsv_content := to_tsvector('arabic_simple', NEW.file_name);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            
            CREATE OR REPLACE TRIGGER tsv_update_trigger
            BEFORE INSERT OR UPDATE OF file_name ON books
            FOR EACH ROW EXECUTE FUNCTION update_books_tsv();
        """)
        
        app_context.bot_data['db_conn'] = conn
        print("✅ تم الاتصال بقاعدة البيانات وتهيئة جداول وفهارس البحث النصي بنجاح.")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
        # لا نرفع RuntimeError لكي لا تتوقف عملية التشغيل في الـ Webhook
        print("🚨 سيستمر التشغيل بدون قاعدة بيانات.")

# 2. إغلاق اتصال قاعدة البيانات
async def close_db(app: Application):
    """إغلاق اتصال قاعدة البيانات عند إيقاف تشغيل البوت."""
    conn = app.bot_data.get('db_conn')
    if conn:
        await conn.close()
        print("✅ تم إغلاق اتصال قاعدة البيانات.")

# 3. معالج رسائل PDF (للفهرسة التلقائية)
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يفهرس أي ملف PDF جديد يصل إلى القناة. يتم تحديث فهرس tsv_content تلقائيًا بواسطة Trigger."""
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        
        if conn:
            try:
                # لا نحتاج لتحديث tsv_content هنا، الـ Trigger سيفعل ذلك تلقائياً
                await conn.execute(
                    "INSERT INTO books(file_id, file_name) VALUES($1, $2) ON CONFLICT (file_id) DO NOTHING", 
                    document.file_id, 
                    document.file_name
                )
                print(f"تمت فهرسة الكتاب: {document.file_name}")
            except Exception as e:
                print(f"خطأ في فهرسة الكتاب: {e}") 

# 4. أمر /search (لإرسال الملف للمستخدم)
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يبحث عن ما يصل إلى 10 كتب مطابقة باستخدام Full-Text Search.
    """
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return
    
    # تحويل مصطلح البحث إلى نص واحد
    search_term = " ".join(context.args).strip()
    
    conn = context.bot_data.get('db_conn')

    if conn:
        # 🛑🛑 استخدام البحث النصي الكامل (FTS): 
        # 1. to_tsquery يحول مصطلح البحث إلى صيغة قابلة للبحث باستخدام التكوين المخصص (arabic_simple).
        # 2. يتم تجاهل الهمزات، التاء المربوطة، إلخ، تلقائياً هنا.
        # 3. يتم استخدام عامل التشغيل @@ للمقارنة مع عمود tsv_content المفهرس.
        search_query = """
            SELECT file_id, file_name 
            FROM books 
            WHERE tsv_content @@ to_tsquery('arabic_simple', $1)
            ORDER BY file_name ASC 
            LIMIT 10
        """
        
        # لضمان عمل to_tsquery بشكل صحيح مع المصطلحات التي تحتوي على مسافات، نستخدم صيغة 'simple'
        # ونستبدل المسافات بعامل '&' (AND) ليتطابق مع كل الكلمات
        query_text = search_term.replace(' ', ' & ')

        results = await conn.fetch(
            search_query,
            query_text
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
    """تستخدم طريقة Webhook وهي آمنة في بيئات الاستضافة مثل Railway."""
    token = os.getenv("BOT_TOKEN")
    port = int(os.environ.get('PORT', 8080)) # المنفذ الافتراضي في Railway
    base_url = os.environ.get('WEB_HOST') # عنوان الـ Domain الممنوح من Railway (يجب أن يكون متاحاً)
    
    if not token or not base_url:
        print("🚨 يجب توفير BOT_TOKEN و WEB_HOST (عادةً يكون عنوان URL الخاص بـ Railway) في متغيرات البيئة.")
        # نعود إلى Polling كحل احتياطي إذا لم تتوفر متغيرات الـ Webhook (للتشغيل المحلي)
        if token:
             print("⚠️ Webhook غير متوفر. يتم تشغيل البوت باستخدام Polling. تأكد من أن نسخة واحدة فقط تعمل.")
             return run_polling_fallback(token)
        raise ValueError("BOT_TOKEN غير متوفر في متغيرات البيئة.")


    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)     # لفتح الاتصال وإنشاء الجدول
        .post_shutdown(close_db) # لإغلاق الاتصال
        .persistence(PicklePersistence(filepath="bot_data.pickle")) # لتخزين بيانات المشرفين مؤقتاً
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
    register_admin_handlers(app, original_start_handler)

    
    # 🛑 4. تشغيل البوت باستخدام الـ Webhook
    
    webhook_url = f'https://{base_url}'
    
    print(f"🤖 تشغيل البوت عبر Webhook على: {webhook_url}:{port}")
    
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token, # استخدام التوكن كمسار آمن
        webhook_url=f"{webhook_url}/{token}",
        secret_token=os.getenv("WEBHOOK_SECRET") # إضافة Secret Token لزيادة الأمان
    )


def run_polling_fallback(token):
    """دالة احتياطية لتشغيل البوت في حال عدم توفر Webhook (للتشغيل المحلي)."""
    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )
    
    original_start_handler = start
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.ChatType.CHANNEL,
        handle_pdf
    ))
    register_admin_handlers(app, original_start_handler)

    print("⚠️ البوت يعمل في وضع Polling. تذكر: لا تشغل نسختين.")
    app.run_polling(poll_interval=1.0)


if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"حدث خطأ فادح: {e}")
