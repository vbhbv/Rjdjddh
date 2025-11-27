import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any

BOOKS_PER_PAGE = 10

# -----------------------------
# دوال التطبيع والتنظيف
# -----------------------------
def normalize_text(text: str) -> str:
    """لتطبيع النص العربي للبحث."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    # توحيد الألف
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    # توحيد الياء والهاء المربوطة
    text = text.replace("ى", "ي")
    text = text.replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    """إزالة الكلمات العامة."""
    if not text:
        return ""
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    """استخراج الكلمات المفتاحية المهمة (أطول من 3 أحرف)."""
    if not text:
        return []
    # إزالة علامات الترقيم
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    # الكلمات المفتاحية المميزة (لأكثر من 3 حروف)
    keywords = [w for w in words if len(w) >= 3]
    return keywords

def get_db_safe_query(normalized_query: str) -> str:
    """بناء العبارة SQL المعالجة للتطابق في قاعدة البيانات."""
    # (هذه الدالة مفيدة في قواعد البيانات التي لا تدعم دوال التبديل المعقدة)
    # نستخدم نفس التطبيع هنا للتأكد من مطابقة التطبيع في بايثون
    db_safe_query = normalized_query.replace("'", "''") # لمنع SQL Injection البسيط في الاستعلامات الديناميكية
    return db_safe_query

# -----------------------------
# إرسال صفحة الكتب مع التغذية الراجعة
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    # التغذية الراجعة الذكية
    if "بحث موسع" in search_stage:
        stage_note = "⚠️ **نتائج بحث موسع** (بحثنا بالكلمات المفتاحية)"
    elif "تطابق جميع الكلمات" in search_stage:
        stage_note = "✅ **نتائج دلالية** (تطابق جميع كلماتك)"
    else:
        stage_note = "✅ **نتائج مطابقة** (تطابق العبارة كاملة)"

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
    
    # تحديد أين سيتم إرسال الرد
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        # يفضل تعديل الرسالة القادمة من callback_query بدلاً من الرد برسالة جديدة
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# خوارزمية البحث الذكي متعددة المراحل (MSSA)
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

    # 1. الإعداد والتطبيع
    normalized_query = normalize_text(remove_common_words(query))
    keywords = extract_keywords(normalized_query)
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords
    
    books = []
    search_stage_text = "تطابق دقيق"

    try:
        # ------------------------------------------------
        # المرحلة 1: التطابق الحرفي المُطبع (الدقة 100%)
        # ------------------------------------------------
        books = await conn.fetch("""
        SELECT id, file_id, file_name, uploaded_at -- يجب جلب uploaded_at للتقييم
        FROM books
        WHERE LOWER(file_name) LIKE '%' || $1 || '%'
        ORDER BY uploaded_at DESC;
        """, normalized_query)

        # ------------------------------------------------
        # المرحلة 2: التطابق الشبه دلالي (جميع الكلمات الأساسية - AND)
        # ------------------------------------------------
        if not books and keywords:
            search_stage_text = "تطابق جميع الكلمات"
            # بناء استعلام AND ديناميكي
            and_conditions = " AND ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
            books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {and_conditions}
            ORDER BY uploaded_at DESC;
            """)

        # ------------------------------------------------
        # المرحلة 3: البحث الموسع (الكلمات المفتاحية - OR)
        # ------------------------------------------------
        if not books and keywords:
            search_stage_text = "بحث موسع بالكلمات المفتاحية"
            # بناء استعلام OR ديناميكي
            or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
            books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
            """)

    except Exception as e:
        print(f"Database Error: {e}")
        await update.message.reply_text("❌ حدث خطأ في البحث.")
        return

    if not books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return
    
    # 2. التقييم الذكي (Smart Scoring)
    scored_books = []
    for book in books:
        score = 0
        title_lower = book['file_name'].lower()
        
        # وزن التطابق: زيادة النتيجة لكل كلمة مفتاحية موجودة في العنوان
        for k in keywords:
            if k in title_lower:
                score += 1
        
        # تحويل السجل (Record) إلى قاموس (Dict) لتمكين التعديل والإضافة
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    # الترتيب: أولاً حسب تقييم المطابقة (الأعلى أولاً)، ثم حسب تاريخ الرفع
    # (افتراض أن uploaded_at هو حقل زمني يمكن استخدامه للمقارنة)
    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = search_stage_text
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة (تم استبداله بالمرحلة 3)
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    # هذه الدالة تستخدم الآن المرحلة 3 الموسعة من البحث
    conn = context.bot_data.get("db_conn")
    keywords = context.user_data.get("last_keywords")
    if not keywords or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return
    
    try:
        # تنفيذ المرحلة 3 (OR Conditions) مرة أخرى
        or_conditions = " OR ".join([f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'" for k in keywords])
        books = await conn.fetch(f"""
        SELECT id, file_id, file_name, uploaded_at
        FROM books
        WHERE {or_conditions}
        ORDER BY uploaded_at DESC;
        """)
    except Exception as e:
        await update.callback_query.message.reply_text("❌ حدث خطأ أثناء البحث عن كتب مشابهة.")
        return

    # تطبيق التقييم الذكي على النتائج المشابهة
    scored_books = []
    for book in books:
        score = 0
        title_lower = book['file_name'].lower()
        for k in keywords:
            if k in title_lower:
                score += 1
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)
    
    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)


    if not scored_books:
        await update.callback_query.message.reply_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (مشابه)" # تحديث المرحلة
    await send_books_page(update, context)


# -----------------------------
# التعامل مع أزرار الكتب والمشاركة
# -----------------------------
async def handle_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("file:"):
        key = data.split(":")[1]
        file_id = context.bot_data.get(f"file_{key}")
        if file_id:
            caption = "تم التنزيل بواسطة [اسم البوت هنا]"
            share_button = InlineKeyboardMarkup([
                # يمكنك استبدال القيمة الفارغة باسم البوت لتسهيل المشاركة
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
        await search_similar_books(update, context)

