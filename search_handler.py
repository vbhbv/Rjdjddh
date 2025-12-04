import hashlib
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
from typing import List, Dict, Any
import os

# -----------------------------
# الإعدادات وقائمة Stop Words
# -----------------------------

BOOKS_PER_PAGE = 10

# قائمة الكلمات التي يجب تجاهلها (Stop Words)
# لمنع تضييق البحث بها في المراحل الأولى
ARABIC_STOP_WORDS = {
    "و", "في", "من", "إلى", "عن", "على", "ب", "ل", "ا", "أو", "أن", "إذا",
    "ما", "هذا", "هذه", "ذلك", "تلك", "كان", "قد", "الذي", "التي", "هو", "هي",
    "ف", "ك", "اى"
}

# إعدادات المشرف
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_USER_ID = 0
    print("⚠️ ADMIN_ID environment variable is not valid.")

# -----------------------------
# دوال التطبيع والتنظيف المُحسّنة
# -----------------------------
def normalize_text(text: str) -> str:
    """يوحد الحروف ويزيل الحركات والمسافات الزائدة."""
    if not text: return ""
    text = str(text).lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = text.replace("ـ", "")
    text = re.sub(r"[ًٌٍَُِ]", "", text)
    
    # تحسين: معالجة شاملة للمسافات البيضاء والرموز
    text = re.sub(r'[^\w\s]', ' ', text) # استبدال الرموز بمسافة
    text = re.sub(r'\s+', ' ', text).strip() # إزالة المسافات المتعددة والتنظيف
    return text

def remove_common_words(text: str) -> str:
    """يزيل الكلمات الدالة على نوع الملف (كتاب، رواية، إلخ)."""
    if not text: return ""
    # قائمة أطول وأكثر دقة للكلمات الشائعة التي لا تضيف قيمة للبحث
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء", "طبعة", "مجاني", "كبير", "صغير"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str) -> List[str]:
    """يستخلص الكلمات المفتاحية، ويفصل الكلمات القصيرة الهامة."""
    if not text:
        return []
    clean_text = normalize_text(text)
    words = clean_text.split()
    
    # الكلمات المفتاحية الأساسية (لا تشمل Stop Words)
    keywords = [w for w in words if w not in ARABIC_STOP_WORDS and len(w) >= 1]
    
    # قائمة الكلمات القصيرة (بما في ذلك Stop Words) التي قد تكون مهمة للبحث الدقيق كعبارة كاملة
    stop_words_for_search = [w for w in words if w in ARABIC_STOP_WORDS]
    
    # ندمج الجميع: الكلمات الأساسية + الكلمات القصيرة/Stop Words (للاستخدام في calculate_score)
    return list(set(keywords + stop_words_for_search))

def get_db_safe_query(normalized_query: str) -> str:
    return normalized_query.replace("'", "''")

# -----------------------------
# تقشير بسيط للكلمات (light stemming)
# -----------------------------
def light_stem(word: str) -> str:
    """تقشير خفيف لإزالة اللواحق و'الـ' التعريف."""
    suffixes = ["ية", "ي", "ون", "ات", "ان", "ين", "ه"]
    for suf in suffixes:
        if word.endswith(suf) and len(word) > len(suf) + 2:
            word = word[:-len(suf)]
            break
    if word.startswith("ال") and len(word) > 3:
        word = word[2:]
    
    # التأكد من عدم ترك الكلمة فارغة بعد التقشير
    return word if word else ""

# -----------------------------
# دوال المرادفات البسيطة
# -----------------------------
SYNONYMS = {
    "مهندس": ["هندسة", "مقاول", "معماري"],
    "الهندسة": ["مهندس", "معمار", "بناء"],
    "المهدي": ["المنقذ", "القائم"],
    "عدمية": ["نيتشه", "موت", "عبث"], # مثال لربط الكلمات القصيرة بمواضيعها
    "دين": ["إسلام", "مسيحية", "يهودية", "فقه"],
    "فلسفة": ["منطق", "مفهوم", "متافيزيقا"],
}

def expand_keywords_with_synonyms(keywords: List[str]) -> List[str]:
    """يوسع قائمة الكلمات المفتاحية بمرادفاتها."""
    expanded = set(keywords)
    for k in keywords:
        if k in SYNONYMS:
            expanded.update(SYNONYMS[k])
    return list(expanded)

# -----------------------------
# دالة التقييم الوزني المُعززة (لضمان ظهور الكلمات القصيرة)
# -----------------------------
def calculate_score(book: Dict[str, Any], query_keywords: List[str], normalized_query: str) -> int:
    """تحسب نقاط الكتاب بناءً على تطابق الجذور والكلمات القصيرة الهامة."""
    score = 0
    book_name = normalize_text(book.get('file_name', ''))

    # 1. 🥇 أعلى وزن: التطابق الكامل / شبه الكامل (Exact Match)
    if normalized_query == book_name:
        score += 200 # طفرة نوعية للتطابق التام
    elif normalized_query in book_name:
        score += 100

    title_words = book_name.split()
    
    for k in query_keywords:
        k_len = len(k)
        is_significant_short = k_len <= 3 and k not in ARABIC_STOP_WORDS # كلمة قصيرة ذات دلالة (مثل: دين، فن)

        # 2. ⚖️ تحديد الأوزان الأساسية
        base_match_score = 30 if k_len > 3 else 20 
        base_stem_score = 15 if k_len > 3 else 10

        k_stem = light_stem(k)
        if not k_stem: continue # تخطي الكلمات التي اختفت بعد التقشير

        for t_word in title_words:
            t_stem = light_stem(t_word)
            
            # 3. ⭐️ وزن التطابق في البداية (الأهم)
            if t_stem.startswith(k_stem) and len(k_stem) >= 2:
                score += base_match_score * 2 # وزن مضاعف
            
            # 4. 💫 وزن تطابق الجذر (Stem Match)
            elif k_stem in t_stem:
                score += base_stem_score
                
            # 5. ✨ وزن تطابق الكلمة بالكامل (Partial Word Match)
            elif k in t_word:
                score += 5 
                
            # 6. 💡 تعزيز الكلمات القصيرة الهامة
            if is_significant_short and k == t_word:
                score += 50 # تعزيز إضافي لظهور الكلمة القصيرة الهامة تماماً
                
    return score

# -----------------------------
# إشعار المشرف بعد كل بحث
# -----------------------------
async def notify_admin_search(context: ContextTypes.DEFAULT_TYPE, username: str, query: str, found: bool):
    if ADMIN_USER_ID == 0: return
    bot = context.bot
    status_text = "✅ تم العثور على نتائج" if found else "❌ لم يتم العثور على نتائج"
    username_text = f"@{username}" if username else "(بدون يوزر)"
    message = f"🔔 قام المستخدم {username_text} بالبحث عن:\n`{query}`\nالحالة: {status_text}"
    try:
        await bot.send_message(ADMIN_USER_ID, message, parse_mode='Markdown')
    except Exception as e:
        print(f"Failed to notify admin: {e}")

# -----------------------------
# إرسال صفحة الكتب 
# -----------------------------
async def send_books_page(update, context: ContextTypes.DEFAULT_TYPE, include_index_home: bool = False):
    books = context.user_data.get("search_results", [])
    page = context.user_data.get("current_page", 0)
    search_stage = context.user_data.get("search_stage", "تطابق دقيق")
    total_pages = (len(books) - 1) // BOOKS_PER_PAGE + 1 if books else 1

    start = page * BOOKS_PER_PAGE
    end = start + BOOKS_PER_PAGE
    current_books = books[start:end]

    if "بحث موسع" in search_stage or "الجذور" in search_stage:
        stage_note = "⚠️ نتائج بحث موسع (بحثنا بالجذور والمرادفات)"
    elif "تطابق جميع الكلمات" in search_stage:
        stage_note = "✅ نتائج دلالية (تطابق جميع كلماتك المفتاحية)"
    else:
        stage_note = "✅ نتائج مطابقة (تطابق العبارة كاملة)"

    text = f"📚 النتائج ({len(books)} كتاب)\n{stage_note}\nالصفحة {page + 1} من {total_pages}\n\n"
    keyboard = []

    for b in current_books:
        if not b.get("file_name") or not b.get("file_id"):
            continue
        # استخدام hash لـ file_id لإنشاء مفتاح آمن للكولباك
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

    # زر العودة للفهرس يظهر دائمًا إذا كانت الكتب ضمن فهرس
    if context.user_data.get("is_index", False) or include_index_home:
        keyboard.append([InlineKeyboardButton("🏠 العودة للفهرس", callback_data="home_index")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

# -----------------------------
# البحث الذكي متعدد المراحل (طفرة نوعية)
# -----------------------------
async def search_books(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    query = update.message.text.strip()
    if not query: return

    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    # 💡 المعالجة المسبقة للبحث
    normalized_query = normalize_text(remove_common_words(query))
    all_words_in_query = normalize_text(query).split() # كل كلمات المستخدم (بما في ذلك Stop Words)
    
    # الكلمات المفتاحية الأساسية (بدون Stop Words)
    keywords = [w for w in all_words_in_query if w not in ARABIC_STOP_WORDS and len(w) >= 1] 
    
    # إضافة الجذور والمرادفات للبحث الموسع
    expanded_keywords = expand_keywords_with_synonyms(keywords)
    stemmed_keywords = [light_stem(k) for k in expanded_keywords]
    
    context.user_data["last_query"] = normalized_query
    context.user_data["last_keywords"] = keywords

    books = []
    search_stage_text = "تطابق دقيق (العبارة كاملة)"
    
    try:
        # 1. 🥇 المرحلة الأولى: تطابق العبارة كاملة
        books = await conn.fetch("""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE LOWER(file_name) LIKE '%' || $1 || '%'
            ORDER BY uploaded_at DESC;
        """, normalized_query)
        
        # 2. 🥈 المرحلة الثانية: تطابق جميع الكلمات المفتاحية (المقشرة أو غير المقشرة)
        if not books and keywords:
            search_stage_text = "تطابق جميع الكلمات المفتاحية"
            # شرط AND يجمع تطابق الكلمة أو جذرها لزيادة الدقة
            all_match_conditions = " AND ".join([
                f"(LOWER(file_name) LIKE '%{get_db_safe_query(k)}%' OR LOWER(file_name) LIKE '%{get_db_safe_query(light_stem(k))}%')"
                for k in keywords if len(k) >= 2
            ])
            if all_match_conditions:
                 books = await conn.fetch(f"""
                    SELECT id, file_id, file_name, uploaded_at
                    FROM books
                    WHERE {all_match_conditions}
                    ORDER BY uploaded_at DESC;
                """)

        # 3. 🥉 المرحلة الثالثة: البحث الموسع بالجذور والمرادفات (OR Conditions)
        if not books and expanded_keywords:
            search_stage_text = "بحث موسع بالجذور والمرادفات"
            
            search_terms = list(set(expanded_keywords + stemmed_keywords))
            or_conditions = " OR ".join([
                f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'"
                for k in search_terms if len(k) >= 2
            ])
            
            if or_conditions:
                books = await conn.fetch(f"""
                    SELECT id, file_id, file_name, uploaded_at
                    FROM books
                    WHERE {or_conditions}
                    ORDER BY uploaded_at DESC;
                """)
        
        # 4. 💡 المرحلة الرابعة: ضمان ظهور الكلمات القصيرة الهامة (البحث بالعبارة الأصلية)
        if not books and len(normalized_query.split()) == 1 and normalized_query not in ARABIC_STOP_WORDS:
            search_stage_text = "بحث خاص بالكلمات القصيرة الهامة"
            books = await conn.fetch("""
                SELECT id, file_id, file_name, uploaded_at
                FROM books
                WHERE LOWER(file_name) LIKE '%' || $1 || '%'
                ORDER BY uploaded_at DESC;
            """, normalized_query)


    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ في البحث: {e}")
        return

    found_results = bool(books)
    await notify_admin_search(context, update.effective_user.username, query, found_results)

    if not books:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث عن كتب مشابهة", callback_data="search_similar")]])
        await update.message.reply_text(f"❌ لم أجد أي كتب مطابقة للبحث: {query}\nيمكنك تجربة البحث عن كتب مشابهة:", reply_markup=keyboard)
        context.user_data["search_results"] = []
        context.user_data["current_page"] = 0
        return

    # تطبيق التقييم الوزني المُعزز على جميع النتائج
    scored_books = []
    for book in books:
        # استخدام all_words_in_query كـ query_keywords في calculate_score لضمان احتساب نقاط للكلمات القصيرة
        score = calculate_score(book, all_words_in_query, normalized_query) 
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    # الفرز بناءً على: 1. النقاط (الأعلى) 2. تاريخ الرفع (الأحدث)
    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)
    
    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = search_stage_text
    await send_books_page(update, context)

# -----------------------------
# البحث عن كتب مشابهة
# -----------------------------
async def search_similar_books(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    keywords = context.user_data.get("last_keywords")
    last_query = context.user_data.get("last_query", "")
    
    if not keywords or not conn:
        await update.callback_query.message.reply_text("❌ لا يوجد موضوع للبحث عنه.")
        return

    try:
        # البحث الموسع بالجذور والمرادفات
        expanded_keywords = expand_keywords_with_synonyms(keywords)
        stemmed_keywords = [light_stem(k) for k in expanded_keywords]
        
        search_terms = list(set(expanded_keywords + stemmed_keywords))
        or_conditions = " OR ".join([
            f"LOWER(file_name) LIKE '%{get_db_safe_query(k)}%'"
            for k in search_terms if len(k) >= 2
        ])
        
        if not or_conditions:
            await update.callback_query.message.reply_text("❌ لم أجد كلمات مفتاحية صالحة للبحث المشابه.")
            return
            
        books = await conn.fetch(f"""
            SELECT id, file_id, file_name, uploaded_at
            FROM books
            WHERE {or_conditions}
            ORDER BY uploaded_at DESC;
        """)
        
    except Exception as e:
        await update.callback_query.message.edit_text(f"❌ حدث خطأ أثناء البحث عن كتب مشابهة: {e}")
        return

    scored_books = []
    for book in books:
        # استخدام جميع الكلمات للاحتساب
        all_words_in_query = normalize_text(last_query).split() 
        score = calculate_score(book, all_words_in_query, last_query)
        book_dict = dict(book)
        book_dict['score'] = score
        scored_books.append(book_dict)

    scored_books.sort(key=lambda b: (b['score'], b['uploaded_at']), reverse=True)

    if not scored_books:
        await update.callback_query.message.edit_text("❌ لم أجد كتب مشابهة.")
        return

    context.user_data["search_results"] = scored_books
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = "بحث موسع (مشابه بالجذور والمرادفات)"
    await send_books_page(update, context)

# -----------------------------
# التعامل مع أزرار الكتب + أزرار الفهرس
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
        await search_similar_books(update, context)

    elif data == "home_index" or data == "show_index":
        # يجب أن يكون لديك ملف index_handler.py
        from index_handler import show_index
        await show_index(update, context)
    elif data.startswith("index_page:"):
        from index_handler import navigate_index_pages
        await navigate_index_pages(update, context)
    elif data.startswith("index:"):
        from index_handler import search_by_index
        await search_by_index(update, context)
