import hashlib
import re
from typing import List
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from search_suggestions import send_search_suggestions  # الربط بالملف الجديد
import logging

=========================

Logging

=========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

=========================

إعدادات عامة

=========================

BOOKS_PER_PAGE = 10

ARABIC_STOP_WORDS = {
"و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
"ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
"ف", "ك", "اى"
}

إعدادات المشرف

try:
ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
ADMIN_USER_ID = 0
print("⚠️ ADMIN_ID environment variable is not valid.")

=========================

دوال التطبيع والتنظيف

=========================

def normalize_text(text: str) -> str:
if not text:
return ""
text = str(text).lower()
text = text.replace("_", " ")
text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
text = text.replace("ى", "ي").replace("ة", "ه")
text = text.replace("ـ", "")
text = re.sub(r"[ًٌٍَُِ]", "", text)
text = re.sub(r'[^\w\s]', ' ', text)
text = re.sub(r'\s+', ' ', text).strip()
return text

def remove_common_words(text: str) -> str:
if not text:
return ""
for word in ["كتاب", "رواية", "نسخة", "مجموعة", "اريد", "جزء", "طبعة", "مجاني", "كبير", "صغير"]:
text = text.replace(word, "")
return text.strip()

def light_stem(word: str) -> str:
suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "ه"]
for suf in suffixes:
if word.endswith(suf) and len(word) > len(suf) + 2:
word = word[:-len(suf)]
break
if word.startswith("ال") and len(word) > 3:
word = word[2:]
return word if word else ""

=========================

المرادفات

=========================

SYNONYMS = {
"مهندس": ["هندسة", "مقاول", "معماري"],
"الهندسة": ["مهندس", "معمار", "بناء"],
"المهدي": ["المنقذ", "القائم"],
"عدمية": ["نيتشه", "موت", "عبث"],
"دين": ["إسلام", "مسيحية", "يهودية", "فقه"],
"فلسفة": ["منطق", "مفهوم", "متافيزيقا"]
}

def expand_keywords_with_synonyms(keywords: List[str]) -> List[str]:
expanded = set(keywords)
for k in keywords:
if k in SYNONYMS:
expanded.update(SYNONYMS[k])
return list(expanded)

=========================

إرسال صفحة الكتب

=========================

async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
books = context.user_data.get("search_results", [])
page = context.user_data.get("current_page", 0)
search_stage = context.user_data.get("search_stage", "تطابق دقيق")
total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

start = page * BOOKS_PER_PAGE
end = start + BOOKS_PER_PAGE
current_books = books[start:end]

if "بحث موسع" in search_stage:
stage_note = "⚠️ نتائج بحث موسع (بحثنا بالجذور والمرادفات)"
elif "تطابق جميع الكلمات" in search_stage:
stage_note = "✅ نتائج دلالية (تطابق جميع كلماتك المفتاحية)"
elif "تطابق العبارة" in search_stage:
stage_note = "🔍 تطابق العبارة الكامل"
else:
stage_note = "✅ نتائج مطابقة"

text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
keyboard = []

for b in current_books:
if not b.get("file_name") or not b.get("file_id"):
continue
key = hashlib.md5(str(b["file_id"]).encode()).hexdigest()[:16]
context.bot_data[f"file_{key}"] = b["file_id"]
keyboard.append([InlineKeyboardButton(f"{b['file_name']}", callback_data=f"file:{key}")])

nav_buttons = []
if page > 0:
nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev_page"))
if end < len(books):
nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="next_page"))
if nav_buttons:
keyboard.append(nav_buttons)

if context.user_data.get("is_index", False) or include_index_home:
keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

reply_markup = InlineKeyboardMarkup(keyboard)
if update.message:
await update.message.reply_text(text, reply_markup=reply_markup)
elif update.callback_query:
await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

=========================

البحث الذكي متعدد المراحل النهائي

=========================

async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
if update.effective_chat.type != "private":
return

query = update.message.text.strip()
if not query:
return

conn = context.bot_data.get("db_conn")
if not conn:
await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
return

normalized_query = normalize_text(query)
clean_query = remove_common_words(query)
words_in_query = normalize_text(clean_query).split()
keywords = [w for w in words_in_query if w not in ARABIC_STOP_WORDS and len(w) >= 2]
expanded_keywords = expand_keywords_with_synonyms(keywords)
stemmed_keywords = [light_stem(k) for k in expanded_keywords]

context.user_data["last_query"] = normalized_query
context.user_data["last_keywords"] = keywords

ts_query_stemmed = ' & '.join(stemmed_keywords) if stemmed_keywords else ''
ts_query_expanded = ' | '.join(expanded_keywords) if expanded_keywords else ''
final_ts_query = f"({ts_query_stemmed}) | ({ts_query_expanded})" if ts_query_stemmed else ts_query_expanded

books = []
search_stage = "بدون نتائج"

if len(normalized_query.split()) > 2:
try:
books = await conn.fetch("""
SELECT id, file_id, file_name, uploaded_at
FROM books
WHERE file_name ILIKE $1
LIMIT 50;
""", f"%{normalized_query}%")
if books:
search_stage = "🔍 تطابق العبارة الكامل"
except:
pass

if not books and final_ts_query:
try:
books = await conn.fetch("""
SELECT id, file_id, file_name, uploaded_at
FROM books
WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
ORDER BY ts_rank(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) DESC
LIMIT 400;
""", final_ts_query)
if books:
search_stage = "⭐ بحث دلالي (FTS + الجذور المطلوبة)"
except:
pass

if not books and stemmed_keywords:
try:
all_keywords_query = ' & '.join(stemmed_keywords)
books = await conn.fetch("""
SELECT id, file_id, file_name, uploaded_at
FROM books
WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
ORDER BY ts_rank(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) DESC
LIMIT 400;
""", all_keywords_query)
if books:
search_stage = "✅ تطابق جميع الكلمات المفتاحية (AND FTS)"
except:
pass

if not books and stemmed_keywords:
try:
or_query = ' | '.join(stemmed_keywords)
books = await conn.fetch("""
SELECT id, file_id, file_name, uploaded_at
FROM books
WHERE to_tsvector('arabic', file_name) @@ to_tsquery('arabic', $1)
ORDER BY ts_rank(to_tsvector('arabic', file_name), to_tsquery('arabic', $1)) DESC
LIMIT 400;
""", or_query)
if books:
search_stage = "⚠️ بحث واسع (OR Keywords FTS)"
except:
pass

if not books:
await send_search_suggestions(update, context)
context.user_data["search_results"] = []
context.user_data["current_page"] = 0
return

context.user_data["search_results"] = [dict(b) for b in books]
context.user_data["current_page"] = 0
context.user_data["search_stage"] = search_stage
await send_books_page(update, context)

==========================

التعامل مع أزرار الكتب والفهرس

==========================

async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
data = query.data

if data.startswith("file:"):
key = data.split(":")[1]
file_id = context.bot_data.get(f"file_{key}")
if file_id:
caption = "📖 تم التنزيل بواسطة @boooksfree1bot"
share_button = InlineKeyboardMarkup([
[InlineKeyboardButton("شارك البوت مع أصدقائك", switch_inline_query="")]
])
await query.message.reply_document(document=file_id, caption=caption, reply_markup=share_button)
else:
await query.message.reply_text("❌ الملف غير متوفر حالياً.")

elif data == "next_page":
context.user_data["current_page"] += 1
await send_books_page(update, context)

elif data == "prev_page":
context.user_data["current_page"] -= 1
await send_books_page(update, context)

elif data in ("home_index", "show_index"):
from index_handler import show_index
await show_index(update, context)
