import os
import asyncio
import asyncpg
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# متغيرات البيئة
TOKEN = os.getenv("BOT_TOKEN")
# CHANNEL_ID لم يعد يستخدم بشكل مباشر في المعالج (سيتم الاستماع لجميع القنوات التي فيها البوت)
# لكن سنحتفظ به للتأكد من ربط البوت بالقناة الصحيحة.
DATABASE_URL = os.getenv("DATABASE_URL")

# اتصال قاعدة البيانات (سيتم تخزينه في ContextTypes لتجنب إعادة الاتصال)
DB_CONN = None

# 1. إنشاء اتصال مع قاعدة البيانات
async def init_db():
    global DB_CONN
    if DB_CONN is None:
        DB_CONN = await asyncpg.connect(DATABASE_URL)
        # إنشاء جدول للكتب إذا لم يكن موجودًا
        await DB_CONN.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE, -- إضافة UNIQUE لمنع تكرار الملفات في الفهرسة
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            )
        """)
    return DB_CONN

# 2. معالج رسائل PDF (للفهرسة التلقائية)
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من أن الرسالة تأتي من قناة (ChatType.CHANNEL) وأنها تحتوي على ملف PDF
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        
        document = update.channel_post.document
        conn = await init_db() # جلب اتصال قاعدة البيانات
        
        try:
            # فهرسة في قاعدة البيانات
            await conn.execute(
                "INSERT INTO books(file_id, file_name) VALUES($1, $2) ON CONFLICT (file_id) DO NOTHING", 
                document.file_id, 
                document.file_name
            )
            print(f"تمت فهرسة الكتاب: {document.file_name}")
        except Exception as e:
            print(f"خطأ في فهرسة الكتاب: {e}")

# 3. أمر /search (لإعادة توجيه الملف للمستخدم)
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    # التحقق من أن الطلب ليس من القناة نفسها لتجنب تكرار الردود
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب الذي تبحث عنه بعد الأمر. مثال: /search اسم الكتاب")
        return
    
    search_term = " ".join(context.args)
    conn = await init_db()
    
    # البحث في قاعدة البيانات (يمكن تحسين استعلام البحث)
    result = await conn.fetchrow(
        "SELECT file_id, file_name FROM books WHERE file_name ILIKE $1 LIMIT 1",
        f"%{search_term}%" # استخدام ILIKE للبحث غير الحساس لحالة الأحرف
    )

    if result:
        file_id = result['file_id']
        book_name = result['file_name']
        
        # إعادة توجيه الملف للمستخدم مباشرة
        # **ملاحظة:** لضمان عمل إعادة التوجيه/الإرسال، يجب أن يكون البوت يمتلك صلاحية الوصول للملف.
        await update.message.reply_document(
            document=file_id, 
            caption=f"✅ تم العثور على الكتاب: **{book_name}**"
        )
    else:
        await update.message.reply_text(f"❌ لم يتم العثور على كتاب باسم '{search_term}'.")

# 4. أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة البوت! \n"
        "كل ملف PDF يتم إرساله للقناة يتم فهرسته تلقائيًا.\n"
        "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب"
    )

# 5. الدالة الرئيسية
async def main():
    await init_db() # تهيئة قاعدة البيانات مرة واحدة
    
    app = Application.builder().token(TOKEN).build()
    
    # إضافة المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_book)) # المعالج الجديد للبحث
    
    # 🌟 المعالج الضروري لمراقبة رسائل القناة
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.ChatType.CHANNEL, # استمع فقط لملفات PDF في القنوات
        handle_pdf
    ))

    # تشغيل البوت
    print("البوت يعمل...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        # استخدام asyncio.run لتشغيل الدالة الرئيسية بشكل صحيح
        asyncio.run(main())
    except KeyboardInterrupt:
        print("تم إيقاف البوت.")
    finally:
        # إغلاق اتصال قاعدة البيانات عند الخروج
        if DB_CONN:
            asyncio.run(DB_CONN.close())
