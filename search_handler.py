import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os

BOOKS_PER_PAGE = 10

# -----------------------------
# إعدادات المشرف
# -----------------------------
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))  # معرف المشرف
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    """لتطبيع النص العربي للبحث."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    """إزالة الكلمات العامة مثل كتاب/رواية/نسخة."""
    if not text:
        return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    """استخراج الكلمات المفتاحية المهمة (أطول من 3 أحرف)."""
    if not text:
        return []
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

def get_db_safe_query(normalized_query: str) -> str:
    """بناء استعلام آمن من SQL Injection البسيط."""
    return normalized_query.replace("'", "''")

# -----------------------------
# تقشير بسيط للكلمات (light stemming)
# -----------------------------
def light_stem(word: str) -> str:
    """إزالة بعض اللواحق واللاحقات الشائعة لتوحيد الجذر."""
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين"]
    for suf in suffixes:
        if word.endswith(suf):
            word = word[:-len(suf)]
            break
    if word.startswith("ال"):
        word = word[2:]
    return word

# -----------------------------
# دالة التقييم الوزني فائق الذكاء
# -----------------------------
def calculate_score(book: Dict[str, Any], keywords: List[str], normalized_query: str) -> int:
    """يحسب التقييم الوزني للكتاب بناءً على نوع ومكان المطابقة مع دعم الجذر."""
    score = 0
    book_name = normalize_text(book.get('file_name', ''))

    # التطابق الحرفي الكامل
    if normalized_query == book_name:
        score += 50
    # تطابق الجملة
    elif normalized_query in book_name:
        score += 20

    title_words = book_name.split()
    for k in keywords:
        k_stem = light_stem(k)
        for t_word in title_words:
            t_stem = light_stem(t_word)
            if t_stem.startswith(k_stem):
                score += 10
            elif k_stem in t_stem:
                score += 8
    return score

# -----------------------------
# إشعار المشرف بعد كل بحث
# -----------------------------
async def notify_admin_search(context: ContextTypes.DEFAULT_TYPE, username: str, query: str, found: bool):
    """إرسال إشعار للمشرف عن البحث الذي قام به المستخدم."""
    if ADMIN_USER_ID == 0:
        return
    bot = context.bot
    status_text = "✅ تم العثور على نتائج" if found else "❌ لم يتم العثور على نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"
    message = f"🔔 قام المستخدم {username_text} بالبحث عن:\n`{query}`\nالحالة: {status_text}"
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to notify admin: {e}")
