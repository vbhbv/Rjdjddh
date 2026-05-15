import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# تعريف 25 قسماً دقيقاً ومنوعاً
INDEX_CATEGORIES = {
    "1": {"name": "📚 روايات وقصص", "keywords": ["رواية", "قصة", "روايات", "قصص"]},
    "2": {"name": "🕋 علوم القرآن وتفسير", "keywords": ["تفسير", "قرآن", "تجويد", "القرآن"]},
    "3": {"name": "📜 الفقه وأصوله", "keywords": ["فقه", "الفقيه", "مذهب", "أصول"]},
    "4": {"name": "💬 أحاديث نبوية", "keywords": ["حديث", "الأحاديث", "البخاري", "مسلم", "شرح"]},
    "5": {"name": "🧠 علم النفس", "keywords": ["علم نفس", "السلوك", "تحليل نفسي", "سيكولوجية"]},
    "6": {"name": "🚀 تطوير الذات والنجاح", "keywords": ["ذات", "نجاح", "شخصية", "تحفيز", "كاريزما"]},
    "7": {"name": "🏛️ التاريخ العربي والإسلامي", "keywords": ["تاريخ", "الأندلس", "الخلافة", "الفتوحات"]},
    "8": {"name": "🌍 التاريخ العالمي", "keywords": ["تاريخ العالم", "حروب", "ثورة", "قديم", "العصور"]},
    "9": {"name": "📖 الأدب العربي", "keywords": ["أدب", "بلاغة", "النحو", "شعر", "دواوين"]},
    "10": {"name": "🤔 الفلسفة والمنطق", "keywords": ["فلسفة", "منطق", "فلاسفة", "فكر", "وجودية"]},
    "11": {"name": "🧪 الكيمياء", "keywords": ["كيمياء", "عناصر", "تفاعلات", "معامل", "الكيميائي"]},
    "12": {"name": "⚡ الفيزياء", "keywords": ["فيزياء", "طاقة", "نسبية", "ذرة", "ميكانيكا"]},
    "13": {"name": "🧬 علوم الأحياء والطب", "keywords": ["أحياء", "بيولوجيا", "طب", "صحة", "تشريح"]},
    "14": {"name": "💻 البرمجة والذكاء الاصطناعي", "keywords": ["برمجة", "ذكاء اصطناعي", "كود", "بايثون", "تطبيقات"]},
    "15": {"name": "💰 الاقتصاد والمال", "keywords": ["اقتصاد", "مال", "بورصة", "تجارة", "استثمار"]},
    "16": {"name": "📊 الإدارة والقيادة", "keywords": ["إدارة", "قيادة", "مشاريع", "تسويق", "بزنس"]},
    "17": {"name": "⚖️ القانون والتشريع", "keywords": ["قانون", "حقوق", "دستور", "محاماة", "قضاء"]},
    "18": {"name": "🗳️ السياسة والاجتماع", "keywords": ["سياسة", "علاقات دولية", "اجتماع", "مجتمع"]},
    "19": {"name": "🧒 كتب الأطفال والناشئة", "keywords": ["أطفال", "حكايات", "ناشئة", "تربية"]},
    "20": {"name": "🎨 الفنون والسينما", "keywords": ["فنون", "رسم", "سينما", "موسيقى", "نقد"]},
    "21": {"name": "🕌 السيرة النبوية", "keywords": ["سيرة", "الرسول", "النبي", "الغزوات"]},
    "22": {"name": "📝 المذكرات والسير الذاتية", "keywords": ["مذكرات", "سيرة ذاتية", "حياتي", "أيام"]},
    "23": {"name": "📐 الرياضيات والمهندسة", "keywords": ["رياضيات", "هندسة", "حساب", "جبر", "معادلات"]},
    "24": {"name": "🗺️ الجغرافيا والرحلات", "keywords": ["جغرافيا", "رحلات", "رحالة", "بلدان", "خرائط"]},
    "25": {"name": "🔍 اللغات والترجمة", "keywords": ["لغة", "ترجمة", "قاموس", "تعليم", "إنجليزي"]}
}

async def show_index_menu(update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة الفهارس الـ 25 للمستخدم"""
    keyboard = []
    keys = list(INDEX_CATEGORIES.keys())
    
    # توزيع الأزرار (زرين في كل صف)
    for i in range(0, len(keys), 2):
        row = [
            InlineKeyboardButton(INDEX_CATEGORIES[keys[i]]["name"], callback_data=f"idx:{keys[i]}"),
        ]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(INDEX_CATEGORIES[keys[i+1]]["name"], callback_data=f"idx:{keys[i+1]}"))
        
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "🗂 **فهرس المكتبة الشامل**\n"
        "اختر القسم الذي يهمك استكشافه:"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_index_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار القسم وعرض النتائج مباشرة"""
    query = update.callback_query
    category_id = query.data.split(":")[1]
    category = INDEX_CATEGORIES.get(category_id)
    
    if not category:
        return

    pool = context.bot_data.get("db_conn")
    keywords_pattern = "|".join(category["keywords"])
    
    async with pool.acquire() as conn:
        sql = """
        SELECT file_id, file_name 
        FROM books 
        WHERE file_name ~* $1 
        LIMIT 700;
        """
        rows = await conn.fetch(sql, f"({keywords_pattern})")

    if not rows:
        await query.answer(f"⚠️ لا توجد كتب حالياً في قسم {category['name']}", show_alert=True)
        return

    # حفظ النتائج
    context.user_data["search_results"] = [dict(r) for r in rows]
    context.user_data["current_page"] = 0
    
    # استدعاء دالة العرض العادية (بدون زر العودة)
    from search_handler import send_books_page
    await send_books_page(update, context)
