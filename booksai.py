# ===============================================
# ملف: booksai.py
# الذكاء الاصطناعي المساعد للبحث في الكتب
# ===============================================

import os
import re
from google import genai
from google.genai import types

# ==========================================================
# إعداد Gemini AI
# ==========================================================
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("🚨 المتغير GEMINI_API_KEY غير موجود في البيئة.")

client = genai.Client(api_key=API_KEY)

# ==========================================================
# 🔍 دالة البحث الذكي عبر الذكاء الاصطناعي
# ==========================================================
async def search_by_story_or_description(user_query: str, books: list) -> list:
    """
    يبحث عن الكتاب الأكثر تطابقًا مع وصف المستخدم أو قصته.
    """
    if not books:
        return []

    # نبني قائمة الكتب بصيغة واضحة للذكاء الاصطناعي
    books_text = "\n".join(
        [f"{b['id']}: {b['file_name']}" for b in books]
    )

    prompt = f"""
    المستخدم كتب وصفًا لكتاب يريد إيجاده:
    "{user_query}"

    هذه قائمة من الكتب في المكتبة:
    {books_text}

    اختر الكتب التي تتحدث عن ما وصفه المستخدم أكثر.
    أعد فقط أرقام الكتب (id) المناسبة مفصولة بفواصل، بدون كلام إضافي.
    """

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        ids_text = response.text.strip()
        matched_ids = re.findall(r"\d+", ids_text)
        matched_ids = [int(i) for i in matched_ids if i.isdigit()]
        return [b for b in books if b["id"] in matched_ids]
    except Exception as e:
        print(f"❌ خطأ في البحث بالذكاء الاصطناعي: {e}")
        return []

# ==========================================================
# 📘 إنشاء وصف مختصر للكتاب
# ==========================================================
async def generate_book_description(book_title: str) -> str:
    """
    ينشئ وصفًا مختصرًا للكتاب بناءً على عنوانه.
    """
    try:
        prompt = f"""
        أعطني وصفًا أدبيًا جميلًا وموجزًا (3 أسطر فقط)
        لكتاب بعنوان "{book_title}" دون استخدام كلمات مثل "يبدو" أو "ربما".
        """
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ خطأ في توليد وصف الكتاب: {e}")
        return "📘 كتاب مميز من مكتبتنا الإلكترونية."

# ==========================================================
# 🤖 اقتراح كتب مشابهة من نفس المجال أو المؤلف
# ==========================================================
async def suggest_related_books(user_preference: str, books: list) -> list:
    """
    يقترح 5 كتب من نفس المجال أو المؤلف.
    """
    if not books:
        return []

    books_text = "\n".join(
        [f"{b['id']}: {b['file_name']}" for b in books]
    )

    prompt = f"""
    المستخدم يريد اقتراح كتب في مجال "{user_preference}".
    إليك قائمة الكتب:
    {books_text}

    اختر أفضل 5 كتب تناسب ما طلبه المستخدم.
    أعد فقط أرقام الكتب (id) بدون أي نص آخر.
    """

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        ids_text = response.text.strip()
        matched_ids = re.findall(r"\d+", ids_text)
        matched_ids = [int(i) for i in matched_ids if i.isdigit()]
        return [b for b in books if b["id"] in matched_ids][:5]
    except Exception as e:
        print(f"⚠️ خطأ في اقتراح الكتب: {e}")
        return books[:5]

# ==========================================================
# 🧩 توافق مع النسخ القديمة
# ==========================================================
ai_search = search_by_story_or_description
ai_suggest_books = suggest_related_books
