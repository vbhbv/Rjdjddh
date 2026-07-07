import os
import asyncio
import logging
from datetime import datetime, time
import pytz  # لضبط توقيت إرسال التقرير اليومي بدقة
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.error import TelegramError, Forbidden, BadRequest
from functools import wraps

logger = logging.getLogger(__name__)

# ==============================================================================
# 🛠️ الإعدادات والصلاحيات (Permissions & Config)
# ==============================================================================

try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "5493390715"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")


def admin_only(func):
    """ديكوريتور للتحقق من هوية المشرف قبل تنفيذ الأوامر"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user and update.effective_user.id == ADMIN_USER_ID and ADMIN_USER_ID != 0:
            return await func(update, context, *args, **kwargs)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ أمر خاص بالمشرفين فقط.")
        return
    return wrapper


# ==============================================================================
# ⭐ إدارة تفعيل البريميوم الزمني (Premium Membership)
# ==============================================================================

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
                text=f"🌟 **مبروك! تم تفعيل العضوية المميزة (Premium) لحسابك بنجاح.**\n\n"
                     f"⏳ المدة: **{duration_text}**\n"
                     f"🚀 يمكنك الآن الاستمتاع ببحث وتحميل غير محدود دون أي قيود!"  
            )  
        except Exception: 
            pass  
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


# ==============================================================================
# 🔒 نظام الحظر الشامل (Ban System)
# ==============================================================================

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


# ==============================================================================
# 📊 لوحة التحكم والإحصائيات (Admin Panel)
# ==============================================================================

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get('db_conn')
    if pool:
        async with pool.acquire() as conn:
            book_count = await conn.fetchval("SELECT COUNT(*) FROM books")
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            premium_users = await conn.fetchval("""
                SELECT COUNT(*) FROM users 
                WHERE is_premium = TRUE AND (premium_expiry IS NULL OR premium_expiry > NOW())
            """)

        stats_text = (  
            "📊 **لوحة تحكم المكتبة الكبرى v3.2**\n"  
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
            "• إحصائيات الـ 24 ساعة: `/channel_stats`\n"
            "--------------------------------------\n"  
            "🚫 **أوامر الحظر والتحكم:**\n"  
            "• لحظر مستخدم كلياً: `/ban ID`\n"  
            "• لإلغاء حظر مستخدم: `/unban ID`\n"  
            "• للبث الشامل: `/broadcast نص الرسالة`"  
        )  
        await update.message.reply_text(stats_text, parse_mode='Markdown')


# ==============================================================================
# 📢 ميزة الإذاعة الآمنة والذكية في الخلفية (Background Broadcast)
# ==============================================================================

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
            if "retry after" in str(e).lower():
                try:
                    retry_after = int(''.join(filter(str.isdigit, str(e))))
                except ValueError:
                    retry_after = 10
                await asyncio.sleep(retry_after)
                try:
                    await context.bot.send_message(chat_id=u_id, text=msg)
                    success_count += 1
                except Exception:
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


# ==============================================================================
# 📢 إدارة الاشتراك الإجباري والتحليل الزمني (Force Subscribe Stats)
# ==============================================================================

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


@admin_only
async def channel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    required_channel = context.bot_data.get("required_channel_id")
    pool = context.bot_data.get('db_conn')
    
    if required_channel is None:
        await update.message.reply_text("❌ لم يتم تعيين قناة اشتراك إجباري للبوت حتى الآن.")
        return

    try:
        chat_info = await context.bot.get_chat(required_channel)
        channel_title = chat_info.title or "القناة المشتركة"
        
        joined_last_24h = 0
        if pool:
            async with pool.acquire() as conn:
                # 🔄 فحص ما إذا حان وقت تصفير العداد (مرت 24 ساعة)
                reset_needed = await conn.fetchval("""
                    SELECT (NOW() >= reset_at) FROM bot_counters WHERE counter_name = 'sub_verified_24h'
                """)
                
                if reset_needed:
                    # تصفير العداد الرقمي وإعادة جدولة الـ 24 ساعة القادمة تلقائياً
                    await conn.execute("""
                        UPDATE bot_counters 
                        SET current_value = 0, reset_at = NOW() + INTERVAL '24 hours' 
                        WHERE counter_name = 'sub_verified_24h';
                    """)
                
                # جلب القيمة الصافية للعداد الرقمي المستقل
                joined_last_24h = await conn.fetchval("""
                    SELECT current_value FROM bot_counters WHERE counter_name = 'sub_verified_24h'
                """)

        stats_reply = (
            "📢 **إحصائيات الاشتراك الإجبارية الحالية:**\n"
            "--------------------------------------\n"
            f"📌 اسم القناة: **{channel_title}**\n"
            f"🆔 معرف القناة الرقمي: `{required_channel}`\n"
            "--------------------------------------\n"
            f"👥 العدد الحالي منذ آخر تصفير تلقائي: **{joined_last_24h:,}** عضو ✨"
        )
        await update.message.reply_text(stats_reply, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل جلب الإحصائيات: {e}")


# ==============================================================================
# ⏰ وظيفة الإرسال التلقائي والدوري كل 24 ساعة (Automated Daily Report)
# ==============================================================================

async def send_daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    """الوظيفة المجدولة التي تنطلق تلقائياً لإرسال الإحصائيات وتصفير العداد"""
    pool = context.bot_data.get('db_conn')
    required_channel = context.bot_data.get("required_channel_id")
    
    if not pool or ADMIN_USER_ID == 0:
        return

    try:
        channel_title = "القناة المشتركة"
        if required_channel:
            try:
                chat_info = await context.bot.get_chat(required_channel)
                channel_title = chat_info.title or "القناة المشتركة"
            except:
                pass

        async with pool.acquire() as conn:
            # جلب العدد الأخير المتوفر قبل التصفير
            joined_today = await conn.fetchval("""
                SELECT current_value FROM bot_counters WHERE counter_name = 'sub_verified_24h'
            """)
            if joined_today is None:
                joined_today = 0

            # تصفير العداد لليوم الجديد فوراً وتحديث وقت التصفير القادم
            await conn.execute("""
                UPDATE bot_counters 
                SET current_value = 0, reset_at = NOW() + INTERVAL '24 hours' 
                WHERE counter_name = 'sub_verified_24h';
            """)

        # إرسال التقرير النهائي لك مباشرة
        report_text = (
            "📊 **التقرير اليومي التلقائي للإشتراك الإجباري:**\n"
            "--------------------------------------\n"
            f"📌 اسم القناة: **{channel_title}**\n"
            "--------------------------------------\n"
            f"👥 عدد الأعضاء الكلي الذين انضموا اليوم: **{joined_today:,}** عضو جديد ✨\n\n"
            "🔄 تم تصفير العداد بنجاح وبدء الحساب لليوم الجديد تلقائياً."
        )
        
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=report_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error executing daily report job: {e}")


# ==============================================================================
# 🔌 ربط وتسجيل المعالجات (Handlers Registration)
# ==============================================================================

def register_admin_handlers(application, original_start_handler):
    """ربط كافة الأوامر الإدارية وجدولة وظيفة التقرير اليومي"""
    application.add_handler(CommandHandler("admin", admin_panel))  
    application.add_handler(CommandHandler("set_premium", set_premium))  
    application.add_handler(CommandHandler("rem_premium", remove_premium))  
    application.add_handler(CommandHandler("ban", ban_user))  
    application.add_handler(CommandHandler("unban", unban_user))  
    application.add_handler(CommandHandler("broadcast", admin_broadcast))  
    application.add_handler(CommandHandler("setchannel", set_channel))
    application.add_handler(CommandHandler("channel_stats", channel_stats))

    # ⏳ تفعيل الجدولة اليومية التلقائية عبر الـ Job Queue الخاص بالبوت
    if application.job_queue:
        # التقرير سيرسل لك يومياً الساعة 11:55 مساءً بتوقيت مكة المكرمة/العراق (Asia/Baghdad)
        target_timezone = pytz.timezone("Asia/Baghdad")
        report_time = time(hour=23, minute=55, second=0, tzinfo=target_timezone)
        
        application.job_queue.run_daily(
            send_daily_report_job,
            time=report_time,
            name="daily_subscription_report"
        )
        logger.info("✅ Daily subscription report job successfully scheduled at 23:55 Baghdad time.")
