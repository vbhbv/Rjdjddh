import os
import logging
import asyncpg
import easyocr
import cv2
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

# متغير عام لحفظ حوض الاتصال المشترك
db_pool = None
reader = None

async def init_db_pool(existing_pool=None):
    """تهيئة حوض الاتصال بقاعدة البيانات ومحرك الـ OCR"""
    global db_pool, reader
    
    # 1. ربط حوض الاتصال القادم من الملف الرئيسي أو إنشائه من البيئة
    if existing_pool:
        db_pool = existing_pool
        logger.info("✅ [OCR Engine] Shared DB pool attached successfully.")
    else:
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            try:
                db_pool = await asyncpg.create_pool(dsn=db_url, min_size=1, max_size=5)
                logger.info("✅ [OCR Engine] DB pool created from DATABASE_URL.")
            except Exception as e:
                logger.error(f"❌ [OCR Engine] Failed to create DB pool from URL: {e}")
        else:
            logger.error("🚨 [OCR Engine] DATABASE_URL environment variable is missing.")

    # 2. تهيئة محرك القراءة ذكياً إذا لم يكن مهيأً سابقاً
    if reader is None:
        logger.info("⏳ [OCR Engine] Loading EasyOCR models (Arabic & English)...")
        reader = easyocr.Reader(['ar', 'en'], gpu=False)
        logger.info("✅ [OCR Engine] EasyOCR models loaded successfully.")
    
    return db_pool

async def async_db_search(search_queries, limit_candidates=60):
    """البحث في قاعدة البيانات السحابية باستخدام العبارات المستخرجة من الغلاف"""
    global db_pool
    if db_pool is None:
        await init_db_pool()
        if db_pool is None:
            logger.error("❌ [OCR Engine] Cannot search, DB pool is completely unavailable.")
            return []

    candidates = []
    # تنظيف العبارات وتجهيزها للبحث
    clean_queries = [q.strip() for q in search_queries if len(q.strip()) > 2]
    if not clean_queries:
        return []

    async with db_pool.acquire() as conn:
        for query in clean_queries:
            try:
                # البحث باستخدام نظام التشابه النصي والـ Trigram المدعوم في السيرفر
                rows = await conn.fetch("""
                    SELECT file_id, file_name,
                           similarity(file_name, $1) as sim
                    FROM books
                    WHERE file_name % $1 OR to_tsvector('arabic', file_name) @@ plainto_tsquery('arabic', $1)
                    ORDER BY sim DESC
                    LIMIT $2
                """, query, limit_candidates)
                
                for row in rows:
                    candidates.append({
                        "file_id": row["file_id"],
                        "file_name": row["file_name"],
                        "similarity": row["sim"] or 0.0
                    })
            except Exception as e:
                logger.error(f"❌ [OCR Engine] Database query error for '{query}': {e}")
                
    # إزالة التكرار بناءً على الـ file_id
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c["file_id"] not in seen:
            seen.add(c["file_id"])
            unique_candidates.append(c)
            
    return unique_candidates

async def telegram_photo_handler_pipeline(image_path: str) -> dict:
    """خط المعالجة الكامل لقراءة الغلاف والبحث ومطابقته"""
    global reader
    if reader is None:
        await init_db_pool()

    if not os.path.exists(image_path):
        return {"status": "error", "message": "❌ لم يتم العثور على ملف الصورة على السيرفر."}

    try:
        # 1. تحسين الصورة برمجياً لرفع دقة القراءة (Image Preprocessing)
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # تطبيق تقنية CLAHE لتوضيح النصوص الباهتة والمتباينة والإضاءة الضعيفة
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_img = clahe.apply(gray)
        
        # حفظ الصورة المعالجة مؤقتاً لقراءتها
        processed_path = image_path + "_enhanced.jpg"
        cv2.imwrite(processed_path, enhanced_img)
        
        # 2. استخراج النصوص عبر الـ OCR
        results = reader.readtext(processed_path, detail=0)
        
        # تنظيف الملف المؤقت فوراً
        if os.path.exists(processed_path):
            os.remove(processed_path)
            
        if not results:
            return {"status": "no_text", "message": "🧐 لم يتمكن البوت من قراءة أي نصوص واضحة على هذا الغلاف. يرجى تصوير الكتاب بزاوية وإضاءة أفضل."}

        # 3. صياغة عبارات بحث ذكية مستهدفة
        full_text = " ".join(results).replace("\n", " ").strip()
        search_queries = [full_text]
        
        # إضافة الكلمات الطويلة كعبارات فرعية لزيادة احتمالية المطابقة
        filtered_results = [res for res in results if len(res.strip()) > 3]
        if filtered_results:
            search_queries.append(" ".join(filtered_results[:3]))
            search_queries.extend(filtered_results[:2])

        logger.info(f"🚀 [OCR Engine] Extracted search queries: {search_queries}")

        # 4. البحث المباشر في قاعدة البيانات السحابية الحية
        candidates = await async_db_search(search_queries, limit_candidates=60)
        if not candidates:
            return {"status": "not_found", "message": f"🔍 النص المقروء من الغلاف: *({full_text})*\n\nأسفرت نتائج البحث عن عدم توفر هذا الكتاب حالياً في قاعدة البيانات."}

        # 5. الفرز والمطابقة الفائقة عبر RapidFuzz (Fuzzy Matching)
        choices = {c["file_id"]: c["file_name"] for c in candidates}
        best_matches = process.extract(
            full_text, 
            choices, 
            scorer=fuzz.token_set_ratio, 
            limit=3
        )

        if best_matches:
            best_match_id, score, _ = best_matches[0]
            matched_name = choices[best_match_id]
            
            logger.info(f"🎯 [OCR Match] Best Match: {matched_name} with Score: {score}")

            if score >= 70:
                return {
                    "status": "exact_match",
                    "message": "🎯 **تم العثور على الكتاب بنجاح عبر قراءة الغلاف الإلكتروني!**",
                    "book": {"title": matched_name, "author": "مستخرج من قاعدة البيانات", "file_id": best_match_id}
                }
            elif score >= 45:
                return {
                    "status": "suggestion",
                    "message": "💡 **لم نجد تطابقاً تاماً بنسبة 100%، ولكن إليك أقرب كتاب متوفر للغلاف:**",
                    "book": {"title": matched_name, "author": "العنوان المقارب في المكتبة", "file_id": best_match_id}
                }

        return {"status": "not_found", "message": f"🔍 النص المقروء: *({full_text})*\n\nلم يتم العثور على تطابق كافٍ داخل المكتبة."}

    except Exception as e:
        logger.error(f"❌ Exception in pipeline: {e}", exc_info=True)
        return {"status": "error", "message": f"❌ حدث خطأ داخلي أثناء تشغيل محرك المعالجة: {str(e)}"}
