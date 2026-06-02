import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Setup logging for the English Index Handler
logger = logging.getLogger(__name__)

# Full 50-Category Structural Index Translated into English with Optimized Database Keywords
ENGLISH_INDEX_CATEGORIES = {
    "1": {"name": "📚 Novels & Stories", "keywords": ["novel", "story", "stories", "fiction", "tale"]},
    "2": {"name": "🕋 Quranic Sciences & Tafsir", "keywords": ["tafsir", "quran", "tajweed", "koran"]},
    "3": {"name": "📜 Islamic Jurisprudence (Fiqh)", "keywords": ["fiqh", "jurisprudence", "fatwa", "madhab"]},
    "4": {"name": "💬 Prophetic Hadiths", "keywords": ["hadith", "bukhari", "muslim", "sunnah"]},
    "5": {"name": "🧠 Psychology", "keywords": ["psychology", "behavior", "psychoanalysis", "freud", "cognitive"]},
    "6": {"name": "🚀 Self-Development & Success", "keywords": ["self-help", "success", "motivation", "habits", "charisma"]},
    "7": {"name": "🏛️ Arabic & Islamic History", "keywords": ["islamic history", "caliphate", "andalus", "ottoman"]},
    "8": {"name": "🌍 World History", "keywords": ["world history", "war", "revolution", "ancient", "civilization"]},
    "9": {"name": "📖 Arabic Literature", "keywords": ["arabic literature", "balagha", "nahw", "diwan"]},
    "10": {"name": "🤔 Philosophy & Logic", "keywords": ["philosophy", "logic", "philosopher", "existentialism", "nietzsche"]},
    "11": {"name": "🧪 Chemistry", "keywords": ["chemistry", "chemical", "elements", "reactions", "laboratory"]},
    "12": {"name": "⚡ Physics", "keywords": ["physics", "quantum", "relativity", "energy", "mechanics"]},
    "13": {"name": "🧬 Biological Sciences", "keywords": ["biology", "genetics", "cell", "organism", "evolution"]},
    "14": {"name": "🩺 Human Medicine", "keywords": ["medicine", "anatomy", "surgery", "medical", "disease"]},
    "15": {"name": "🌿 Alternative & Herbal Medicine", "keywords": ["herbal", "alternative medicine", "natural therapy", "remedy"]},
    "16": {"name": "🚜 Agriculture & Plants", "keywords": ["agriculture", "crops", "soil", "plants", "botany"]},
    "17": {"name": "💻 Programming & Tech", "keywords": ["programming", "code", "python", "software", "computer"]},
    "18": {"name": "🤖 Artificial Intelligence", "keywords": ["artificial intelligence", "ai ", "algorithms", "robot", "machine learning"]},
    "19": {"name": "💰 Economics & Finance", "keywords": ["economics", "finance", "stock", "trade", "investment"]},
    "20": {"name": "📊 Management & Leadership", "keywords": ["management", "leadership", "projects", "marketing", "business"]},
    "21": {"name": "⚖️ Law & Legislation", "keywords": ["law", "rights", "constitution", "court", "judiciary"]},
    "22": {"name": "🗳️ Politics & Int. Relations", "keywords": ["politics", "international relations", "diplomacy", "political"]},
    "23": {"name": "🧒 Children's Books", "keywords": ["children", "kids", "tales", "parenting"]},
    "24": {"name": "🎨 Arts & Cinema", "keywords": ["arts", "drawing", "cinema", "music", "movies", "criticism"]},
    "25": {"name": "🕌 Prophet's Biography (Seerah)", "keywords": ["seerah", "prophet", "biography", "ghazawat"]},
    "26": {"name": "📝 Memoirs & Biographies", "keywords": ["memoirs", "biography", "autobiography", "my life"]},
    "27": {"name": "📐 Mathematics", "keywords": ["mathematics", "math", "algebra", "calculus", "equations"]},
    "28": {"name": "🏗️ Engineering", "keywords": ["engineering", "architect", "civil", "electrical", "mechanical"]},
    "29": {"name": "🗺️ Geography & Maps", "keywords": ["geography", "maps", "terrain", "climate"]},
    "30": {"name": "🔍 Languages & Translation", "keywords": ["language", "translation", "dictionary", "learning", "english"]},
    "31": {"name": "🍽️ Cooking & Culinary Arts", "keywords": ["cooking", "sweets", "food", "recipes", "chef"]},
    "32": {"name": "⚽ Sports & Fitness", "keywords": ["sports", "fitness", "football", "training", "bodybuilding"]},
    "33": {"name": "🌌 Astronomy & Space", "keywords": ["astronomy", "space", "stars", "planets", "galaxies"]},
    "34": {"name": "🛠️ Crafts & Professions", "keywords": ["carpentry", "sewing", "maintenance", "crafts"]},
    "35": {"name": "🐾 Animal World", "keywords": ["animal", "birds", "fishes", "wildlife", "veterinary"]},
    "36": {"name": "📽️ Media & Journalism", "keywords": ["media", "journalism", "radio", "tv ", "news"]},
    "37": {"name": "⛩️ Religions & Sects", "keywords": ["religions", "sects", "creed", "theology", "comparative"]},
    "38": {"name": "👥 Sociology", "keywords": ["sociology", "society", "phenomena", "customs"]},
    "39": {"name": "🎭 Theater & Drama", "keywords": ["theater", "acting", "play script", "drama"]},
    "40": {"name": "🧩 Puzzles & Intelligence", "keywords": ["puzzles", "intelligence", "chess", "thinking", "games"]},
    "41": {"name": "🚢 Travels & Exploration", "keywords": ["travel", "tourism", "passenger", "exploration"]},
    "42": {"name": "🌋 Geology & Earth Sciences", "keywords": ["geology", "minerals", "earthquakes", "rocks", "earth"]},
    "43": {"name": "🛡️ Security & Defense", "keywords": ["security", "defense", "intelligence", "strategy", "army", "military"]},
    "44": {"name": "🧥 Fashion & Style", "keywords": ["fashion", "clothing", "design", "beauty", "style"]},
    "45": {"name": "🏡 Decor & Interior Design", "keywords": ["decor", "furniture", "interior design", "home"]},
    "46": {"name": "🖋️ Detective Novels & Mystery", "keywords": ["mystery", "crime", "investigation", "detective", "thriller"]},
    "47": {"name": "🕯️ Sufism & Spirituality", "keywords": ["sufism", "spiritual", "asceticism", "mysticism"]},
    "48": {"name": "💻 Cybersecurity", "keywords": ["hacker", "cybersecurity", "protection", "encryption", "malware"]},
    "49": {"name": "🏙️ Urban Planning", "keywords": ["urban", "cities", "planning", "construction", "architecture"]},
    "50": {"name": "💎 Minerals & Gemstones", "keywords": ["gemstones", "gold", "silver", "mines", "minerals"]}
}

async def show_english_index_menu(update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the massive 50-category library index to the user in English"""
    keyboard = []
    keys = list(ENGLISH_INDEX_CATEGORIES.keys())
    
    # Arrange buttons dynamically (2 buttons per row)
    for i in range(0, len(keys), 2):
        row = [
            InlineKeyboardButton(ENGLISH_INDEX_CATEGORIES[keys[i]]["name"], callback_data=f"eng_idx:{keys[i]}"),
        ]
        if i + 1 < len(keys):
            row.append(InlineKeyboardButton(ENGLISH_INDEX_CATEGORIES[keys[i+1]]["name"], callback_data=f"eng_idx:{keys[i+1]}"))
        
        keyboard.append(row)

    # 🔄 إضافة زر عودة ثابت في نهاية الـ 50 قسماً للرجوع للوحة التحكم الرئيسية للبوت مباشرة
    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "🇬🇧 **Grand Library Index (50 Specialized Departments)**\n\n"
        "The archive has been rigorously cataloged to suit all academic and general interests.\n"
        "Select the category you wish to browse:"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_english_index_selection(update, context: ContextTypes.DEFAULT_TYPE):
    """Processes the chosen English index department and queries the PostgreSQL database"""
    query = update.callback_query
    category_id = query.data.split(":")[1]
    category = ENGLISH_INDEX_CATEGORIES.get(category_id)
    
    if not category:
        return

    pool = context.bot_data.get("db_conn")
    # Generating the regex pattern for exact pattern matching
    keywords_pattern = "|".join(category["keywords"])
    
    async with pool.acquire() as conn:
        # Utilizing regex matching (~*) to match any of the English keywords in database file names
        sql = """
        SELECT file_id, file_name 
        FROM books 
        WHERE file_name ~* $1 
        LIMIT 700;
        """
        rows = await conn.fetch(sql, f"({keywords_pattern})")

    if not rows:
        await query.answer(f"⚠️ No books found under: {category['name']}", show_alert=True)
        return

    # Store found records cleanly back into user data context
    context.user_data["search_results"] = [dict(r) for r in rows]
    context.user_data["current_page"] = 0
    context.user_data["search_stage"] = f"🇬🇧 Index: {category['name']}"
    
    # 🎯 تحديد هدف العودة الذكي: عند ضغط المستخدم على عودة من داخل نتائج (الروايات مثلاً) يعود لقائمة الفهارس الإنكليزية وليس للبداية
    context.user_data["back_target"] = "show_english_index"
    
    # Hand over the payload to the unified interactive paginator for seamless scrolling and downloading
    from search_handler import send_books_page
    await send_books_page(update, context)
