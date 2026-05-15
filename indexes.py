import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# تعريف الأقسام الـ 10 الذكية (تعتمد على الكلمات المفتاحية في أسماء الملفات)
INDEX_CATEGORIES = {
    "1": {"name": "📚 روايات وقصص", "keywords": ["رواية", "قصة", "روايات"]},
    "2": {"name": "⚖️ كتب دينية وإسلامية", "keywords": ["تفسير", "فقه", "إسلام", "حديث", "سيرة"]},
    "3": {"name": "🧠 علم نفس وتطوير ذات", "keywords": ["نفس", "ذات", "نجاح", "شخصية", "تحفيز"]},
    "4": {"name": "📜 تاريخ وحضارة", "keywords": ["تاريخ", "حضارة", "حروب", "قديم", "سيرة"]},
    "5": {"name": "🧬 علوم وطب", "keywords": ["علوم", "طب", "صحة", "فيزياء", "كيمياء"]},
    "6": {"name": "💻 برمجة وتكنولوجيا", "keywords": ["برمجة", "حاسوب", "ذكاء", "تقنية", "كود"]},
    "7": {"name": "💰 اقتصاد وإدارة", "keywords": ["اقتصاد", "مال", "إدارة", "تجارة", "بزنس"]},
    "8": {"name": "🎨 أدب وفلسفة", "keywords": ["أدب", "فلسفة", "شعر", "فكر", "خواطر"]},
    "9": {"name": "🧒 كتب أطفال", "keywords": ["أطفال", "قصص أطفال", "ناشئة", "تعليم"]},
    "10": {"name": "🌍 سياسة وقانون", "keywords": ["سياسة", "قانون", "دولي", "حقوق"]}
}

async def show_index_menu(update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة الفهارس الـ 10 للمستخدم"""
    keyboard = []
    # ترتيب الأقسام في صفوف (كل صف فيه زرين)
    keys = list(INDEX_CATEGORIES.keys())
    for i in range(0, len(keys), 2):
        row = [
            InlineKeyboardButton(INDEX_CATEGORIES[keys[i]]["name"], callback_data=f"idx:{keys[i]}"),
            InlineKeyboardButton(INDEX_CATEGORIES[keys[i+1]]["name"], callback_data=f"idx:{keys[i+1]}") if i+1 < len(keys) else None
        ]
        keyboard.append([btn for btn in row if btn])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🗂 **فهرس المكتبة الذكي**\nاختر القسم الذي تريد استكشافه:"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_index_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المستخدم لقسم معين والبحث فيه تلقائياً"""
    query = update.callback_query
    category_id = query.data.split(":")[1]
    category = INDEX_CATEGORIES.get(category_id)
    
    if not category:
        return

    pool = context.bot_data.get("db_conn")
    # بناء استعلام SQL يبحث عن الكلمات المفتاحية للقسم
    keywords_pattern = "|".join(category["keywords"])
    
    async with pool.acquire() as conn:
        # البحث عن أول 50 كتاب ينتمي لهذا القسم
        sql = """
        SELECT file_id, file_name 
        FROM books 
        WHERE file_name ~* $1 
        LIMIT 700;
        """
        rows = await conn.fetch(sql, f"({keywords_pattern})")

    if not rows:
        await query.answer(f"⚠️ لا توجد كتب حالياً في قسم {category['name']}")
        return

    # إرسال النتائج باستخدام نفس نظام عرض الكتب الموجود عندك
    from search_handler import send_books_page
    context.user_data["search_results"] = [dict(r) for r in rows]
    context.user_data["current_page"] = 0
    await send_books_page(update, context)
