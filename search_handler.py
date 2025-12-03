import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os
from datetime import datetime

BOOKS_PER_PAGE = 10

# -----------------------------
# إعدادات المشرف
# -----------------------------
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    return text

COMMON_WORDS = {"كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"}

def remove_common_words(text: str) -> str:
    if not text:
        return ""
    words = text.split()
    filtered = [w for w in words if w not in COMMON_WORDS]
    return " ".join(filtered).strip()

def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

# -----------------------------
# تقشير بسيط للكلمات (light stemming)
# -----------------------------
def light_stem(word: str) -> str:
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين"]
    for suf in suffixes:
        if word.endswith(suf):
            word = word[:-len(suf)]
            break
    if word.startswith("ال"):
        word = word[2:]
    return word

# -----------------------------
# دالة التقييم الوزني
# -----------------------------
def calculate_score(book: Dict[str, Any], keywords: List[str], normalized_query: str) -> int:
    score = 0
    book_name = normalize_text(book.get('file_name', ''))
    
    # التطابق الحرفي الكامل
    if normalized_query == book_name:
        score += 50
    elif normalized_query in book_name:
        score += 20

    # تطبيق light_stem مرة واحدة لكل كلمة
    stemmed_keywords = [light_stem(k) for k in keywords]
    title_words = book_name.split()
    stemmed_title = [light_stem(t) for t in title_words]

    for k_stem in stemmed_keywords:
        for t_stem in stemmed_title:
            if t_stem.startswith(k_stem):
                score += 10
            elif k_stem in t_stem:
                score += 8
    return score

# -----------------------------
# إشعار المشرف بعد كل بحث
# -----------------------------
async def notify_admin_search(context: ContextTypes.DEFAULT_TYPE, username: str, query: str, found: bool, results_count: int):
    if ADMIN_USER_ID == 0:
        return
    bot = context.bot
    status_text = "✅ تم العثور على نتائج" if found else "❌ لم يتم العثور على نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"🔔 قام المستخدم {username_text} بالبحث عن:\n`{query}`\nالحالة: {status_text}\nعدد النتائج: {results_count}\nالوقت: {timestamp}"
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to notify admin: {e}")

# -----------------------------
# إرسال صفحة الكتب
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total_pages = max((len(books) - 1) // BOOKS_PER_PAGE + 1, 1)
    page = max(0, min(page, total_pages - 1))  # تأكد من عدم الخروج عن الحدود

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    stage_note = context.user_data.get("search_stage", "تطابق دقيق")
    if "بحث موسع" in stage_note:
        stage_note = "⚠️ نتائج بحث موسع"
    elif "تطابق جميع الكلمات" in stage_note:
        stage_note = "✅ نتائج دلالية"
    else:
        stage_note = "✅ نتائج مطابقة"

    text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(f"📘 {b['file_name']}", callback_data=f"file:{key}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
    if end < len(books):
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
