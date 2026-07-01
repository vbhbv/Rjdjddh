import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.error import TelegramError, Forbidden, BadRequest
from functools import wraps

logger = logging.getLogger(__name__)

# ===============================================
# إعدادات المشرفين
# ===============================================
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "5493390715"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# ===============================================
# دوال مساعدة
# ===============================================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID and ADMIN_USER_ID != 0:
            return await func(update, context, *args, **kwargs)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ أمر خاص بالمشرفين فقط.")
        return
    return wrapper

# ===============================================
# أوامر التفعيل ومنح البريميوم الزمني
# ===============================================
@admin_only
async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ **طريقة الاستخدام الصحيحة للأمر:**\n\n"
            "• شهري (30 يوم):\n`/set_premium ID month`\n"
            "• نصف سنوي (180 يوم):\n`/set_premium ID half`\n"
            "• سنوي (365 يوم):\n`/set_premium ID year`"
        )
        return
    
    try:  
        user_id = int(context.args[0])  
        duration_type = context.args[1].lower()  
          
        if duration_type == "month":  
            days_to_add = 30  
            duration_text = "شهر واحد (30 يوم)"  
        elif duration_type == "half":  
            days_to_add = 180  
            duration_text = "نصف سنة (180 يوم)"  
        elif duration_type == "year":  
            days_to_add = 365  
            duration_text = "سنة كاملة (365 يوم)"  
        else:  
            await update.message.reply_text("❌ خيار غير صحيح! اختر إما: `month` أو `half` أو `year`.")  
            return  

        pool = context.bot_data.get('db_conn')  
          
        async with pool.acquire() as conn:  
            await conn.execute("""  
                UPDATE users   
                SET is_premium = TRUE,   
                    premium_expiry = NOW() + ($2 || ' days')::INTERVAL  
                WHERE user_id = $1  
            """, user_id, str(days_to_add))  
          
        await update.message.reply_text(f"✅ تم تفعيل البريميوم بنجاح للمستخدم: {user_id}\n⏱ المدة الممنوحة: **{duration_text}**")  
          
        try:  
            await context.bot.send_message(  
                chat_id=user_id,   
                text=f"🌟 **مبروك! تم تفعيل العضوية المميزة (Premium) لحسابك بنجاح.**\n\n⏳ المدة: **{duration_text}**\n🚀 يمكنك الآن الاستمتاع ببحث وتحميل غير محدود دون أي قيود!"  
            )  
        except: pass  
    except Exception as e:  
        await update.message.reply_text(f"❌ حدث خطأ في قاعدة البيانات: {e}")

@admin_only
async def remove_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ يرجى كتابة الأيدي بعد الأمر.")
        return

    try:  
        user_id = int(context.args[0])  
        pool = context.bot_data.get('db_conn')  
          
        async with pool.acquire() as conn:  
            await conn.execute("""  
                UPDATE users   
                SET is_premium = FALSE, premium_expiry = NULL   
                WHERE user_id = $1  
            """, user_id)  
              
        await update.message.reply_text(f"🚫 تم إلغاء البريميوم الزمني تماماً للمستخدم: {user_id}")  
    except Exception as e:  
        await update.message.reply_text(f"❌ حدث خطأ: {e}")

# ===============================================
# إدارة الحظر (Ban System)
# ===============================================
@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ طريقة الاستخدام:\n/ban ID")
        return

    try:  
        user_id = int(context.args[0])  
        user_data_dict = dict(context.application.user_data)  
        if user_id not in user_data_dict:  
            user_data_dict[user_id] = {}  
          
        context.application.user_data[user_id]["is_banned"] = True  
        await update.message.reply_text(f"🔒 **تم حظر المستخدم بنجاح:** {user_id}")  
    except ValueError:  
        await update.message.reply_text("❌ يرجى كتابة معرف مستخدم (ID) رقمي صحيح.")  
    except Exception as e:  
        await update.message.reply_text(f"❌ خطأ غير متوقع أثناء الحظر: {e}")

@admin_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ طريقة الاستخدام:\n/unban ID")
        return

    try:  
        user_id = int(context.args[0])  
        user_data_dict = dict(context.application.user_data)  
        if user_id in user_data_dict:  
            context.application.user_data[user_id]["is_banned"] = False  
              
        await update.message.reply_text(f"🔓 **تم إلغاء حظر المستخدم بنجاح:** {user_id}")  
    except ValueError:  
        await update.message.reply_text("❌ يرجى كتابة معرف مستخدم (ID) رقمي صحيح.")  
    except Exception as e:  
        await update.message.reply_text(f"❌ خطأ غير متوقع أثناء إلغاء الحظر: {e}")

# ===============================================
# بقية المهام والاشتراكات
# ===============================================
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id:
        pool = context.bot_data.get('db_conn')
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", update.effective_user.id)
            except: pass

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data:
        u_id = update.effective_user.id
        user_data_dict = dict(context.application.user_data)
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            return False

    required_channel = context.bot_data.get("required_channel_id")  
    if required_channel is None:   
        return True  
    try:  
        member = await context.bot.get_chat_member(required_channel, update.effective_user.id)  
        if member.status in ["left", "kicked"]:  
            await update.message.reply_text("❌ يجب الاشتراك في القناة أولاً قبل استخدام البوت.")  
            return False  
        return True  
    except:   
        return False

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_conn')
    if pool:
        async with pool.acquire() as conn:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            premium_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_premium = TRUE AND (premium_expiry IS NULL OR premium_expiry > NOW())")

        stats_text = (  
            "📊 **لوحة تحكم المكتبة الكبرى v3.1**\n"  
            "--------------------------------------\n"  
            f"📚 الكتب المفهرسة كلياً: **{book_count:,}**\n"  
            f"👥 المستخدمين الكلي: **{total_users:,}**\n"  
            f"⭐ الأعضاء المميزين (الزمني): **{premium_users:,}**\n"  
            "--------------------------------------\n"  
            "🛠 **أوامر الإدارة والتفعيل الزمني:**\n"  
            "• شهري: `/set_premium ID month`\n"  
            "• نصف سنوي: `/set_premium ID half`\n"  
            "• سنوي: `/set_premium ID year`\n"  
            "• لإلغاء البريميوم: `/rem_premium ID`\n"  
            "--------------------------------------\n"  
            "📢 **إعدادات الاشتراك الإجباري:**\n"  
            "• تعيين/تغيير القناة: `/setchannel @username` أو `/setchannel ID`\n"  
            "--------------------------------------\n"  
            "🚫 **أوامر الحظر والتحكم:**\n"  
            "• لحظر مستخدم كلياً: `/ban ID`\n"  
            "• لإلغاء حظر مستخدم: `/unban ID`\n"  
            "• للبث الشامل: `/broadcast نص الرسالة`"  
        )  
        await update.message.reply_text(stats_text, parse_mode='Markdown')

# ===============================================
# ميزة الإذاعة الآمنة والذكية في الخلفية المصلحة تماماً
# ===============================================
async def _background_broadcast(users, msg, context: ContextTypes.DEFAULT_TYPE, admin_chat_id: int):
    user_data_dict = dict(context.application.user_data) if context.application.user_data else {}
    success_count = 0
    fail_count = 0
    
    for index, r in enumerate(users):
        u_id = r['user_id']
        
        if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
            continue
            
        try:   
            await context.bot.send_message(chat_id=u_id, text=msg)  
            success_count += 1
            
            if index % 20 == 0:
                await asyncio.sleep(1.0)
                
        except Forbidden:
            fail_count += 1
        except BadRequest:
            fail_count += 1
        except TelegramError as e:
            # صيد أخطاء التدفق (Flood / Rate Limits) ديناميكياً من نص الخطأ دون الحاجة لاستيراد مخصص تالف
            if "retry after" in str(e).lower():
                try:
                    retry_after = int(''.join(filter(str.isdigit, str(e))))
                except:
                    retry_after = 10
                await asyncio.sleep(retry_after)
                try:
                    await context.bot.send_message(chat_id=u_id, text=msg)
                    success_count += 1
                except:
                    fail_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    try:
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=(
                "📢 **اكتملت إذاعة الخلفية بنجاح!**\n\n"
                f"🟢 تم التسليم بنجاح: **{success_count:,}**\n"
                f"🔴 فشل الإرسال (حظر/محذوف): **{fail_count:,}**\n\n"
                "⚡ البوت لم يتأثر طوال فترة البث وعمل بكفاءة."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Could not send broadcast report to admin: {e}")

@admin_only
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: 
        await update.message.reply_text("⚠️ يرجى كتابة نص الإذاعة بعد الأمر.")
        return
        
    msg = " ".join(context.args)
    pool = context.bot_data.get('db_conn')
    
    if not pool:
        await update.message.reply_text("❌ قاعدة البيانات غير متوفرة حالياً.")
        return

    async with pool.acquire() as conn:  
        users = await conn.fetch("SELECT user_id FROM users")  
          
    await update.message.reply_text(
        f"🚀 **بدأت الإذاعة لـ {len(users)} مستخدم في الخلفية!**\n"  
        f"⚡ البوت يعمل الآن بكامل طاقته ويستقبل طلبات البحث كالمعتاد.\n"
        f"📊 سيصلك تقرير تفصيلي هنا فور الانتهاء كلياً."
    )  
    
    asyncio.create_task(
        _background_broadcast(users, msg, context, update.effective_chat.id)
    )

@admin_only
async def set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ طريقة الاستخدام:\n/setchannel @username أو /setchannel ID")
        return

    try:  
        arg = context.args[0]  
        if arg.startswith("@"):  
            chat = await context.bot.get_chat(arg)  
            target_id = chat.id  
            channel_name = chat.title or arg  
        else:  
            target_id = int(arg)  
            chat = await context.bot.get_chat(target_id)  
            channel_name = chat.title or str(target_id)  
              
        context.bot_data["required_channel_id"] = target_id  
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري بنجاح وحفظها دائمياً!\n📌 القناة: **{channel_name}**")  
    except Exception as e:  
        await update.message.reply_text("❌ لم يتم العثور على القناة. تأكد من رفع البوت مشرفاً أولاً.")

def register_admin_handlers(application, original_start_handler):
    async def start_with_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and application.user_data:
            u_id = update.effective_user.id
            user_data_dict = dict(application.user_data)
            if u_id in user_data_dict and user_data_dict[u_id].get("is_banned"):
                return

        if await check_subscription(update, context):  
            await track_user(update, context)  
            await original_start_handler(update, context)  

    application.add_handler(CommandHandler("admin", admin_panel))  
    application.add_handler(CommandHandler("set_premium", set_premium))  
    application.add_handler(CommandHandler("rem_premium", remove_premium))  
    application.add_handler(CommandHandler("ban", ban_user))  
    application.add_handler(CommandHandler("unban", unban_user))  
    application.add_handler(CommandHandler("broadcast", admin_broadcast))  
    application.add_handler(CommandHandler("setchannel", set_channel))
