import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List
import difflib

# -----------------------------
# إعدادات
# -----------------------------
BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = text.replace("ـ", "")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "ه"]
    for suf in suffixes:
        if word.endswith(suf) and len(word) > len(suf) + 2:
            word = word[:-len(suf)]
            break
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    return word if word else ""

def expand_keywords_with_synonyms(keywords: List[str], synonyms: dict) -> List[str]:
    expanded = set(keywords)
    for k in keywords:
        if k in synonyms:
            expanded.update(synonyms[k])
    return list(expanded)

# -----------------------------
# إرسال اقتراحات البحث
# -----------------------------
async def send_search_suggestions(update, context: ContextTypes.DEFAULT_TYPE, query: str, books_list: List[dict], synonyms: dict):
    """
    تعرض الاقتراحات عندما لا توجد نتائج مباشرة للبحث
    """
    normalized_query = normalize_text(query)
    query_words = [w for w in normalized_query.split() if w not in ARABIC_STOP_WORDS]
    stemmed_query = [light_stem(w) for w in query_words]
    
    # جمع كل أسماء الكتب الموجودة مسبقاً
    all_titles = [b["file_name"] for b in books_list]
    
    # اقتراحات بناء على تشابه نصي بسيط
    suggestions = difflib.get_close_matches(normalized_query, all_titles, n=5, cutoff=0.5)
    
    # لو لا توجد اقتراحات دقيقة، نبحث في الكلمات المفتاحية والمرادفات
    if not suggestions:
        expanded = expand_keywords_with_synonyms(stemmed_query, synonyms)
        for b in books_list:
            title_norm = normalize_text(b["file_name"])
            if any(word in title_norm for word in expanded):
                suggestions.append(b["file_name"])
    
    # إذا لا توجد اقتراحات على الإطلاق
    if not suggestions:
        await update.message.reply_text(f"❌ لا توجد كتب مطابقة للبحث: {query}\nحاول تعديل الكلمات أو تجربة كلمات مفتاحية أخرى.")
        return
    
    # تجهيز لوحة المفاتيح للأزرار
    keyboard = []
    for title in suggestions:
        # البحث عن file_id للكتاب
        file_id = None
        for b in books_list:
            if b["file_name"] == title:
                file_id = b.get("file_id")
                break
        if file_id:
            key = hashlib.md5(file_id.encode()).hexdigest()[:16]
            context.bot_data[f"file_{key}"] = file_id
            keyboard.append([InlineKeyboardButton(title, callback_data=f"file:{key}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"🔍 لم نعثر على نتائج مطابقة للبحث '{query}'، لكن هذه بعض الاقتراحات:", reply_markup=reply_markup)
