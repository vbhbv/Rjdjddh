import os
import logging
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

web_app = FastAPI(title="Knowledge Library Live API Engine")

web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مرجع ديناميكي لكائن الـ Application المتصل بـ main.py
bot_application = None

def init_web_server(app):
    global bot_application
    bot_application = app
    logger.info("📡 تم ربط خادم الويب بمحرك البوت بنجاح.")

# =========================================================================
# 🛠️ نظام الفحص المنفصل والاستباقي المربوط بمعرف القناة الثابت
# =========================================================================

@web_app.get("/api/check-access")
async def api_check_access(user_id: int):
    """يفحص الاشتراك ويجلب رابط القناة iiollr ديناميكياً من السيرفر"""
    
    # بناء رابط القناة المطلوب مباشرة
    channel_url = "https://t.me/iiollr"

    # استدعاء دالة الفحص الفعلي للاشتراك إذا كان محرك البوت متصلاً
    if bot_application and hasattr(bot_application, "check_user_limits"):
        allowed, reason = await bot_application.check_user_limits(user_id=user_id)
        if not allowed:
            # نرسل كود 403 ومعه رابط القناة لكي تفتح الواجهة عليه فوراً
            raise HTTPException(
                status_code=403, 
                detail={"message": reason, "channel_url": channel_url}
            )
            
    return {"success": True, "status": "access_granted", "channel_url": channel_url}

# =========================================================================
# 📡 باقي المسارات المحمية
# =========================================================================

@web_app.get("/miniapp")
async def get_miniapp():
    file_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            import fastapi.responses
            return fastapi.responses.HTMLResponse(content=file.read())
    return fastapi.responses.HTMLResponse(content="<h3>خطأ في ملف الواجهة</h3>", status_code=404)

@web_app.get("/api/search")
async def api_search(user_id: int, query: str = Query(..., min_length=2)):
    if bot_application and hasattr(bot_application, "check_user_limits"):
        allowed, _ = await bot_application.check_user_limits(user_id=user_id)
        if not allowed: raise HTTPException(status_code=403, detail="مرفوض")
        
    pool = bot_application.bot_data.get("db_conn") if bot_application else None
    if not pool: return {"success": False, "message": "قاعدة البيانات غير متصلة"}
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT file_id, file_name FROM books WHERE file_name ILIKE $1 LIMIT 25;", f"%{query}%")
            return {"success": True, "results": [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]}
    except Exception as e:
        return {"success": False, "message": "خطأ في البحث"}

@web_app.get("/api/download")
async def api_download(file_id: str, user_id: int):
    if bot_application and hasattr(bot_application, "check_user_limits"):
        allowed, _ = await bot_application.check_user_limits(user_id=user_id)
        if not allowed: raise HTTPException(status_code=403, detail="مرفوض")
            
    try:
        await bot_application.bot.send_document(chat_id=user_id, document=file_id, caption="📖 تم جلب كتابك بنجاح.")
        return {"success": True, "message": "تم إرسال الكتاب!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="فشل إرسال الملف.")
