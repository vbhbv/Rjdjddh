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

async def _enforce_access(user_id: int, action: str):
    """
    🔧 دالة مساعدة موحّدة تستدعي check_user_limits الحقيقية المخزّنة في bot_data
    (وليس كخاصية على كائن Application نفسه، لأنه يستخدم __slots__ ولا يقبل ذلك).
    إن كانت الدالة غائبة لأي سبب، نرفض الطلب بدل السماح للجميع بالمرور
    (fail-closed بدل fail-open كما كان يحدث سابقاً).
    """
    if bot_application is None:
        raise HTTPException(status_code=503, detail={"message": "السيرفر قيد التهيئة، حاول بعد لحظات."})

    limits_checker = bot_application.bot_data.get("check_user_limits")
    if limits_checker is None:
        # 🚨 fail-closed: لو غابت الدالة لأي سبب مستقبلاً، نمنع الوصول بدل فتحه للجميع
        logger.error("🚨 check_user_limits غير موجودة في bot_data! يتم رفض الطلب احتياطاً.")
        raise HTTPException(status_code=503, detail={"message": "الخدمة غير مهيأة بشكل صحيح حالياً."})

    allowed, reason = await limits_checker(user_id=user_id, action=action)
    if not allowed:
        channel_url = "https://t.me/iiollr"
        raise HTTPException(status_code=403, detail={"message": reason, "channel_url": channel_url})


@web_app.get("/api/check-access")
async def api_check_access(user_id: int):
    """يفحص الاشتراك ويجلب رابط القناة iiollr ديناميكياً من السيرفر"""
    channel_url = "https://t.me/iiollr"
    await _enforce_access(user_id, action="check")
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
    # 🔧 action="search" — يخضع لفحص الاشتراك ولحد الـ10 عمليات بحث معاً
    await _enforce_access(user_id, action="search")

    pool = bot_application.bot_data.get("db_conn") if bot_application else None
    if not pool:
        return {"success": False, "message": "قاعدة البيانات غير متصلة"}

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT file_id, file_name FROM books WHERE file_name ILIKE $1 LIMIT 25;", f"%{query}%")
            return {"success": True, "results": [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]}
    except Exception as e:
        logger.error(f"⚠️ خطأ في البحث عبر الـ API: {e}")
        return {"success": False, "message": "خطأ في البحث"}

@web_app.get("/api/trending")
async def api_trending():
    """الأكثر تحميلاً — بلا حاجة لهوية المستخدم أو فحص اشتراك، فهي بيانات عامة فقط"""
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
    # 🔧 action="download" — يخضع فقط لفحص الاشتراك، دون حد البحث (فليس بحثاً)
    await _enforce_access(user_id, action="download")

    pool = bot_application.bot_data.get("db_conn") if bot_application else None

    try:
        await bot_application.bot.send_document(chat_id=user_id, document=file_id, caption="📖 تم جلب كتابك بنجاح.")

        if pool:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO download_stats(file_id) VALUES($1)", file_id)

        return {"success": True, "message": "تم إرسال الكتاب!"}
    except Exception as e:
        logger.error(f"⚠️ خطأ أثناء إرسال الملف عبر الـ API: {e}")
        raise HTTPException(status_code=500, detail="فشل إرسال الملف. تأكد من أنك قمت بعمل /start للبوت وتحدثت معه مسبقاً.")
