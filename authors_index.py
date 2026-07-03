import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ===============================================
# بيانات أعلام الفكر والأدب (القائمة والمجالات)
# ===============================================
AUTHORS_DATA = {
    "philosophy": {
        "title": "🧠 الفلسفة والاجتماع",
        "items": ["علي الوردي", "فريدريش نيتشه", "ابن خلدون", "الغزالي", "المسيري"]
    },
    "literature": {
        "title": "✍️ الأدب والرواية العالمية",
        "items": ["نجيب محفوظ", "دوستويفسكي", "طه حسين", "تولستوي", "العقاد"]
    },
    "islamic": {
        "title": "📚 الفكر والعلوم الإسلامية",
        "items": ["محمد باقر الصدر", "ابن تيمية", "ابن القيم", "المطهري", "مالك بن نبي"]
    },
    "history": {
        "title": "🏛️ التاريخ والآثار",
        "items": ["جواد علي", "طه باقر", "ويل ديورانت", "المقريزي", "ابن الأثير"]
    }
}

# ===============================================
# عرض قائمة التصنيفات الرئيسية للأعلام
# ===============================================
async def show_index_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # بناء الأزرار ديناميكياً
    keyboard = []
    for key, data in AUTHORS_DATA.items():
        keyboard.append([InlineKeyboardButton(data["title"], callback_data=f"auth:cat:{key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "✍️ **فهرس أعلام الأدب والفكر السيّار**\n\n"
        "مرحباً بك في قسم الموسوعات الفكرية والأدبية.\n"
        "هنا تم تصنيف الكتب والمؤلفات بحسب أبرز القامات والفلاسفة لتسهيل الوصول المباشر إلى نتاجهم الكامل.\n\n"
        "📌 اختر التصنيف المعرفي لعرض الأعلام المتاحين:"
    )

    if query:
        # 🛠 تم التصحيح هنا: استخدام edit_message_text بدلاً من edit_text العاطلة
        await query.edit_message_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, parse_mode="Markdown", reply_markup=reply_markup)

# ===============================================
# معالجة الضغطات والاختيارات (Callback Query)
# ===============================================
async def handle_index_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # 1. عند اختيار تصنيف معين
    if data.startswith("auth:cat:"):
        category_key = data.split("auth:cat:")[1]
        category_data = AUTHORS_DATA.get(category_key)

        if not category_data:
            await query.answer("❌ التصنيف غير موجود.", show_alert=True)
            return

        keyboard = []
        for author in category_data["items"]:
            keyboard.append([InlineKeyboardButton(f"📖 مؤلفات {author}", callback_data=f"auth:search:{author}")])
        
        keyboard.append([InlineKeyboardButton("🔙 العودة لفهرس الأعلام", callback_data="show_authors_index")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 🛠 تم التصحيح هنا أيضاً: استخدام edit_message_text
        await query.edit_message_text(
            text=f"📂 **قسم: {category_data['title']}**\n\nاختر اسم المفكر أو الأديب لعرض كافة مؤلفاته وكتبه المتوفرة في المكتبة فوراً:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    # 2. عند اختيار عَلَم معين للبحث عنه
    elif data.startswith("auth:search:"):
        author_name = data.split("auth:search:")[1]
        
        await query.answer(f"🔍 جاري البحث عن مؤلفات: {author_name}...")

        # محاكاة النص من أجل تمريره لدالة البحث بسلاسة
        query.message.text = author_name
        
        from search_handler import search_books
        await search_books(update, context)
