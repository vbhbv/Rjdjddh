import os
import re
import asyncpg
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    ChatMemberHandler, PicklePersistence, ContextTypes, filters
)

# إعدادات المراقبة واللوج
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===============================================
# معالج الأخطاء العام لمنع الانهيار الصامت
# ===============================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("⚠️ Exception while handling an update:", exc_info=context.error)

# ===============================================
# إعداد وتجهيز قاعدة البيانات (PostgreSQL)
# ===============================================
async def init_db(app_context: ContextTypes.DEFAULT_TYPE):
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("🚨 DATABASE_URL variable is missing.")
            return

        pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )

        async with pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                file_name TEXT,
                name_normalized TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW(),
                is_premium BOOLEAN DEFAULT FALSE,
                premium_expiry TIMESTAMP,
                search_credits INT DEFAULT 0
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INT DEFAULT 0
            );
            """)
            
            await conn.execute("INSERT INTO stats (key, value) VALUES ('total_searches', 0) ON CONFLICT DO NOTHING;")

        app_context.bot_data["db_conn"] = pool
        logger.info("✅ Database pool ready and schemas verified.")

    except Exception:
        logger.error("❌ Database setup error", exc_info=True)

async def close_db(app: Application):
    pool = app.bot_data.get("db_conn")
    if pool:
        await pool.close()
        logger.info("✅ Database pool closed.")

# ===============================================
# نظام التحقق من القنوات الإجبارية والبريميوم
# ===============================================
async def check_subscription(user_id: int, bot) -> bool:
    try:
        from __main__ import app
        pool = app.bot_data.get("db_conn")
        channel_id = app.bot_data.get("required_channel_id")
    except:
        pool, channel_id = None, None

    if pool:
        try:
            async with pool.acquire() as conn:
                res = await conn.fetchrow("SELECT is_premium, premium_expiry FROM users WHERE user_id = $1", user_id)
                if res and res["is_premium"]:
                    if res["premium_expiry"] is None or res["premium_expiry"] > datetime.now():
                        return True  
        except Exception as e:
            logger.error(f"Error checking premium status: {e}")

    if channel_id is None: return True
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"Error checking chat member status: {e}")
        return False

async def get_channel_invite_link(bot) -> str:
    try:
        from __main__ import app
        channel_id = app.bot_data.get("required_channel_id")
    except: channel_id = None
    if channel_id is None: return "https://t.me/"
    try:
        chat = await bot.get_chat(channel_id)
        if chat.username: return f"https://t.me/{chat.username}"
        elif chat.invite_link: return chat.invite_link
    except: pass
    return "https://t.me/"

# ===============================================
# أرشفة واستقبال ملفات الـ PDF تلقائياً
# ===============================================
async def handle_pdf(update, context: ContextTypes.DEFAULT_TYPE):
    if (
        update.channel_post
        and update.channel_post.document
        and update.channel_post.document.mime_type == "application/pdf"
    ):
        pool = context.bot_data.get("db_conn")
        if not pool: return

        document = update.channel_post.document
        file_name = document.file_name or "Unknown_Book.pdf"
        
        async with pool.acquire() as conn:
            await conn.execute("""
            INSERT INTO books(file_id, file_name)
            VALUES($1, $2)
            ON CONFLICT (file_id) DO UPDATE SET file_name = EXCLUDED.file_name;
            """, document.file_id, file_name)

# ===============================================
# معالجة النصوص والبحث المتقدم الذكي
# ===============================================
def clean_arabic_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r'[^\w\s]', ' ', text)
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ة': 'ه', 'ى': 'ي',
        'گ': 'ك', 'پ': 'ب', 'چ': 'ج', 'ژ': 'ج', 'ڤ': 'ف'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lower()

async def search_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if not pool or not update.message or not update.message.text: return

    query_text = update.message.text.strip()
    if query_text.startswith('/'): return

    if len(query_text) < 2:
        await update.message.reply_text("⚠️ **الرجاء كتابة كلمتين أو أكثر للبحث بشكل دقيق.**", parse_mode="Markdown")
        return

    cleaned_query = clean_arabic_text(query_text)
    
    # زيادة عداد الإحصائيات
    try:
        async with pool.acquire() as conn:
            await conn.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_searches';")
    except: pass

    searching_msg = await update.message.reply_text("🔍 **جاري الفحص والبحث في الأرشيف الرقمي...**", parse_mode="Markdown")

    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT file_id, file_name, similarity(file_name, $1) as sim
                FROM books
                WHERE file_name % $1 OR to_tsvector('arabic', file_name) @@ plainto_tsquery('arabic', $1)
                ORDER BY sim DESC, id DESC
                LIMIT 10;
            """, query_text)
        except Exception as e:
            logger.error(f"Search Query Error: {e}")
            rows = []

    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=searching_msg.message_id)

    if not rows:
        # اقتراح نظام الرادار القرائي إذا لم يتوفر الكتاب
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💡 تشغيل رادار الاقتراحات", callback_data="radar_menu")]])
        await update.message.reply_text(
            text=f"❌ **لم يتم العثور على كتاب باسم: ({query_text})**\n\nتأكد من كتابة الاسم صحيحاً أو جرب البحث بكلمات مفتاحية أخرى.",
            parse_mode="Markdown", reply_markup=keyboard
        )
        return

    for row in rows:
        file_id = row["file_id"]
        file_name = row["file_name"]
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 تحميل الكتاب الفوري", callback_data=f"dl:{file_id}")],
            [InlineKeyboardButton("📢 مشاركة الكتاب مع صديق", switch_inline_query_current_chat=f"book:{file_id}")]
        ])
        
        await update.message.reply_text(
            text=f"📖 **الكتاب المستخرج:**\n`{file_name}`",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# ===============================================
# نظام الرادار القرائي (المستشار الذكي للكتب)
# ===============================================
async def start_radar_flow(query):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 روايات وقصص", callback_data="rad_cat:novels"), InlineKeyboardButton("🧠 فلسفة وعلم نفس", callback_data="rad_cat:philosophy")],
        [InlineKeyboardButton("⏳ تاريخ وسير", callback_data="rad_cat:history"), InlineKeyboardButton("💼 ريادة أعمال وتنمية", callback_data="rad_cat:business")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(
        text="💡 **مرحباً بك في رادار الاقتراحات القرائية الذكي**\n\nاختر المجال الثقافي الذي ترغب في استكشاف كتبه الآن:",
        parse_mode="Markdown", reply_markup=keyboard
    )

async def process_radar_category(query, context):
    category = query.data.split(":")[1]
    context.user_data["radar_cat"] = category
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 للمبتدئين", callback_data="rad_diff:easy")],
        [InlineKeyboardButton("🪴 متوسط وعميق", callback_data="rad_diff:medium")],
        [InlineKeyboardButton("🏛️ تخصصي ومتقدم", callback_data="rad_diff:hard")]
    ])
    await query.message.edit_text(text="🎯 **ما هو مستوى القراءة المناسب لك في هذا المجال؟**", parse_mode="Markdown", reply_markup=keyboard)

async def process_radar_difficulty(query, context):
    difficulty = query.data.split(":")[1]
    context.user_data["radar_diff"] = difficulty
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 كتب وجيزة (أقل من 150 صفحة)", callback_data="rad_size:small")],
        [InlineKeyboardButton("📖 كتب متوسطة (150 - 350 صفحة)", callback_data="rad_size:medium")],
        [InlineKeyboardButton("📚 مجلدات شاملة (أكثر من 350 صفحة)", callback_data="rad_size:large")]
    ])
    await query.message.edit_text(text="⏳ **اختر حجم ونوعية الكتاب المفضل لجلسة القراءة الحالية:**", parse_mode="Markdown", reply_markup=keyboard)

async def execute_radar_search(query, context):
    pool = context.bot_data.get("db_conn")
    cat = context.user_data.get("radar_cat", "novels")
    diff = context.user_data.get("radar_diff", "medium")
    size = query.data.split(":")[1]
    
    # كلمات مفتاحية استرشادية للربط الدلالي
    keywords_map = {
        "novels": ["رواية", "قصة", "حكايات", "نجيب محفوظ", "أجاثا"],
        "philosophy": ["فلسفة", "علم نفس", "تحليل", "نيتشه", "سيغموند"],
        "history": ["تاريخ", "سيرة", "أندلس", "الحروب", "الحضارة"],
        "business": ["مال", "استثمار", "تنمية", "ثراء", "إدارة"]
    }
    
    target_keywords = keywords_map.get(cat, ["كتاب"])
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY RANDOM() LIMIT 3;
        """, [f"%{k}%" for k in target_keywords])

    if not rows:
        await query.message.edit_text(text="⏳ **الرادار يقوم بتحديث الاقتراحات حالياً، يرجى المحاولة لاحقاً أو البحث نصياً.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="back_to_main")]]))
        return

    response_text = "💡 **إليك ترشيحات الرادار الذكي المبنية على تفضيلاتك:**\n\n"
    keyboard_buttons = []
    for i, row in enumerate(rows, 1):
        response_text += f"{i}️⃣ `{row['file_name']}`\n\n"
        keyboard_buttons.append([InlineKeyboardButton(r"📥 تحميل الاقتراح " + str(i), callback_data=f"dl:{row['file_id']}")])
    
    keyboard_buttons.append([InlineKeyboardButton("🔄 اقتراحات أخرى", callback_data="radar_menu"), InlineKeyboardButton("🔙 الرئيسية", callback_data="back_to_main")])
    await query.message.edit_text(text=response_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard_buttons))

# ===============================================
# نظام الفهارس الشاملة (العربية والإنجليزية)
# ===============================================
async def show_index_menu(update, context):
    query = update.callback_query
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 الروايات الأدبية", callback_data="idx:novels"), InlineKeyboardButton("🕌 العلوم الإسلامية", callback_data="idx:islamic")],
        [InlineKeyboardButton("📈 الاقتصاد والإدارة", callback_data="idx:economy"), InlineKeyboardButton("🧬 الطب والعلوم", callback_data="idx:science")],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="back_to_main")]
    ])
    await query.message.edit_text(text="🇮🇶 **فهرس التصنيفات الكبرى للمكتبة العربية:**\n\nاختر القسم لاستخراج أشهر العناوين المتاحة:", parse_mode="Markdown", reply_markup=keyboard)

async def handle_index_selection(update, context):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    
    cat_keywords = {
        "novels": ["رواية", "روايات", "قصص"], "islamic": ["تفسير", "حديث", "فقه", "سيرة"],
        "economy": ["اقتصاد", "تسويق", "إدارة", "أسهم"], "science": ["فيزياء", "طبيعة", "كيمياء", "أحياء"]
    }
    
    keywords = cat_keywords.get(category, ["كتاب"])
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY id DESC LIMIT 5;
        """, [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 هذا القسم قيد الأرشفة البرمجية حالياً.", show_alert=True)
        return

    text = f"📂 **أحدث الكتب المضافة في هذا القسم:**\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}️⃣ `{r['file_name']}`\n\n"
        buttons.append([InlineKeyboardButton(f"📥 تحميل كتاب {i}", callback_data=f"dl:{r['file_id']}")])
    buttons.append([InlineKeyboardButton("🔙 العودة للفهرس", callback_data="show_index")])
    
    await query.message.edit_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def show_english_index_menu(update, context):
    query = update.callback_query
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Fiction Novels", callback_data="eng_idx:fiction"), InlineKeyboardButton("🧠 Self-Help & Mind", callback_data="eng_idx:selfhelp")],
        [InlineKeyboardButton("💻 Tech & Coding", callback_data="eng_idx:tech"), InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
    ])
    await query.message.edit_text(text="🇬🇧 **English Library Indexes & Categories:**\n\nSelect a category to view recently indexed publications:", parse_mode="Markdown", reply_markup=keyboard)

async def handle_english_index_selection(update, context):
    query = update.callback_query
    category = query.data.split(":")[1]
    pool = context.bot_data.get("db_conn")
    
    eng_keywords = {"fiction": ["novel", "fiction", "story"], "selfhelp": ["mind", "habit", "power", "rich"], "tech": ["python", "code", "data", "learn"]}
    keywords = eng_keywords.get(category, ["book"])
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT file_id, file_name FROM books
            WHERE file_name ILIKE ANY($1)
            ORDER BY id DESC LIMIT 5;
        """, [f"%{k}%" for k in keywords])

    if not rows:
        await query.answer("🧐 No English books found in this category yet.", show_alert=True)
        return

    text = f"🇬🇧 **Latest English Additions:**\n\n"
    buttons = []
    for i, r in enumerate(rows, 1):
        text += f"{i}️⃣ `{r['file_name']}`\n\n"
        buttons.append([InlineKeyboardButton(f"📥 Download Book {i}", callback_data=f"dl:{r['file_id']}")])
    buttons.append([InlineKeyboardButton("🔙 Back to English Index", callback_data="show_english_index")])
    
    await query.message.edit_text(text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# ===============================================
# تسجيل وتحصيل روابط الإحالة والمستخدمين
# ===============================================
async def register_user(update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data.get("db_conn")
    if not pool or not update.effective_user: return

    user_id = update.effective_user.id
    async with pool.acquire() as conn:
        existing_user = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if not existing_user:
            await conn.execute("INSERT INTO users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)
            inviter_id = None
            if context.args and context.args[0].startswith("inv_"):
                try: inviter_id = int(context.args[0].split("_")[1])
                except: pass
            if inviter_id and inviter_id != user_id:
                try:
                    await conn.execute("UPDATE users SET search_credits = search_credits + 10 WHERE user_id = $1", inviter_id)
                    await context.bot.send_message(
                        chat_id=inviter_id,
                        text="🎉 **شكرًا لك! انضم مستخدم جديد برابط إحالتك، وتم إضافة 10 محاولات إضافية لحسابك!**",
                        parse_mode="Markdown"
                    )
                except Exception as e: logger.error(f"Referral reward failed: {e}")

async def welcome_bot_in_group(update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member or update.my_chat_member
    if not chat_member or chat_member.chat.type not in ("group", "supergroup"): return
    if chat_member.new_chat_member.user.id == context.bot.id and chat_member.new_chat_member.status in ("member", "administrator"):
        group_name = chat_member.chat.title or "المجموعة الثقافية"
        welcome_text = f"🎉 **أهلاً بكم في مجموعة ( {group_name} )!**\n\n🤖 تم تفعيل البوت داخل المجموعة بنجاح.\n📌 للاستخدام اكتب: `/search اسم الكتاب`"
        try: await context.bot.send_message(chat_id=chat_member.chat.id, text=welcome_text, parse_mode="Markdown")
        except: pass

# ===============================================
# إدارة الأزرار التفاعلية وتحميل الملفات (التحميل المباشر)
# ===============================================
async def handle_start_callbacks(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    u_id = query.from_user.id
    if context.application.user_data and dict(context.application.user_data).get(u_id, {}).get("is_banned"):
        try: await query.answer("❌ عذراً، أنت محظور من استخدام البوت.", show_alert=True)
        except: pass
        return

    # 🛡️ الاستجابة الآمنة لمنع انهيار السيرفر بسبب انتهاء وقت الزر
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"⚠️ Callback query expired or invalid: {e}")
        return

    if query.data == "show_index":
        await show_index_menu(update, context)
    elif query.data.startswith("idx:"):
        await handle_index_selection(update, context)
    elif query.data == "show_english_index":
        await show_english_index_menu(update, context)
    elif query.data.startswith("eng_idx:"):
        await handle_english_index_selection(update, context)
    elif query.data == "radar_menu":
        await start_radar_flow(query)
    elif query.data.startswith("rad_cat:"):
        await process_radar_category(query, context)
    elif query.data.startswith("rad_diff:"):
        await process_radar_difficulty(query, context)
    elif query.data.startswith("rad_size:"):
        await execute_radar_search(query, context)
    elif query.data.startswith("dl:"):
        file_id = query.data.split(":")[1]
        try:
            await query.message.reply_document(document=file_id, caption="📚 قراءة ممتعة مفيدة من مكتبتنا الثقافية الرقمية.")
        except Exception as e:
            logger.error(f"Download Error: {e}")
            await query.message.reply_text("❌ **عذراً، هذا الملف تالف أو تم حذفه من خوادم تيليجرام.**", parse_mode="Markdown")
    elif query.data == "show_advertising_info":
        adv_text = "📢 **لقسم الإعلانات ودعم استمرار البوت الرقمي وتغطية تكاليف السيرفرات:**\n\n📩 تواصل مع الإدارة: @UUUULU"
        await query.message.reply_text(text=adv_text, parse_mode="Markdown")
    elif query.data in ("back_to_main", "check_subscription"):
        if await check_subscription(query.from_user.id, context.bot):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
                [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
                [InlineKeyboardButton("💡 مستشارك القرائي (الرادار)", callback_data="radar_menu")],
                [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
                [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
            ])
            await query.message.edit_text(
                text="🌟 *مرحبًا بك في بوت مكتبة الكتب*\n\n🔎 اكتب اسم الكتاب مباشرة للبحث في أزيد من مليون كتاب ورواية مجاناً.",
                parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            link = await get_channel_invite_link(context.bot)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك في القناة هنا", url=link)],
                [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
            ])
            try: await query.message.reply_text(text="🌱 **فضلاً، اشترك في القناة أولاً ليفعل البوت محركات البحث المعرفية!**", parse_mode="Markdown", reply_markup=keyboard)
            except: pass
    elif query.data == "buy_premium":
        text = "⭐ **باقات العضوية المميزة (Premium)**\n\nتحميل غير محدود وتخطي تام للقنوات الإجبارية وأولوية قصوى بالسيرفر.\n\n📩 للتفعيل الفوري تواصل مع الحساب الرسمي: @UUUULU"
        await query.message.reply_text(text=text, parse_mode="Markdown")

# ===============================================
# الأوامر الرئيسية للوحة التحكم والتفاعل البدئي
# ===============================================
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"):
        return
    await register_user(update, context)

    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة هنا", url=link)],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(text="👋 **أهلاً بك! فضلاً، اشترك في القناة أدناه أولاً لتفعيل ميزات البوت مجاناً:**", parse_mode="Markdown", reply_markup=keyboard)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇶 فهرس المكتبة العربية ", callback_data="show_index")],
        [InlineKeyboardButton("🇬🇧 فهرس المكتبة الإنجليزية", callback_data="show_english_index")],
        [InlineKeyboardButton("💡 مستشارك القرائي (الرادار)", callback_data="radar_menu")],
        [InlineKeyboardButton("⭐ اشتراكات البريميوم اللامحدود", callback_data="buy_premium")],
        [InlineKeyboardButton("📢 الاعلان داخل البوت", callback_data="show_advertising_info")]
    ])
    await update.message.reply_text(text="🌟 *مرحبًا بك في بوت مكتبة الكتب الذكي*\n\n📚 ابدأ البحث فوراً بكتابة عنوان الكتاب أو الكلمات المفتاحية في رسالة نصية مباشرة!", parse_mode="Markdown", reply_markup=keyboard)

async def search_books_with_subscription(update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"):
        return
    if not await check_subscription(update.effective_user.id, context.bot):
        link = await get_channel_invite_link(context.bot)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 اشترك في القناة هنا", url=link)],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_subscription")]
        ])
        await update.message.reply_text(text="⚠️ **توقفت عملية البحث! فضلاً اشترك في القناة لتفعيل الحساب:**", parse_mode="Markdown", reply_markup=keyboard)
        return
    await search_books(update, context)

# ===============================================
# استقبال ومعالجة الصور الموفر للاستضافة (إلغاء الـ OCR والوزن الزائد)
# ===============================================
async def handle_photo_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and context.application.user_data and dict(context.application.user_data).get(update.effective_user.id, {}).get("is_banned"):
        return
    await update.message.reply_text(
        text="⚠️ **عذراً، ميزة البحث عبر صور الغلاف غير مفعلة حالياً لتخفيف العبء عن السيرفر وبقاء الخدمة مجانية كلياً وصامتة.**\n\n✍️ فضلاً، اكتب اسم الكتاب أو اسم المؤلف في رسالة نصية مباشرة وسأبحث لك عنه فوراً وبسرعة فائقة!",
        parse_mode="Markdown"
    )

# ===============================================
# دالة التشغيل والانطلاق (Main)
# ===============================================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token: return
    persistence = PicklePersistence(filepath="bot_data.pickle")
    
    global app
    app = Application.builder().token(token).persistence(persistence).post_init(init_db).build()

    # ربط معالج الأخطاء العام لمنع تجمد الـ Polling
    app.add_error_handler(error_handler)

    from admin_panel import register_admin_handlers  
    register_admin_handlers(app, start)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_books_with_subscription))
    app.add_handler(CallbackQueryHandler(handle_start_callbacks))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    
    # توجيه الصور والرسائل النصية لمعالجة آمنة واقتصادية ومستقرة
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo_cover))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, search_books_with_subscription))
    app.add_handler(ChatMemberHandler(welcome_bot_in_group, ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("🚀 The text-based complete book library bot is polling and operational...")
    app.run_polling()

if __name__ == "__main__":
    main()
