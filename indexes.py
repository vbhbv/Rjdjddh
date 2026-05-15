import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# تعريف 50 قسماً دقيقاً وشاملاً للمكتبة
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
    "13": {"name": "🧬 علوم الأحياء", "keywords": ["أحياء", "بيولوجيا", "وراثة", "خلية"]},
    "14": {"name": "🩺 الطب البشري", "keywords": ["طب", "تشريح", "جراحة", "أدوية", "مرض"]},
    "15": {"name": "🌿 الطب البديل والأعشاب", "keywords": ["أعشاب", "تداوي", "طب بديل", "علاج طبيعي"]},
    "16": {"name": "🚜 الزراعة والنباتات", "keywords": ["زراعة", "محاصيل", "تربة", "نباتات", "ري"]},
    "17": {"name": "💻 البرمجة والتقنية", "keywords": ["برمجة", "كود", "بايثون", "تطبيقات", "كمبيوتر"]},
    "18": {"name": "🤖 الذكاء الاصطناعي", "keywords": ["ذكاء اصطناعي", "خوارزميات", "روبوت", "تعلم الآلة"]},
    "19": {"name": "💰 الاقتصاد والمال", "keywords": ["اقتصاد", "مال", "بورصة", "تجارة", "استثمار"]},
    "20": {"name": "📊 الإدارة والقيادة", "keywords": ["إدارة", "قيادة", "مشاريع", "تسويق", "بزنس"]},
    "21": {"name": "⚖️ القانون والتشريع", "keywords": ["قانون", "حقوق", "دستور", "محاماة", "قضاء"]},
    "22": {"name": "🗳️ السياسة والعلاقات", "keywords": ["سياسة", "علاقات دولية", "دبلوماسية", "نظام"]},
    "23": {"name": "🧒 كتب الأطفال", "keywords": ["أطفال", "حكايات", "ناشئة", "تربية"]},
    "24": {"name": "🎨 الفنون والسينما", "keywords": ["فنون", "رسم", "سينما", "موسيقى", "نقد"]},
    "25": {"name": "🕌 السيرة النبوية", "keywords": ["سيرة", "الرسول", "النبي", "الغزوات"]},
    "26": {"name": "📝 المذكرات والسير الذاتية", "keywords": ["مذكرات", "سيرة ذاتية", "حياتي", "أيام"]},
    "27": {"name": "📐 الرياضيات", "keywords": ["رياضيات", "حساب", "جبر", "معادلات", "تفاضل"]},
    "28": {"name": "🏗️ الهندسة", "keywords": ["هندسة", "معماري", "مدني", "كهرباء", "ميكانيك"]},
    "29": {"name": "🗺️ الجغرافيا والخرائط", "keywords": ["جغرافيا", "خرائط", "تضاريس", "المناخ"]},
    "30": {"name": "🔍 اللغات والترجمة", "keywords": ["لغة", "ترجمة", "قاموس", "تعليم", "إنجليزي"]},
    "31": {"name": "🍽️ الطبخ والمطبخ", "keywords": ["طبخ", "حلويات", "مأكولات", "وصفات", "شيف"]},
    "32": {"name": "⚽ الرياضة واللياقة", "keywords": ["رياضة", "لياقة", "كرة", "تدريب", "كمال أجسام"]},
    "33": {"name": "🌌 الفلك والفضاء", "keywords": ["فلك", "فضاء", "نجوم", "كواكب", "مجرات"]},
    "34": {"name": "🛠️ الحرف والمهن", "keywords": ["نجارة", "خياطة", "كهرباء", "صيانة", "حرفة"]},
    "35": {"name": "🐾 عالم الحيوان", "keywords": ["حيوان", "طيور", "أسماك", "برية", "بيطرة"]},
    "36": {"name": "📽️ الإعلام والصحافة", "keywords": ["إعلام", "صحافة", "راديو", "تلفزيون", "خبر"]},
    "37": {"name": "⛩️ الأديان والمذاهب", "keywords": ["أديان", "مذاهب", "فرق", "عقيدة", "مقارنة"]},
    "38": {"name": "👥 علم الاجتماع", "keywords": ["اجتماع", "مجتمع", "ظواهر", "عادات"]},
    "39": {"name": "🎭 المسرح والدراما", "keywords": ["مسرح", "تمثيل", "نص مسرحي", "خشبة"]},
    "40": {"name": "🧩 الألغاز والذكاء", "keywords": ["ألغاز", "ذكاء", "شطرنج", "تفكير", "ألعاب"]},
    "41": {"name": "🚢 الرحلات والأسفار", "keywords": ["رحلة", "سياحة", "مسافر", "بلاد", "استكشاف"]},
    "42": {"name": "🌋 الجيولوجيا والأرض", "keywords": ["جيولوجيا", "معادن", "زلازل", "صخور", "الأرض"]},
    "43": {"name": "🛡️ الأمن والدفاع", "keywords": ["أمن", "دفاع", "مخابرات", "استراتيجية", "جيش"]},
    "44": {"name": "🧥 الموضة والأزياء", "keywords": ["موضة", "أزياء", "تصميم", "جمال"]},
    "45": {"name": "🏡 الديكور والتصميم", "keywords": ["ديكور", "أثاث", "تصميم داخلي", "منزل"]},
    "46": {"name": "🖋️ الروايات البوليسية", "keywords": ["غموض", "جريمة", "تحقيق", "بوليسي", "مغامرة"]},
    "47": {"name": "🕯️ التصوف والروحانيات", "keywords": ["تصوف", "روحاني", "أوراد", "زهد", "إشراق"]},
    "48": {"name": "💻 الأمن السيبراني", "keywords": ["هكر", "اختراق", "حماية", "سيبراني", "تشفير"]},
    "49": {"name": "🏙️ التخطيط العمراني", "keywords": ["عمران", "مدن", "تخطيط", "بناء"]},
    "50": {"name": "💎 المعادن والأحجار", "keywords": ["أحجار كريمة", "ذهب", "فضة", "مناجم"]}
}

async def show_index_menu(update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة الفهارس الـ 50 للمستخدم"""
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
        "🗂 **فهرس المكتبة الكبرى (50 قسماً)**\n"
        "تم ترتيب المكتبة لتناسب كافة اهتماماتكم.\n"
        "اختر القسم الذي تريد تصفحه:"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_index_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار القسم وعرض النتائج"""
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
    
    # استدعاء دالة العرض
    from search_handler import send_books_page
    await send_books_page(update, context)
