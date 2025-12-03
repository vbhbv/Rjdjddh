import asyncpg
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import hashlib

# -----------------------------
# دوال التطبيع والكلمات المرادفة
# -----------------------------
def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ه", "ة")
    return text

def remove_common_words(text: str) -> str:
    for word in ["كتاب", "رواية", "نسخة", "مجموعة", "مجلد", "جزء", "شاعر", "قصيدة"]:
        text = text.replace(word, "")
    return text.strip()

def extract_keywords(text: str):
    clean_text = re.sub(r'[^\w\s]', '', text)
    words = clean_text.split()
    return [w for w in words if len(w) >= 3]

# -----------------------------
# إنشاء جدول الفهرس
# -----------------------------
async def init_index_table(conn: asyncpg.Connection):
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS index_table (
        id SERIAL PRIMARY KEY,
        category TEXT UNIQUE,
        keywords TEXT[]
    );
    """)

    # أمثلة توسيع الفهرس: 30 فهرس
    categories = {
        "قواعد اللغة العربية": ["لغة", "نحو", "صرف", "إملاء", "صرفية"],
        "كتب إنكليزية": ["english", "grammar", "literature", "english books"],
        "كتب قانون": ["قانون", "تشريع", "محكمة", "قانوني"],
        "شعر": ["شاعر", "قصيدة", "ديوان", "معلقات"],
        "نقد أدبي": ["نقد", "أدب", "تحليل", "مراجعة"],
        "فيزياء": ["فيزياء", "علوم", "طبيعة", "فيزيائي"],
        "كيمياء": ["كيمياء", "مركبات", "تفاعلات"],
        "رياضيات": ["رياضيات", "جبر", "هندسة", "تحليل"],
        "فلسفة": ["فلسفة", "فلاسفة", "منطق", "أخلاق"],
        "اقتصاد": ["اقتصاد", "مالية", "أسواق"],
        "تاريخ": ["تاريخ", "حضارة", "أحداث", "سيرة"],
        "جغرافيا": ["جغرافيا", "خرائط", "أرض", "عالم"],
        "طب": ["طب", "دواء", "تشخيص", "علاج"],
        "تقنية": ["برمجة", "حاسوب", "تقنية", "ذكاء اصطناعي"],
        "دين": ["إسلام", "مسيحية", "يهودية", "دين"],
        "سيرة ذاتية": ["سيرة", "حياة", "مذكرات", "ذكريات"],
        "سياسة": ["سياسة", "حكومة", "انتخابات", "قرار"],
        "أدب عالمي": ["رواية", "أدب", "كتاب", "قصص"],
        "روايات": ["رواية", "خيال", "قصص", "روائي"],
        "قصص أطفال": ["أطفال", "قصص", "تعليم", "حكايات"],
        "رياضة": ["رياضة", "كرة", "ملاعب", "لاعبين"],
        "علوم اجتماعية": ["علم الاجتماع", "سلوك", "مجتمع", "علاقات"],
        "علم نفس": ["علم النفس", "سلوك", "شخصية", "تحليل"],
        "تقارير وأبحاث": ["بحث", "تقرير", "دراسة", "ورقة"],
        "مسلسلات وأفلام": ["سينما", "مسلسلات", "أفلام", "تمثيل"],
        "فنون": ["فن", "لوحة", "موسيقى", "إبداع"],
        "تصميم": ["تصميم", "جرافيك", "ديكور", "تصاميم"],
        "موسوعات": ["موسوعة", "موسوعات", "مرجع", "كتاب"],
        "برمجة": ["python", "java", "برمجة", "coding"],
        "ذكاء اصطناعي": ["ai", "machine learning", "ذكاء", "تعلم آلي"],
        "طبخ": ["طبخ", "وصفات", "أطعمة", "مأكولات"]
    }

    for cat, keys in categories.items():
        await conn.execute("""
        INSERT INTO index_table(category, keywords)
        VALUES($1, $2)
        ON CONFLICT (category) DO UPDATE
        SET keywords = EXCLUDED.keywords;
        """, cat, keys)

# -----------------------------
# عرض الفهرس بالأزرار
# -----------------------------
async def show_index(update, context: ContextTypes.DEFAULT_TYPE):
    conn = context.bot_data.get("db_conn")
    if not conn:
        await update.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    rows = await conn.fetch("SELECT category FROM index_table ORDER BY category;")
    keyboard = []
    for r in rows:
        keyboard.append([InlineKeyboardButton(r["category"], callback_data=f"index:{r['category']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📚 اختر الفهرس:", reply_markup=reply_markup)

# -----------------------------
# البحث عن كتب حسب الفهرس
# -----------------------------
async def search_by_index(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.split(":")[1]

    conn = context.bot_data.get("db_conn")
    if not conn:
        await query.message.reply_text("❌ قاعدة البيانات غير متصلة حالياً.")
        return

    # جلب كلمات الفهرس
    row = await conn.fetchrow("SELECT keywords FROM index_table WHERE category=$1;", category)
    if not row:
        await query.message.reply_text("❌ لم أجد هذا الفهرس.")
        return

    keywords = row["keywords"]
    # البحث في جدول الكتب
    conditions = " OR ".join([f"LOWER(file_name) LIKE '%{k.lower()}%'" for k in keywords])
    books = await conn.fetch(f"SELECT file_id, file_name FROM books WHERE {conditions} ORDER BY uploaded_at DESC;")

    if not books:
        await query.message.reply_text(f"❌ لا توجد كتب ضمن الفهرس: {category}")
        return

    text = f"📚 كتب الفهرس: {category}\n\n"
    keyboard = []
    for b in books:
        key = hashlib.md5(b["file_id"].encode()).hexdigest()[:16]
        context.bot_data[f"file_{key}"] = b["file_id"]
        keyboard.append([InlineKeyboardButton(b["file_name"], callback_data=f"file:{key}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)
