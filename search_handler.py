import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os

BOOKS_PER_PAGE = 10

# -----------------------------
# إعدادات المشرف (لم يتم تغييرها)
# -----------------------------

try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))  # معرف المشرف
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف (مُبقاة للتعامل مع استعلام المستخدم)
# -----------------------------

def normalize_text(text: str) -> str:
    """لتطبيع النص العربي للبحث."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    # FTS في PostgreSQL سيعالج الهمزات والتاء المربوطة بشكل أفضل، لكن نبقي هذا للتنظيف الأولي
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    """إزالة الكلمات العامة مثل كتاب/رواية/نسخة (أصبح دورها أقل أهمية)."""
    if not text:
        return ""
    # ملاحظة: FTS يزيل stop words تلقائياً، لكن نترك هذه الدالة لمعالجة بعض الحالات الخاصة
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    """استخراج الكلمات المفتاحية المهمة (لم تعد تستخدم في الخوارزمية الجديدة، لكن تم الإبقاء عليها)."""
    if not text:
        return []
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

def get_db_safe_query(normalized_query: str) -> str:
    """بناء استعلام آمن من SQL Injection البسيط."""
    return normalized_query.replace("'", "''")

# -----------------------------
# دالة التقييم الوزني القديمة (لم تعد تستخدم في search_books)
# -----------------------------
# تم تركها في الكود ولكن لن يتم استدعاؤها في دالة البحث الرئيسية

# -----------------------------
# إشعار المشرف وإرسال صفحة الكتب (لم يتم تغييرهما)
# -----------------------------
# ... (notify_admin_search و send_books_page كما هي)
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

async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "بحث دلالي مُعزز" in search_stage:
        stage_note = "⭐ نتائج بحث ذكية ومُعززة (مرتبة حسب الصلة)"
    else:
        stage_note = "⚠️ نتائج بحث موسع (Fallback)"

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


# -----------------------------
# 🥇 خوارزمية البحث الجديدة (PostgreSQL FTS)
# -----------------------------

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

    # 1. التنظيف الأولي للاستعلام
    normalized_query = normalize_text(remove_common_words(query))
    ts_query_text = get_db_safe_query(normalized_query)
    
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = extract_keywords(normalized_query) # نحتاجها في دالة Fallback
    
    books = []
    search_stage_text = "بحث دلالي مُعزز"

    try:
        # 2. الاستعلام: استخدام FTS والترتيب بالـ ts_rank
        # ملاحظة: plainto_tsquery('arabic', $1) يقوم بتجذير كلمات الاستعلام تلقائياً
        
        books = await conn.fetch("""
            SELECT 
                id, 
                file_id, 
                file_name, 
                uploaded_at,
                -- حساب درجة التقييم الوزني الذكية
                ts_rank(file_name_tsvector, plainto_tsquery('arabic', $1)) AS rank_score
            FROM books
            -- البحث: يجب أن يكون هناك تطابق في الفهرس
            WHERE file_name_tsvector @@ plainto_tsquery('arabic', $1)
            -- الترتيب حسب درجة الصلة، ثم بتاريخ التحميل
            ORDER BY rank_score DESC, uploaded_at DESC
            LIMIT 1000;
        """, ts_query_text)

    except Exception as e:
        # في حالة فشل الاستعلام (قد يكون الفهرس file_name_tsvector غير موجود)
        print(f"FTS Query Failed: {e}. Falling back to old OR search.")
        books = []
        search_stage_text = "بحث موسع (Fallback)"
        # يمكن إضافة هنا كود البحث الموسع القديم (المرحلة 3) كخطة بديلة (Fallback)

    found_results = bool(books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not books:
        # إذا لم نجد شيئاً باستخدام FTS، نعود للبحث الموسع القديم (المرحلة 3)
        return await search_similar_books(update, context, is_fallback=True)

    # 3. الترتيب النهائي (نستخدم الدرجة rank_score القادمة من FTS)
    scored_books = []
    for book in books:
        book_dict = dict(book)
        # نستخدم rank_score كدرجة التقييم
        book_dict['score'] = book.get('rank_score', 0) 
        scored_books.append(book_dict)

    # الترتيب: تم مسبقاً في SQL، لكن نعيد ترتيب قائمة البايثون
    scored_books.sort(key=lambda b: b['score'], reverse=True)
    
    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = search_stage_text
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة (تم تعديلها لتعمل كـ Fallback)
# -----------------------------

async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE, is_fallback=False):
    conn = context.bot_data.get("db_conn")
    # نستخدم last_query الأصلي إذا كنا في callback
    query = context.user_data.get("last_query")
    keywords = context.user_data.get("last_keywords")
    
    if not keywords or not conn:
        message_to_edit = update.callback_query.message if update.callback_query else update.message
        await message_to_edit.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    # **هذه المرحلة تستخدم الطريقة القديمة (OR LIKE) كـ FALLBACK فقط**
    try:
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
        """)
    except Exception as e:
        message_to_edit = update.callback_query.message if update.callback_query else update.message
        await message_to_edit.reply_text("❌ حدث خطأ أثناء البحث الموسع.")
        return

    # نستخدم دالة التقييم القديمة لترتيب نتائج Fallback
    scored_books = []
    for book in books:
        # نحتاج إلى دالة calculate_score القديمة لترتيب نتائج الـ Fallback
        score = calculate_score(book, keywords, context.user_data.get("last_query", ""))
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)

    if not scored_books:
        message_to_edit = update.callback_query.message if update.callback_query else update.message
        await message_to_edit.reply_text(f"❌ لم أجد كتب مشابهة للبحث: {query}.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (Fallback)"
    
    # تحديد مصدر الـ update ليرد بشكل صحيح (رسالة جديدة أو تعديل رسالة Callback)
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار الكتب والمشاركة (لم يتم تغييره)
# -----------------------------

async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة @boooksfree1bot"
            share_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 شارك البوت مع أصدقائك", switch_inline_query="")]
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
    elif data == "search_similar":
        await search_similar_books(update, context, is_fallback=True)

