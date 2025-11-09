import os
import google.genai as genai
from google.genai.types import GenerateContentConfig

# جلب مفتاح Gemini من متغير البيئة
API_KEY = os.getenv("GEMINI_API_KEY")

# تهيئة العميل
client = genai.Client(api_key=API_KEY)

# 🧠 البحث الذكي عن كتاب من خلال الوصف أو الكلمات المفتاحية
def ai_search(description: str) -> str:
    """
    يقوم هذا الذكاء الاصطناعي بتحليل وصف المستخدم أو فكرته عن الكتاب
    ثم يحاول اقتراح كتاب أو أكثر بناءً على المعنى.
    """
    prompt = f"""
    أنت مساعد ذكي في مكتبة إلكترونية.
    المستخدم كتب وصفًا عن كتاب يبحث عنه:
    "{description}"

    ابحث بناءً على المعنى وليس الاسم فقط.
    إذا لم يكن متاحًا الكتاب المطلوب، اقترح كتبًا مشابهة.
    اكتب الرد بالعربية، ويشمل:
    - اسم الكتاب
    - المؤلف
    - وصف مختصر
    - سبب الترشيح
    """
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=GenerateContentConfig(max_output_tokens=400),
        )
        return response.text.strip()
    except Exception as e:
        return f"⚠️ حدث خطأ أثناء البحث الذكي: {e}"


# 📚 اقتراح كتب حسب مجال معين
def ai_suggest_books(field: str) -> str:
    """
    يقترح ٥ كتب بناءً على المجال المطلوب.
    """
    prompt = f"""
    اقترح 5 كتب شهيرة ومميزة في مجال "{field}".
    يجب أن يكون الرد منسقًا هكذا:
    1. اسم الكتاب – المؤلف – وصف مختصر
    2. ...
    اكتب بالعربية فقط.
    """
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=GenerateContentConfig(max_output_tokens=500),
        )
        return response.text.strip()
    except Exception as e:
        return f"⚠️ حدث خطأ أثناء اقتراح الكتب: {e}"
