import os
import logging
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware

# استيراد كائن الـ FastAPI الرئيسي من الملف الأساسي لضمان العمل على نفس المنفذ (Port)
from main import web_app

logger = logging.getLogger(__name__)

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
    logger.info("📡 تم ربط خادم الويب بمحرك البوت بنجاح.")

# ===============================================
# مسارات الـ API والواجهة المكتبية الذكية
# ===============================================

@web_app.get("/miniapp")
async def get_miniapp():
    """بث واجهة الويب الفاخرة المحدثة index.html"""
    file_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            import fastapi.responses
            return fastapi.responses.HTMLResponse(content=file.read())
    return fastapi.responses.HTMLResponse(content="<h3>عذراً، لم يتم العثور على ملف الواجهة index.html في مجلد المشروع!</h3>", status_code=404)


@web_app.get("/api/search")
async def api_search(query: str = Query(..., min_length=2)):
    """محرك بحث حي فوري يستعلم من قاعدة البيانات ويعيد النتيجة للواجهة مباشرة"""
    if bot_application is None:
        return {"success": False, "message": "السيرفر قيد التهيئة، يرجى الانتظار..."}
        
    pool = bot_application.bot_data.get("db_conn")
    if not pool:
        return {"success": False, "message": "قاعدة البيانات غير متصلة حالياً"}
    
    try:
        async with pool.acquire() as conn:
            # استخدام نفس منطق الفهارس الثلاثية (Trgm) لضمان السرعة الفائقة
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
    """جلب الكتب الأكثر تحميلاً بناءً على جدول الإحصائيات الأسبوعي"""
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
            # خطة بديلة عرض 15 كتاب عشوائي إذا كانت الإحصائيات الأسبوعية فارغة في البداية
            if not rows:
                rows = await conn.fetch("SELECT file_id, file_name FROM books LIMIT 15;")
            
            return {"success": True, "results": [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]}
    except Exception as e:
        logger.error(f"⚠️ خطأ في جلب الملفات الأكثر تحميلاً: {e}")
        return {"success": False, "results": []}
