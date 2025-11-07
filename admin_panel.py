# admin_panel.py (محدث بالمعرفات الجديدة)

from telethon import events, Button
from telethon.tl.types import ChannelParticipantsAdmins

# ===============================================
#       إعدادات المشرفين والاشتراك الإجباري
# ===============================================

# 🛑 تم إضافة ID المستخدم الجديد كـ مشرف
ADMINS = [6166700051] 
# 🛑 تم إضافة قناة الاشتراك الإجباري
FORCE_SUB_CHANNEL = '@iiollr' 
WELCOME_MESSAGE = "مرحباً بك! يرجى الاشتراك في قناة البوت للمتابعة."

# ===============================================
#       وظائف مساعدة
# ===============================================

def is_admin(user_id):
    """التحقق مما إذا كان المستخدم مشرفاً."""
    # ملاحظة: التحقق من ID المستخدم مباشرة هو أفضل طريقة هنا
    return user_id in ADMINS

async def get_total_users(client):
    """جلب عدد المستخدمين الكلي للبوت (تقديري)."""
    # (هذه وظيفة وهمية/تقديرية، في الواقع تحتاج لجلب العدد من قاعدة بيانات البوت)
    try:
        # تستخدم للحصول على عدد تقريبي للمستخدمين في حالة عدم وجود قاعدة بيانات
        dialogs = await client.get_dialogs()
        users_count = sum(1 for d in dialogs if d.is_user and not d.entity.bot)
        return users_count
    except Exception:
        return 0 

# ===============================================
#       أوامر المشرفين
# ===============================================

def register_admin_handlers(client):
    """تسجيل جميع معالجات أوامر المشرفين في البوت."""
    
    # --- 1. الأمر /start والترحيب ---
    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        user_id = event.sender_id
        
        # إذا كان المستخدم مشرفاً
        if is_admin(user_id):
            await event.reply('**أهلاً بك يا مشرف!**\n\nتفضل لوحة التحكم:', 
                              buttons=[
                                  [Button.inline("📊 إحصائيات", data="stats")],
                                  [Button.inline("📢 إذاعة", data="broadcast")],
                                  [Button.inline("🔗 إجبار الاشتراك", data="force_sub_menu")],
                                  [Button.inline("⚙️ إعدادات", data="settings_menu")]
                              ])
            return
            
        # فحص الاشتراك الإجباري للمستخدمين العاديين
        try:
            # التحقق من الاشتراك
            channel_entity = await client.get_entity(FORCE_SUB_CHANNEL)
            
            # محاولة جلب معلومات المشترك
            is_subscribed = await client.get_participant(channel_entity, event.sender_id)
            
            # إذا نجح (أي المشترك موجود)، يتم الترحيب العادي
            await event.reply(f"مرحباً بك في البوت! 👋") 

        except Exception as e:
            # إذا فشل (مثل عدم وجود المشترك)، يتم طلب الاشتراك
            if 'User not participating' in str(e) or 'Peer ID invalid' in str(e):
                await event.reply(
                    WELCOME_MESSAGE,
                    buttons=[[Button.url("اشترك الآن", f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")]]
                )
            else:
                 # رسالة ترحيب عادية في حالة حدوث خطأ آخر
                 await event.reply("مرحباً بك! يرجى التأكد من الاشتراك في القناة.")

    # --- 2. الإحصائيات ---
    @client.on(events.CallbackQuery(data='stats'))
    async def stats_callback(event):
        if not is_admin(event.sender_id):
            return
            
        total_users = await get_total_users(client)
        
        stats_text = (
            "📊 **إحصائيات البوت**\n"
            f"  • **إجمالي المستخدمين:** {total_users:,}\n"
            f"  • **الكتب المنسوخة (وهمي):** 500 كتاب"
        )
        await event.edit(stats_text)


    # --- 3. الإذاعة (البدء) ---
    @client.on(events.CallbackQuery(data='broadcast'))
    async def broadcast_start_callback(event):
        if not is_admin(event.sender_id):
            return
            
        # (يتطلب دالة لتعيين الحالة في ملف main.py أو قاعدة بيانات)
        await event.edit("📢 **وضع الإذاعة:**\n\nأرسل الآن الرسالة أو الصورة/الملف الذي تريد بثه لجميع المستخدمين.",
                         buttons=[[Button.inline("إلغاء الإذاعة", data="cancel_broadcast")]])


    # --- 4. أمر وهمي لإعدادات الاشتراك الإجباري ---
    @client.on(events.CallbackQuery(data='force_sub_menu'))
    async def force_sub_menu_callback(event):
        if not is_admin(event.sender_id):
            return
            
        await event.edit(f"🔗 **إجبار الاشتراك (Force Sub)**\n\nالقناة الحالية: `{FORCE_SUB_CHANNEL}`", 
                         buttons=[[Button.inline("رجوع", data="start")]])
        

    # --- 5. أمر الرجوع للوحة التحكم الرئيسية ---
    @client.on(events.CallbackQuery(data='start'))
    async def back_to_main_menu(event):
        if not is_admin(event.sender_id):
            return

        await event.edit('**أهلاً بك يا مشرف!**\n\nتفضل لوحة التحكم:', 
                          buttons=[
                              [Button.inline("📊 إحصائيات", data="stats")],
                              [Button.inline("📢 إذاعة", data="broadcast")],
                              [Button.inline("🔗 إجبار الاشتراك", data="force_sub_menu")],
                              [Button.inline("⚙️ إعدادات", data="settings_menu")]
                          ])
  
