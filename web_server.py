import os
import logging
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# إنشاء كائن الـ FastAPI بشكل مستقل تماماً لكسر حلقة الاستيراد الدائري
web_app = FastAPI(title="Knowledge Library Live API Engine")

# تفعيل الـ CORS للسماح بالاتصال الآمن والمباشر بين واجهة الـ HTML والسيرفر الخلفي
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مرجع ديناميكي لكائن الـ Application الخاص بـ تيليجرام لتبادل البيانات ومنع الـ Circular Import
bot_application = None

def init_web_server(app):
    """ربط كائن البوت الرئيسي بخادم الويب عند الإقلاع للوصول لقاعدة البيانات"""
    global bot_application
    bot_application = app
    logger.info("📡 تم ربط خادم الويب بمحرك البوت بنجاح وتم تفعيل قنوات الاتصال.")

# =========================================================================
# 🛠️ نظام الفحص المنفصل والاستباقي (Pre-flight Access Control System)
# =========================================================================

async def enforce_strict_limits(user_id: int):
    """دالة داخلية مركزية لفرض القيود وقطع الاتصال فوراً برمي استثناء 403 لو رُفض المستخدم"""
    if bot_application is None:
        raise HTTPException(status_code=503, detail="السيرفر قيد التهيئة وتمرير البيانات...")
        
    # استدعاء دالة الفحص الذكية الحقيقية من ملفك الرئيسي (main.py)
    if hasattr(bot_application, "check_user_limits"):
        allowed, reason = await bot_application.check_user_limits(user_id=user_id)
        if not allowed:
            # قطع العملية فوراً وإرجاع استجابة حظر صريحة (403) تمنع المتصفح من العرض
            raise HTTPException(status_code=403, detail=reason)
    return True

@web_app.get("/api/check-access")
async def api_check_access(user_id: int):
    """مسار منفصل تماماً يستدعيه الـ Mini App قبل أي خطوة أو ضغطة للتأكد من اشتراك الحساب"""
    await enforce_strict_limits(user_id)
    return {"success": True, "status": "access_granted", "message": "تم التحقق، الحساب نشط وملتزم بالشروط."}

# =========================================================================
# 📡 مسارات الـ API والواجهة المكتبية المحمية
# =========================================================================

@web_app.get("/miniapp")
async def get_miniapp():
    """بث واجهة الويب الفاخرة index.html عند طلبها من تيليجرام"""
    file_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            import fastapi.responses
            return fastapi.responses.HTMLResponse(content=file.read())
    return fastapi.responses.HTMLResponse(content="<h3>عذراً، لم يتم العثور على ملف الواجهة index.html في مجلد المشروع!</h3>", status_code=404)


@web_app.get("/api/search")
async def api_search(user_id: int, query: str = Query(..., min_length=2)):
    """محرك بحث فوري مشروط ومحمي بفحص الهوية والاشتراك قبل استعلام قاعدة البيانات"""
    # تفعيل نظام الفحص الاستباقي للبحث أيضاً لمنع أي محاولة تخطي بالرابط المباشر
    await enforce_strict_limits(user_id)
        
    pool = bot_application.bot_data.get("db_conn")
    if not pool:
        return {"success": False, "message": "قاعدة البيانات غير متصلة حالياً"}
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT file_id, file_name 
                FROM books 
                WHERE file_name ILIKE $1 
                LIMIT 25;
            """, f"%{query}%")
            
            results = [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]
            return {"success": True, "results": results}
    except Exception as e:
        logger.error(f"⚠️ خطأ في البحث عبر الـ API: {e}")
        return {"success": False, "message": "حدث خطأ أثناء فحص الرفوف الرقمية"}


@web_app.get("/api/trending")
async def api_trending():
    """جلب الكتب الأكثر تحميلاً (متاح للجميع كعرض واجهة أولي)"""
    if bot_application is None:
        return {"success": False, "results": []}
        
    pool = bot_application.bot_data.get("db_conn")
    if not pool: 
        return {"success": False, "results": []}
        
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT b.file_id, b.file_name, COUNT(s.id) as downloads
                FROM books b
                JOIN download_stats s ON b.file_id = s.file_id
                WHERE s.downloaded_at > NOW() - INTERVAL '7 days'
                GROUP BY b.file_id, b.file_name
                ORDER BY downloads DESC LIMIT 15;
            """)
            if not rows:
                rows = await conn.fetch("SELECT file_id, file_name FROM books LIMIT 15;")
            
            return {"success": True, "results": [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]}
    except Exception as e:
        logger.error(f"⚠️ خطأ في جلب الملفات الأكثر تحميلاً: {e}")
        return {"success": False, "results": []}


@web_app.get("/api/download")
async def api_download(file_id: str, user_id: int):
    """إرسال ملف الكتاب مباشرة إلى شات المستخدم بعد فرض قيود الاشتراك والإحالات بصرامة قطعية"""
    # إجبار الفحص الصارم؛ لو رُفض المستخدم ينقطع التنفيذ هنا فوراً عبر الـ HTTPException
    await enforce_strict_limits(user_id)
            
    pool = bot_application.bot_data.get("db_conn")
    
    try:
        # إرسال المستند مباشرة إلى شات المستخدم عبر كائن البوت المستقر بالخلفية
        await bot_application.bot.send_document(
            chat_id=user_id,
            document=file_id,
            caption="📖 تم جلب كتابك بنجاح من واجهة مكتبة المعرفة الذكية."
        )
        
        # تسجيل عملية التحميل لدعم خوارزمية التريند
        if pool:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO download_stats(file_id) VALUES($1)", file_id)
                
        return {"success": True, "message": "تم إرسال الكتاب إلى حسابك بنجاح!"}
    except Exception as e:
        error_msg = str(e)
        if "forbidden" in error_msg.lower() or "chat not found" in error_msg.lower():
            raise HTTPException(status_code=403, detail="⚠️ عذراً، يجب عليك تفعيل البوت والاشتراك في القناة أولاً لتفادي شروط قيود التحميل.")
            
        logger.error(f"⚠️ خطأ أثناء إرسال الملف المستقل عبر الـ API: {e}")
        raise HTTPException(status_code=500, detail="فشل إرسال الملف. تأكد من أنك قمت بعمل /start للبوت مسبقاً.")
