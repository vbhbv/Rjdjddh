# admin_panel.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import os
import asyncpg # لاستخدامه في جلب الاتصال من bot_data

# ===============================================
#       إعدادات المشرفين والاشتراك الإجباري
# ===============================================
ADMINS = [6166700051] 
FORCE_SUB_CHANNEL_USERNAME = 'iiollr' 
FORCE_SUB_CHANNEL_LINK = f'https://t.me/@{FORCE_SUB_CHANNEL_USERNAME}'
WELCOME_MESSAGE = "مرحباً بك! 📚 يرجى الاشتراك في قناة البوت للمتابعة."

# ===============================================
#       وظائف مساعدة
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

# ===============================================
#       منطق الواجهة (الترحيب/الإدارة)
# ===============================================

# دالة لوحة التحكم الرئيسية (Admin Panel)
async def admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return # لا يفعل شيئاً لغير المشرف

    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📢 إذاعة", callback_data="broadcast")],
        [InlineKeyboardButton("🔗 إجبار الاشتراك", callback_data="force_sub_menu")],
        [InlineKeyboardButton("⚙️ إعدادات", callback_data="settings_menu")]
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
        
        # إذا لم يكن المشترك (member) أو (administrator) أو (creator)
        if chat_member.status not in ['member', 'administrator', 'creator']:
            raise Exception("Not subscribed")

        # إذا كان مشتركاً، يتم تشغيل دالة start الأصلية في الملف الرئيسي
        await original_start(update, context)
        
    except Exception:
        # طلب الاشتراك إذا لم يكن مشتركاً أو حدث خطأ في التحقق
        keyboard = [[InlineKeyboardButton("اشترك الآن", url=FORCE_SUB_CHANNEL_LINK)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(WELCOME_MESSAGE, reply_markup=reply_markup)

# 2. معالج الإحصائيات (Callback)
async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
        
    conn = await get_db_connection(context)
    
    # جلب إحصائيات من قاعدة البيانات
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


# 3. معالج الإذاعة (Callback) - يحتاج إلى منطق معقد لإدارة الحالة
async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
        
    await query.edit_message_text(
        "📢 **وضع الإذاعة:**\n\nأرسل الآن الرسالة أو الصورة/الملف الذي تريد بثه لجميع المستخدمين.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء الإذاعة", callback_data="main_menu")]])
    )

# 4. معالج قائمة الاشتراك الإجباري (Callback)
async def force_sub_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        return
        
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

# نحتاج إلى دالة التسجيل الأساسية، ونستبدل دالة start الأصلية بالدالة الجديدة.
original_start = None

def register_admin_handlers(app, original_start_handler):
    """
    تسجيل جميع معالجات المشرفين واستبدال معالج /start الأصلي.
    
    Args:
        app: كائن التطبيق (Application) الخاص بـ python-telegram-bot.
        original_start_handler: دالة start الأصلية من الملف الرئيسي.
    """
    global original_start
    original_start = original_start_handler
    
    # 1. استبدال معالج /start
    # يجب إزالة معالج start الأصلي أولاً في main.py قبل استدعاء هذه الدالة
    # ثم يتم تسجيل start_handler الجديدة هنا
    app.add_handler(CommandHandler("start", start_handler))
    
    # 2. معالجات الأزرار الداخلية (Callbacks)
    app.add_handler(CallbackQueryHandler(stats_callback, pattern='^stats$'))
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern='^broadcast$'))
    app.add_handler(CallbackQueryHandler(force_sub_menu_callback, pattern='^force_sub_menu$'))
    app.add_handler(CallbackQueryHandler(admin_main_menu, pattern='^main_menu$'))
    
    print("✅ تم تسجيل معالجات المشرفين بنجاح.")
