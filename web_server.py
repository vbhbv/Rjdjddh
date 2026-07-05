import os
import logging
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

# إنشاء تطبيق FastAPI
web_app = FastAPI(title="Knowledge Library Dynamic API")

# تفعيل الـ CORS للسماح بالاتصال الآمن بين الواجهة والسيرفر
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مرجع ديناميكي لـ Application الخاص بـ تيليجرام لنتفادى الـ Circular Import
bot_application = None

def init_web_server(app):
    """ربط كائن البوت الرئيسي بخادم الويب عند الإقلاع"""
    global bot_application
    bot_application = app

# ===============================================
# مسارات الـ API للواجهة المكتبية
# ===============================================
@web_app.get("/miniapp", response_class=HTMLResponse)
async def get_miniapp():
    """بث واجهة الويب الفاخرة index.html"""
    file_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    return "<h3>عذراً، لم يتم العثور على ملف الواجهة index.html</h3>"


@web_app.get("/api/search")
async def api_search(query: str = Query(..., min_length=2)):
    """محرك البحث الحي المرتبط مباشرة بقاعدة بيانات البوت دون إغلاق الواجهة"""
    if bot_application is None:
        return {"success": False, "message": "Server initializing..."}
        
    pool = bot_application.bot_data.get("db_conn")
    if not pool:
        return {"success": False, "message": "Database pool not ready"}
    
    try:
        async with pool.acquire() as conn:
            # استخدام عنونة ILIKE السريعة المتوافقة مع فهارس الـ Trgm لديك
            rows = await conn.fetch("""
                SELECT file_id, file_name 
                FROM books 
                WHERE file_name ILIKE $1 
                LIMIT 20;
            """, f"%{query}%")
            
            results = [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]
            return {"success": True, "results": results}
    except Exception as e:
        logger.error(f"API Live Search Error: {e}")
        return {"success": False, "message": str(e)}


@web_app.get("/api/trending")
async def api_trending():
    """جلب الكتب الأكثر تحميلاً ديناميكياً للواجهة"""
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
                ORDER BY downloads DESC LIMIT 10;
            """)
            if not rows:
                rows = await conn.fetch("SELECT file_id, file_name FROM books LIMIT 10;")
            
            return {"success": True, "results": [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]}
    except:
        return {"success": False, "results": []}
