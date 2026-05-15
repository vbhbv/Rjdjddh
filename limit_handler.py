import logging
from datetime import datetime

# إعداد اللوج لتتبع العمليات
logger = logging.getLogger(__name__)

# الإعدادات العامة
DAILY_SEARCH_LIMIT = 10  # حد البحث اليومي للمستخدمين المجانيين

async def check_search_limit(user_id: int, conn) -> bool:
    """
    الدالة المسؤولة عن فحص صلاحية البحث للمستخدم:
    1. تتحقق من العضوية المميزة (Premium).
    2. إذا لم يكن مميزاً، تطبق حد الـ 10 عمليات بحث يومياً.
    """
    try:
        # أولاً: جلب حالة اشتراك المستخدم من جدول users
        # سنفترض وجود أعمدة is_premium و premium_expiry
        user_data = await conn.fetchrow(
            "SELECT is_premium, premium_expiry FROM users WHERE user_id = $1", 
            user_id
        )

        # التحقق من العضوية المميزة
        if user_data and user_data['is_premium']:
            expiry = user_data['premium_expiry']
            # إذا كان الاشتراك لا يزال سارياً (تاريخ الانتهاء أكبر من الوقت الحالي)
            if expiry and expiry > datetime.now():
                return True
            else:
                # إذا انتهى الاشتراك، نقوم بتحديث حالته في قاعدة البيانات إلى مجاني
                await conn.execute(
                    "UPDATE users SET is_premium = FALSE WHERE user_id = $1", 
                    user_id
                )
                logger.info(f"User {user_id} premium subscription expired.")

        # ثانياً: إذا كان المستخدم مجانياً، نطبق نظام العداد اليومي
        today = datetime.now().date()
        
        # التأكد من وجود جدول سجلات البحث (للمستخدمين المجانيين)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS search_logs (
                user_id BIGINT,
                search_date DATE,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, search_date)
            );
        """)

        # جلب عدد عمليات البحث التي قام بها المستخدم اليوم
        count = await conn.fetchval(
            "SELECT count FROM search_logs WHERE user_id = $1 AND search_date = $2",
            user_id, today
        )

        # إذا وصل للحد الأقصى (10)
        if count is not None and count >= DAILY_SEARCH_LIMIT:
            return False

        # إذا لم يصل للحد، نقوم بزيادة العداد (أو إنشاء سجل جديد لليوم)
        await conn.execute("""
            INSERT INTO search_logs (user_id, search_date, count)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, search_date)
            DO UPDATE SET count = search_logs.count + 1;
        """, user_id, today)
        
        return True

    except Exception as e:
        logger.error(f"⚠️ خطأ في فحص قيود البحث للمستخدم {user_id}: {e}")
        # في حال حدوث خطأ تقني، نفضل السماح بالبحث لضمان استمرارية الخدمة
        return True
