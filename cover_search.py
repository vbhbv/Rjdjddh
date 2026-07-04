import os
import re
import cv2
import asyncio
import numpy as np
import easyocr
import asyncpg
from rapidfuzz import process, fuzz

# ==========================================
# 1. تهيئة المحرك لمرة واحدة عند إقلاع البوت (Singleton)
# ==========================================
print("🔄 [Initialization] جاري تهيئة محرك EasyOCR لمرة واحدة...")
# تم إنشاؤه هنا خارج الـ Handlers لضمان عدم تكرار التحميل في الذاكرة
reader = easyocr.Reader(['ar', 'en'], gpu=False) 

BOOK_STOP_WORDS = {
    "رواية", "قصة", "ديوان", "كتاب", "تأليف", "ترجمة", "إعداد", 
    "الجزء", "الأول", "الثاني", "الثالث", "المجلد", "دار", "النشر", 
    "للنشر", "التوزيع", "مؤسسة", "طبعة", "جديدة", "مزيّدة"
}

DB_CONFIG = {
    "database": "your_db",
    "user": "your_user",
    "password": "your_password",
    "host": "localhost",
    "port": 5432,
    "min_size": 10,  # الحد الأدنى للاتصالات في الـ Pool
    "max_size": 30   # الحد الأقصى للاتصالات لتفادي اختناق قاعدة البيانات
}

# كائن الـ Pool العام الذي سيتم إنشاؤه عند تشغيل البوت
db_pool = None

async def init_db_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(**DB_CONFIG)
        print("✅ [Database] تم إنشاء Connection Pool بنجاح.")

# ==========================================
# 2. تحسين معالجة الصور (Image Preprocessing)
# ==========================================
def preprocess_image_for_ocr(image_path: str) -> np.ndarray:
    """
    تحسين تباين الأغلفة (خصوصاً الداكنة) باستخدام CLAHE وإزالة الضوضاء.
    """
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # تطبيق تقنية CLAHE لزيادة التباين الموضعي دون تشويه الصورة
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    cl_img = clahe.apply(gray)
    
    # تصفية الضوضاء الخفيفة (Denoising) مع الحفاظ على حدة النصوص
    filtered_img = cv2.fastNlMeansDenoising(cl_img, None, h=3, templateWindowSize=7, searchWindowSize=21)
    
    return filtered_img

# ==========================================
# 3. تطبيع النصوص المتماثل (Symmetric Normalization)
# ==========================================
def normalize_text_production(text: str) -> str:
    """
    تنظيف وتطبيع احترافي (ملاحظة 6: يتم تطبيق نفس الدالة على نصوص الداتابيز أيضاً)
    """
    text = text.lower() # للأجزاء الإنجليزية من الغلاف
    text = re.sub(r'[\u064B-\u0652]', '', text) # إزالة التشكيل
    text = re.sub(r'ـ+', '', text) # إزالة المد
    text = re.sub(r'[أإآ]', 'ا', text) # توحيد الألفات
    
    # ملاحظة 6: تجنبنا تحويل (ة -> ه) للحفاظ على التماثل، أو نقوم بتوحيدها في الجهتين.
    # هنا تم توحيد الياء فقط
    text = re.sub(r'ى', 'ي', text) 
    
    text = re.sub(r'[^\w\s]', ' ', text)
    return " ".join(text.split())

# ==========================================
# 4. الـ OCR غير الحاجب (Non-blocking OCR)
# ==========================================
async def extract_structured_data_async(image_path: str, min_confidence: float = 0.5) -> list:
    """
    ملاحظة 4: تشغيل EasyOCR في Thread منفصل لضمان عدم حجب الـ Event Loop الخاص ببوت التليجرام.
    """
    loop = asyncio.get_running_loop()
    
    # معالجة الصورة أولاً
    processed_img = preprocess_image_for_ocr(image_path)
    
    # تشغيل عملية الـ OCR الثقيلة داخل Executor
    results = await loop.run_in_executor(None, reader.readtext, processed_img)
    
    valid_chunks = []
    for box, text, confidence in results:
        # ملاحظة 3 الأصلية: فلترة بحسب درجة الثقة
        if confidence < min_confidence:
            continue
            
        # ملاحظة 2 الأصلية: حساب المساحة بدقة للمائل والعمودي
        pts = np.array(box, dtype=np.int32)
        area = cv2.contourArea(pts)
        
        normalized_text = normalize_text_production(text)
        words = normalized_text.split()
        filtered_words = [w for w in words if w not in BOOK_STOP_WORDS]
        
        if filtered_words:
            valid_chunks.append({
                "text": " ".join(filtered_words),
                "area": area
            })
            
    # ترتيب النصوص من الأكبر حجماً للأصغر (اسم الكتاب ثم المؤلف ثم التفاصيل)
    valid_chunks = sorted(valid_chunks, key=lambda x: x["area"], reverse=True)
    return valid_chunks

# ==========================================
# 5. استراتيجية البحث المتعدد وتوليد العبارات (Multi-Query Strategy)
# ==========================================
def generate_search_queries(valid_chunks: list) -> list:
    """
    ملاحظة 10: توليد عدة احتمالات للبحث لرفع نسبة النجاح إذا فشل الدمج الكامل.
    """
    if not valid_chunks:
        return []
        
    texts = [item["text"] for item in valid_chunks]
    
    queries = []
    # 1. العبارة الكاملة المدمجة (أعلى 3 نصوص مساحة)
    queries.append(" ".join(texts[:3]))
    
    # 2. نصوص منفردة (أكبر نص، ثاني أكبر نص...)
    for t in texts[:2]:
        if t not in queries:
            queries.append(t)
            
    # 3. دمج تراجعي (الأول مع الثاني فقط)
    if len(texts) >= 2:
        combined_2 = f"{texts[0]} {texts[1]}"
        if combined_2 not in queries:
            queries.append(combined_2)
            
    return [q for q in queries if q.strip()]

# ==========================================
# 6. استعلام قاعدة البيانات غير الحاجب (Async pg_trgm)
# ==========================================
async def async_db_search(search_queries: list, limit_candidates: int = 50) -> list:
    """
    ملاحظة 1 و 3 و 7: البحث عبر الحقل الموحد المحسن الفهرس بـ GIN وبشكل Async كامل عبر الـ Pool.
    """
    global db_pool
    if not db_pool:
        await init_db_pool()
        
    # ملاحظة 7: الاعتماد على حقل البحث الموحد search_vector أو search_text (المكون من العنوان والمؤلف)
    # الاستعلام يستقبل مصفوفة عبارات ويبحث بها دفعة واحدة ANY($1) لتقليل رحلات الداتابيز
    query = """
        SELECT id, title, author, 
               (title || ' ' || title || ' ' || COALESCE(author, '')) as weighted_text
        FROM books 
        WHERE search_text % ANY($1)
        ORDER BY similarity(search_text, $2) DESC
        LIMIT $3;
    """
    
    # سنستخدم أول عبارة (وهي الأشمل) كمعيار للترتيب المبدئي في SQL
    primary_query = search_queries[0] if search_queries else ""
    
    async with db_pool.acquire() as connection:
        records = await connection.fetch(query, search_queries, primary_query, limit_candidates)
        
    # تحويل السجلات إلى قائمة قواميس عادية
    return [dict(r) for r in records]

# ==========================================
# 7. التقييم النهائي بـ RapidFuzz المحسن
# ==========================================
def get_final_match_production(search_queries: list, candidates: list):
    """
    ملاحظة 8 و 9: استخدام token_set_ratio وإعطاء وزن مضاعف للعنوان (العنوان العنوان المؤلف).
    """
    if not candidates or not search_queries:
        return None, 0
        
    choices = {c['id']: normalize_text_production(c['weighted_text']) for c in candidates}
    
    best_overall_book = None
    best_overall_score = 0
    
    # نقوم بعمل المطابقة التقريبية لكل العبارات المستخرجة ونأخذ الأعلى ثقة بينها
    for query in search_queries:
        normalized_query = normalize_text_production(query)
        
        # ملاحظة 8: الاعتماد على token_set_ratio لأنه يتجاهل الكلمات الزائدة والترتيب المبعثر للعنوان
        match = process.extractOne(
            normalized_query, 
            choices, 
            scorer=fuzz.token_set_ratio
        )
        
        if match and match[1] > best_overall_score:
            best_overall_score = match[1]
            best_overall_book = next(c for c in candidates if c['id'] == match[2])
            
    return best_overall_book, best_overall_score

# ==========================================
# 8. المتحكم الرئيسي المستدعى من البوت (Handler Entry Point)
# ==========================================
async def telegram_photo_handler_pipeline(image_path: str):
    """
    هذه الدالة هي التي يتم استدعاؤها داخل الـ Handler الخاص ببوت التليجرام الخاص بك.
    وهي آمنة تماماً (Non-blocking) وذات كفاءة فائقة.
    """
    # 1. استخراج النصوص بـ Thread منفصل (Async) مع معالجة وتصفية متقدمة
    valid_chunks = await extract_structured_data_async(image_path)
    
    if not valid_chunks:
        return "❌ لم أتمكن من قراءة أي نصوص واضحة على الغلاف، يرجى إعادة المحاولة بصورة أوضح."
        
    # 2. توليد مصفوفة العبارات الذكية (ملاحظة 10)
    search_queries = generate_search_queries(valid_chunks)
    print(f"🚀 [Engine] العبارات الناتجة للبحث المستهدف: {search_queries}")
    
    # 3. استعلام قاعدة البيانات غير الحاجب (Async Trigram Search)
    candidates = await async_db_search(search_queries, limit_candidates=60)
    
    if not candidates:
        return "😔 عذراً، لم أجد كتاباً يطابق هذا الغلاف في المكتبة حالياً."
        
    # 4. المعالجة التقريبية الموزونة بـ RapidFuzz (ملاحظة 8 و 9)
    book, score = get_final_match_production(search_queries, candidates)
    
    # 5. اتخاذ القرار النهائي بناءً على جودة النتيجة
    if score >= 88:  # تم تعديلها لـ 88 لأن token_set_ratio صارم ودقيق جداً مع الأوزان
        return {
            "status": "exact_match",
            "message": f"✅ وجدته! إليك الكتاب المطلوب فوراً:",
            "book": book
        }
    elif score >= 55:
        return {
            "status": "suggestion",
            "message": f"🤔 لم أجد تطابقاً تاماً بنسبة 100%، هل تقصد هذا الكتاب؟",
            "book": book
        }
    else:
        return "❌ لم أثق في نتائج البحث المستخرجة، يرجى كتابة اسم الكتاب نصياً."

# ==========================================
# محاكاة التشغيل (عينة اختبار)
# ==========================================
if __name__ == "__main__":
    async def test_main():
        # إنشاء الـ Pool لمرة واحدة عند التشغيل
        await init_db_pool()
        
        # محاكاة استدعاء البوت عند استقبال صورة
        result = await telegram_photo_handler_pipeline("book_cover_test.jpg")
        print("\n📥 استجابة البوت النهائية للمستخدم:\n", result)
        
        # عند إغلاق البوت نهائياً نقوم بإغلاق الـ Pool
        global db_pool
        await db_pool.close()

    # تشغيل الحلقة البرمجية للاختبار
    # asyncio.run(test_main())
