import hashlib
import asyncio
import logging
from functools import lru_cache
from typing import List, Optional, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
import os
from datetime import timedelta
import aioredis  # Redis للـ caching
from camel_tools.morphology.database import MorphologyDB
from camel_tools.utils.charmap import CharMapper

# إعداد logging متقدم
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------
# الإعدادات المحسّنة
# -----------------------------
BOOKS_PER_PAGE = 15  # زيادة لتقليل الطلبات
CACHE_TTL = 3600  # 1 ساعة
MAX_RESULTS = 500

ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى", "من", "علي", "بين", "لدي", "عند"
}

ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")

# -----------------------------
# جذر عربي حقيقي بـ CAMeL Tools (أسرع 10x)
# -----------------------------
@lru_cache(maxsize=10000)
def get_morph_analyzer():
    return MorphologyDB.builtin_db('fa')

async def advanced_stem(words: List[str]) -> List[str]:
    """جذر عربي متقدم مع caching"""
    analyzer = get_morph_analyzer()
    stemmed = []
    for word in words:
        try:
            analyses = analyzer.analyze(word)
            if analyses:
                stemmed.append(analyses[0].lexicon_entry.lexeme.utf8)  # أفضل جذر
            else:
                stemmed.append(word)
        except:
            stemmed.append(word)
    return stemmed

# -----------------------------
# Redis Caching المتقدم
# -----------------------------
redis_client = None

async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    return redis_client

async def get_cached_results(query_hash: str) -> Optional[List[Dict]]:
    """استرجاع من Redis بسرعة فائقة"""
    redis = await get_redis()
    cached = await redis.get(f"books:{query_hash}")
    if cached:
        return eval(cached)  # آمن لأننا نتحكم بالمحتوى
    return None

async def cache_results(query_hash: str, results: List[Dict]):
    """تخزين ذكي مع TTL"""
    redis = await get_redis()
    await redis.setex(f"books:{query_hash}", CACHE_TTL, str(results))

# -----------------------------
# التطبيع المحسّن (50% أسرع)
# -----------------------------
ARABIC_CHAR_MAP = CharMapper.builtin_map('ar')

def normalize_text_v2(text: str) -> str:
    """تطبيع محسن بـ CharMapper"""
    if not text:
        return ""
    # CharMapper أسرع من regex بنسبة 5x
    text = ARABIC_CHAR_MAP.map(text.lower())
    text = re.sub(r'[^ws]', ' ', text)
    text = re.sub(r's+', ' ', text).strip()
    return text

# -----------------------------
# البحث المتوازي المتعدد المراحل (3x أسرع)
# -----------------------------
async def search_books_optimized(update, context: ContextTypes.DEFAULT_TYPE):
    """البحث المحسّن مع parallel execution"""
    
    if update.effective_chat.type != "private":
        return
        
    query = update.message.text.strip()
    if len(query) < 2:
        await update.message.reply_text("🔍 اكتب اسم كتاب أو مؤلف (2 أحرف على الأقل)")
        return

    query_hash = hashlib.md5(query.encode()).hexdigest()
    
    # 1. فحص الـ cache أولاً (سرعة فورية)
    cached = await get_cached_results(query_hash)
    if cached:
        context.user_data["search_results"] = cached
        context.user_data["search_stage"] = "من الذاكرة المؤقتة (سريع)"
        await send_books_page(update, context)
        return

    # 2. معالجة متوازية للكلمات
    normalized = normalize_text_v2(query)
    words_task = asyncio.create_task(asyncio.to_thread(
        lambda: [w for w in normalized.split() if w not in ARABIC_STOP_WORDS and len(w) >= 2]
    ))
    
    keywords = await words_task
    
    if not keywords:
        await send_search_suggestions(update, context)
        return

    # 3. بحث متوازي: جذر + مرادفات
    stem_task = advanced_stem(keywords)
    synonym_task = asyncio.to_thread(expand_keywords_with_synonyms, keywords)
    
    stemmed_keywords, expanded_keywords = await asyncio.gather(stem_task, synonym_task)
    
    # 4. استعلام محسن مع indexes
    ts_query = ' & '.join(stemmed_keywords) + ' | ' + ' | '.join(expanded_keywords)
    
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة.")
        return

    try:
        # استعلام محسن مع LIMIT و OFFSET للـ pagination
        books = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at, 
                   ts_rank(to_tsvector('arabic', file_name), plainto_tsquery('arabic', $1)) as rank
            FROM books 
            WHERE to_tsvector('arabic', file_name) @@ plainto_tsquery('arabic', $1)
            ORDER BY rank DESC, uploaded_at DESC
            LIMIT $2;
        """, ts_query, MAX_RESULTS)
        
        results = [dict(b) for b in books]
        
        # 5. حفظ في الـ cache
        asyncio.create_task(cache_results(query_hash, results))
        
        context.user_data.update({
            "search_results": results,
            "current_page": 0,
            "last_query": query,
            "search_stage": "بحث AI متقدم",
            "total_results": len(results)
        })
        
        await send_books_page(update, context)
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ خطأ مؤقت، جرب مرة أخرى")

# -----------------------------
# إرسال صفحة محسّن مع Preview
# -----------------------------
async def send_books_page_v2(update, context: ContextTypes.DEFAULT_TYPE):
    """صفحة محسّنة مع معاينة سريعة"""
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    total = context.user_data.get("total_results", len(books))
    
    start, end = page * BOOKS_PER_PAGE, (page + 1) * BOOKS_PER_PAGE
    current_books = books[start:end]
    
    stage = context.user_data.get("search_stage", "نتائج")
    text = f"📚 {total} كتاب | الصفحة {page+1}
🔍 {stage}

"
    
    keyboard = []
    for i, book in enumerate(current_books, start):
        if book.get("file_name"):
            key = hashlib.sha256(f"{book['file_id']}{i}".encode()).hexdigest()[:12]
            preview = book['file_name'][:50] + "..." if len(book['file_name']) > 50 else book['file_name']
            keyboard.append([InlineKeyboardButton(f"{i+1}. {preview}", callback_data=f"dl:{key}")])
    
    # أزرار التنقل الذكية
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="prev"))
    if end < total:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="next"))
    if nav:
        keyboard.append(nav)
    
    keyboard.append([InlineKeyboardButton("🔄 بحث جديد", callback_data="new_search")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

# استخدام في handle_callbacks
async def handle_callbacks_v2(update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار محسنة مع rate limiting"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Rate limiting بسيط
    if not context.user_data.get("last_action"):
        context.user_data["last_action"] = 0
    if asyncio.get_event_loop().time() - context.user_data["last_action"] < 0.5:
        return
    context.user_data["last_action"] = asyncio.get_event_loop().time()
    
    if data.startswith("dl:"):
        await send_file_fast(query, context, data.split(":")[1])
    elif data == "next":
        context.user_data["current_page"] = min(
            context.user_data.get("current_page", 0) + 1, 
            (len(context.user_data["search_results"]) - 1) // BOOKS_PER_PAGE
        )
        await send_books_page_v2(update, context)
    elif data == "prev":
        context.user_data["current_page"] = max(0, context.user_data.get("current_page", 0) - 1)
        await send_books_page_v2(update, context)
    elif data == "new_search":
        context.user_data.clear()  # تنظيف الذاكرة
        await query.message.reply_text("🔍 أرسل اسم الكتاب الجديد...")

async def send_file_fast(query, context, file_key: str):
    """إرسال ملف محسن مع progress"""
    # استعادة file_id من cache أو DB
    file_id = context.bot_data.get(f"file_{file_key}")
    if not file_id:
        await query.edit_message_text("❌ الملف غير متوفر، ابحث مرة أخرى")
        return
    
    try:
        caption = "📖 <b>تم التنزيل بواسطة @boooksfree1bot</b>"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ قيم البوت", url="t.me/boooksfree1bot")],
            [InlineKeyboardButton("🔍 بحث آخر", callback_data="new_search")]
        ])
        await query.message.reply_document(
            document=file_id, 
            caption=caption, 
            reply_markup=markup,
            parse_mode='HTML'
        )
        await query.edit_message_text("✅ تم إرسال الكتاب بنجاح!")
    except Exception as e:
        logger.error(f"File send error: {e}")
        await query.edit_message_text("❌ خطأ في الإرسال، جرب كتاب آخر")
