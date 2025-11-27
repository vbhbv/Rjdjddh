# search_logic.py
import asyncpg
import re
from telegram.ext import ContextTypes

# ===============================================
# دالة لتطبيع النص العربي للبحث
# ===============================================
def normalize_text(text: str) -> str:
    """
    تطبيع النص العربي:
    - تحويل الحروف إلى صغيرة
    - إزالة _ واستبدالها بمسافة
    - توحيد الألف (أ، إ، آ → ا)
    - تحويل ى إلى ي
    - تحويل الهاء والتاء المربوطة
    """
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ة", "ه")
    return text

# ===============================================
# دالة لإزالة الكلمات الشائعة "كتاب" و"رواية"
# ===============================================
def remove_common_words(text: str) -> str:
    text = re.sub(r'\b(كتاب|رواية)\b', '', text)
    return text.strip()

# ===============================================
# البحث عن الكتب الرئيسية
# ===============================================
async def get_books_by_query(query: str, context: ContextTypes.DEFAULT_TYPE):
    """
    البحث عن الكتب بحسب اسمها، مع تطبيع النص والتعامل مع كلمات مثل "كتاب" و"رواية".
    """
    conn = context.bot_data.get('db_conn')
    if not conn:
        return []

    normalized_query = normalize_text(remove_common_words(query))

    rows = await conn.fetch("""
SELECT id, file_id, file_name
FROM books
WHERE LOWER(REPLACE(
        REPLACE(REPLACE(REPLACE(REPLACE(file_name,'أ','ا'),'إ','ا'),'آ','ا'),'ى','ي'),'_',' ')
    ) LIKE '%' || $1 || '%'
ORDER BY uploaded_at DESC;
""", normalized_query)

    return rows

# ===============================================
# اقتراح كتب مشابهة عند عدم وجود نتائج
# ===============================================
async def get_similar_books(last_query: str, context: ContextTypes.DEFAULT_TYPE):
    """
    البحث عن كتب مشابهة بناءً على الكلمات الأساسية من آخر بحث للمستخدم.
    """
    conn = context.bot_data.get('db_conn')
    if not conn:
        return []

    normalized_query = normalize_text(remove_common_words(last_query))
    words = normalized_query.split()

    if not words:
        return []

    # إنشاء شرط LIKE لكل كلمة منفصلة
    like_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{w}%'" for w in words])

    query_sql = f"""
SELECT id, file_id, file_name
FROM books
WHERE {like_conditions}
ORDER BY uploaded_at DESC
LIMIT 50;
"""
    rows = await conn.fetch(query_sql)
    return rows
