# admin_panel.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import os
import asyncpg

# ===============================================
#       إعدادات المشرفين والاشتراك الإجباري
# ===============================================
ADMINS = [6166700051] 
FORCE_SUB_CHANNEL_USERNAME = 'iiollr' 
FORCE_SUB_CHANNEL_LINK = f'https://t.me/@{FORCE_SUB_CHANNEL_USERNAME}'
# متغير ثابت مبدئي، سيتم استبداله بقيمة من قاعدة البيانات
DEFAULT_WELCOME_MESSAGE = "مرحباً بك! 📚 يرجى الاشتراك في قناة البوت للمتابعة."

# ===============================================
#       وظائف مساعدة وإدارة الترحيب (وهمية/تحتاج DB)
# ===============================================

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مشرفاً."""
    return user_id in ADMINS

async def get_db_connection(context: ContextTypes):
    """جلب اتصال قاعدة البيانات من سياق التطبيق."""
    return context.bot_data.get('db_conn')

async def add_user_to_db(conn, user_id):
    """حفظ المستخدم الجديد في قاعدة البيانات."""
    try:
        await conn.execute(
            "INSERT INTO users(user_id) VALUES($1) ON CONFLICT (user_id) DO NOTHING", 
            user_id
        )
    except Exception as e:
        print(f"خطأ في حفظ المستخدم: {e}")


# --- وظائف إدارة رسالة الترحيب (تحتاج إلى جدول في DB للإعدادات) ---
# سنفترض وجود جدول إعدادات (settings) لحفظ رسالة الترحيب
# يجب إضافة هذا الجدول في init_db بملف main.py:
# CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

async def load_welcome_message(conn):
    """تحميل رسالة الترحيب المحفوظة من قاعدة البيانات."""
    try:
        result = await conn.fetchval("SELECT value FROM settings WHERE key = 'welcome_message'")
        return result if result else DEFAULT_WELCOME_MESSAGE
    except Exception as e:
        print(f"خطأ في تحميل رسالة الترحيب: {e}")
        return DEFAULT_WELCOME_MESSAGE

async def save_welcome_message(conn, message):
    """حفظ رسالة الترحيب الجديدة في قاعدة البيانات."""
    try:
        await conn.execute(
            "INSERT INTO settings(key, value) VALUES('welcome_message', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            message
        )
        return True
    except Exception as e:
        print(f"خطأ في حفظ رسالة الترحيب: {e}")
        return False


# ===============================================
#       منطق الواجهة (الترحيب/الإدارة)
# ===============================================

# دالة لوحة التحكم الرئيسية (Admin Panel)
async def admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return 

    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📢 إذاعة", callback_data="broadcast")],
        [InlineKeyboardButton("🔗 إجبار الاشتراك", callback_data="force_sub_menu")],
        [InlineKeyboardButton("⚙️ إعدادات", callback_data="settings_menu")] # قائمة الإعدادات الجديدة
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = '**أهلاً بك يا مشرف!**\n\nتفضل لوحة التحكم:'
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

# 1. أمر /start (مُعدَّل)
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = await get_db_connection(context)
    
    # 1. حفظ المستخدم في قاعدة البيانات
    if conn:
        await add_user_to_db(conn, user_id)
    
    # 2. فحص حالة المشرف
    if is_admin(user_id):
        return await admin_main_menu(update, context)

    # 3. فحص الاشتراك الإجباري للمستخدمين العاديين
    try:
        # GetChatMemberRequest لفحص حالة الاشتراك
        chat_member = await context.bot.get_chat_member(f'@{FORCE_SUB_CHANNEL_USERNAME}', user_id)
        
        # إذا لم يكن المشترك
        if chat_member.status not in ['member', 'administrator', 'creator']:
            raise Exception("Not subscribed")

        # إذا كان مشتركاً، يتم تشغيل دالة start الأصلية في الملف الرئيسي
        await original_start(update, context)
        
    except Exception:
        # طلب الاشتراك إذا لم يكن مشتركاً أو حدث خطأ في التحقق
        conn = await get_db_connection(context)
        welcome_msg = await load_welcome_message(conn)
        
        keyboard = [[InlineKeyboardButton("اشترك الآن", url=FORCE_SUB_CHANNEL_LINK)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

# 2. معالج الإحصائيات (Callback)
async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id): return
        
    conn = await get_db_connection(context)
    
    total_users = await conn.fetchval("SELECT COUNT(*) FROM users") if conn else 0
    total_books = await conn.fetchval("SELECT COUNT(*) FROM books") if conn else 0

    stats_text = (
        "📊 **إحصائيات البوت**\n"
        f"  • **إجمالي المستخدمين:** {total_users:,}\n"
        f"  • **إجمالي الكتب المفهرسة:** {total_books:,}\n"
        f"  • **قناة الاشتراك الإجباري:** @{FORCE_SUB_CHANNEL_USERNAME}"
    )
    
    keyboard = [[InlineKeyboardButton("رجوع", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(stats_text, reply_markup=reply_markup)


# 3. معالج قائمة الإعدادات الرئيسية (Callback)
async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id): return

    keyboard = [
        [InlineKeyboardButton("✏️ تعديل رسالة الترحيب", callback_data="edit_welcome_msg")],
        [InlineKeyboardButton("رجوع", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "⚙️ **قائمة الإعدادات**\n\nاختر الإعداد الذي تريد تعديله:",
        reply_markup=reply_markup
    )

# 4. بدء عملية تعديل رسالة الترحيب
async def set_welcome_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id): return
    
    # تعيين حالة الانتظار للمستخدم في user_data
    context.user_data['awaiting_welcome_msg'] = True
    
    await query.edit_message_text(
        "📝 **أرسل رسالة الترحيب الجديدة الآن.**\n\n"
        "*(يمكنك استخدام التنسيقات: **غامق**، `رمز`، _مائل_)*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="settings_menu")]])
    )

# 5. معالج رسالة الترحيب (MessageHandler)
async def set_welcome_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # التحقق من أن المشرف في حالة انتظار الرسالة
    if is_admin(user_id) and context.user_data.get('awaiting_welcome_msg'):
        conn = await get_db_connection(context)
        new_message = update.message.text
        
        success = await save_welcome_message(conn, new_message)
        
        # إزالة حالة الانتظار
        del context.user_data['awaiting_welcome_msg']
        
        if success:
            await update.message.reply_text("✅ تم حفظ رسالة الترحيب بنجاح. ستظهر الرسالة الجديدة عند فحص الاشتراك.",
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع للإعدادات", callback_data="settings_menu")]]))
        else:
            await update.message.reply_text("❌ فشل حفظ رسالة الترحيب في قاعدة البيانات.")


# 6. معالج الإذاعة (Callback) - يحتاج إلى منطق معقد لإدارة الحالة
async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id): return
        
    await query.edit_message_text(
        "📢 **وضع الإذاعة:**\n\nأرسل الآن الرسالة أو الصورة/الملف الذي تريد بثه لجميع المستخدمين.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء الإذاعة", callback_data="main_menu")]])
    )

# 7. معالج قائمة الاشتراك الإجباري (Callback)
async def force_sub_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id): return
        
    text = (
        f"🔗 **إجبار الاشتراك (Force Sub)**\n\n"
        f"القناة الحالية: **@{FORCE_SUB_CHANNEL_USERNAME}**\n"
        f"يتم فحص اشتراك المستخدم في هذه القناة عند الضغط على /start."
    )
    
    keyboard = [[InlineKeyboardButton("رجوع", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)


# ===============================================
#       دالة التسجيل الرئيسية
# ===============================================

original_start = None

def register_admin_handlers(app, original_start_handler):
    """
    تسجيل جميع معالجات المشرفين واستبدال معالج /start الأصلي.
    """
    global original_start
    original_start = original_start_handler
    
    # 1. استبدال معالج /start
    app.add_handler(CommandHandler("start", start_handler))
    
    # 2. معالجات الأزرار الداخلية (Callbacks)
    app.add_handler(CallbackQueryHandler(stats_callback, pattern='^stats$'))
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern='^broadcast$'))
    app.add_handler(CallbackQueryHandler(force_sub_menu_callback, pattern='^force_sub_menu$'))
    app.add_handler(CallbackQueryHandler(admin_main_menu, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern='^settings_menu$')) # قائمة الإعدادات
    app.add_handler(CallbackQueryHandler(set_welcome_message_start, pattern='^edit_welcome_msg$')) # بدء تعديل رسالة الترحيب
    
    # 3. معالج رسالة الترحيب الجديدة (يجب أن يكون بعد المعالجات الأخرى)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & filters.User(user_id=ADMINS[0]), 
        set_welcome_message_handler
    ))
    
    print("✅ تم تسجيل معالجات المشرفين بنجاح.")
