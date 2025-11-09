import os
import logging
from typing import List
from google import genai

logger = logging.getLogger(__name__)

# مفتاح الذكاء الاصطناعي
AI_API_KEY = os.getenv("AI_API_KEY")  # ضع هنا مفتاحك من استوديو Google GenAI

if not AI_API_KEY:
    logger.warning("⚠️ AI_API_KEY environment variable is not set.")

# تهيئة العميل
client = genai.Client(api_key=AI_API_KEY) if AI_API_KEY else None

async def ai_search(query: str) -> str:
    """
    البحث عن وصف الكتاب باستخدام الذكاء الاصطناعي
    """
    if not client:
        return "الوصف غير متوفر (مفتاح AI غير مهيأ)."

    try:
        response = client.generate_text(
            model="text-bison-001",
            prompt=f"اعطني وصف مفصل لهذا الكتاب: {query}",
            temperature=0.5,
            max_output_tokens=300
        )
        return response.text
    except Exception as e:
        logger.error(f"AI Search error: {e}")
        return "حدث خطأ أثناء جلب الوصف."

async def ai_suggest_books(query: str, options: List[str]) -> List[str]:
    """
    اقتراح كتب مشابهة لنفس المؤلف أو الموضوع
    """
    if not client:
        return []

    try:
        prompt = f"اقترح 5 كتب من القائمة التالية تتعلق بـ: {query}\nالخيارات: {options}"
        response = client.generate_text(
            model="text-bison-001",
            prompt=prompt,
            temperature=0.7,
            max_output_tokens=300
        )
        # تفكيك النتائج
        suggestions = [line.strip() for line in response.text.split("\n") if line.strip()]
        return suggestions[:5]
    except Exception as e:
        logger.error(f"AI Suggest error: {e}")
        return []

async def ai_search_by_keywords(keywords: str) -> str:
    """
    البحث عن الكتاب عبر وصفه أو أحداثه باستخدام الذكاء الاصطناعي
    """
    if not client:
        return "البحث الذكي غير متوفر (مفتاح AI غير مهيأ)."

    try:
        prompt = f"ابحث عن كتاب يطابق هذه الكلمات المفتاحية أو أحداث القصة: {keywords}"
        response = client.generate_text(
            model="text-bison-001",
            prompt=prompt,
            temperature=0.6,
            max_output_tokens=300
        )
        return response.text
    except Exception as e:
        logger.error(f"AI Keyword Search error: {e}")
        return "حدث خطأ أثناء البحث بالذكاء الاصطناعي."
