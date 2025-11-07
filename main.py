import os
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext._updater import Updater
from telegram.ext import PicklePersistence

# Import the admin module
from admin_panel import register_admin_handlers 

# ===============================================
#       Core Database & Setup Functions
# ===============================================

# 1. Initialize the database connection and setup FTS
async def init_db(app_context: ContextTypes):
    """Initializes the database connection, enables Full-Text Search extensions, and sets up tables."""
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("🚨 DATABASE_URL environment variable is missing.")
            return

        conn = await asyncpg.connect(db_url)
        
        # 1. Enable necessary extensions for FTS (unaccent is crucial for Arabic normalization)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
        
        # 2. Create a custom Arabic search configuration that uses unaccent
        await conn.execute("""
            CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS arabic_simple (PARSER = default);
            ALTER TEXT SEARCH CONFIGURATION arabic_simple 
            ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part 
            WITH unaccent, simple;
        """)

        # 3. Create Tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,  
                file_name TEXT,
                uploaded_at TIMESTAMP DEFAULT NOW(),
                -- Column for FTS indexing
                tsv_content tsvector
            );
            
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                joined_at TIMESTAMP DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        
        # 4. Create GIN index for fast FTS lookups
        await conn.execute("CREATE INDEX IF NOT EXISTS tsv_idx ON books USING GIN (tsv_content);")

        # 5. Create Trigger Function to automatically update tsv_content on insert/update
        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_books_tsv() RETURNS trigger AS $$
            BEGIN
                -- Use the custom arabic_simple configuration for Arabic FTS
                NEW.tsv_content := to_tsvector('arabic_simple', NEW.file_name);
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        # 6. Apply the Trigger
        await conn.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger 
                    WHERE tgname = 'tsv_update_trigger'
                ) THEN
                    CREATE TRIGGER tsv_update_trigger
                    BEFORE INSERT OR UPDATE OF file_name ON books
                    FOR EACH ROW EXECUTE FUNCTION update_books_tsv();
                END IF;
            END $$;
        """)
        
        app_context.bot_data['db_conn'] = conn
        print("✅ Database connection and FTS setup complete.")
    except Exception as e:
        print(f"❌ Database connection or setup error: {e}")
        # Continue running even if DB fails initially
        print("🚨 Will continue without database connection.")

# 2. Close DB connection
async def close_db(app: Application):
    """Closes the database connection on shutdown."""
    conn = app.bot_data.get('db_conn')
    if conn:
        await conn.close()
        print("✅ Database connection closed.")

# 3. PDF Handler (Automatic Indexing)
async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Indexes any new PDF file received in the channel."""
    if update.channel_post and update.channel_post.document and update.channel_post.document.mime_type == "application/pdf":
        
        document = update.channel_post.document
        conn = context.bot_data.get('db_conn')
        
        if conn:
            try:
                # The tsv_content column will be updated automatically by the trigger
                await conn.execute(
                    "INSERT INTO books(file_id, file_name) VALUES($1, $2) ON CONFLICT (file_id) DO NOTHING", 
                    document.file_id, 
                    document.file_name
                )
                print(f"Book indexed: {document.file_name}")
            except Exception as e:
                print(f"Error indexing book: {e}") 

# 4. /search command (FTS)
async def search_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Searches for up to 10 matching books using Full-Text Search."""
    if update.effective_chat.type == "channel":
        return

    if not context.args:
        await update.message.reply_text("الرجاء إرسال اسم الكتاب. مثال: /search اسم الكتاب")
        return
    
    search_term = " ".join(context.args).strip()
    
    conn = context.bot_data.get('db_conn')

    if conn:
        # Use simple search config: replace spaces with '&' (AND operator in FTS)
        query_text = search_term.replace(' ', ' & ')
        
        # FTS Query: Use @@ operator against the indexed tsv_content column
        search_query = """
            SELECT file_id, file_name 
            FROM books 
            WHERE tsv_content @@ to_tsquery('arabic_simple', $1)
            ORDER BY file_name ASC 
            LIMIT 10
        """

        results = await conn.fetch(
            search_query,
            query_text
        )

        if results:
            if len(results) == 1:
                # Send file directly if only one result
                file_id = results[0]['file_id']
                book_name = results[0]['file_name']
                
                try:
                    await update.message.reply_document(
                        document=file_id, 
                        caption=f"✅ تم العثور على الكتاب: **{book_name}**"
                    )
                except Exception:
                    await update.message.reply_text("❌ لم أتمكن من إرسال الملف. قد يكون الملف غير صالح أو واجهت مشكلة في تيليجرام.")
            
            else:
                # Show multiple results in Inline buttons
                
                message_text = f"📚 تم العثور على **{len(results)}** كتاباً يطابق بحثك '{search_term}':\n\n"
                message_text += "الرجاء اختيار النسخة المطلوبة من القائمة أدناه:"
                
                keyboard = []
                for result in results:
                    # Use unique callback_data: "file:<file_id_partial>"
                    callback_data = f"file:{result['file_id'][:50]}" 
                    
                    keyboard.append([InlineKeyboardButton(f"🔗 {result['file_name']}", callback_data=callback_data)])
                    
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        else:
            await update.message.reply_text(f"❌ لم يتم العثور على كتاب يطابق '{search_term}'.")
    else:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات حالياً. حاول لاحقاً.")

# 5. /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في مكتبة البوت! 📚\n"
        "للبحث عن كتاب، استخدم الأمر: /search اسم الكتاب"
    )

# 6. Main Runner Function
def run_bot():
    """Uses Webhook for hosting environments like Railway, with Polling fallback."""
    token = os.getenv("BOT_TOKEN")
    port = int(os.environ.get('PORT', 8080))
    base_url = os.environ.get('WEB_HOST')
    
    # Check for mandatory environment variables
    if not token:
        raise ValueError("BOT_TOKEN is missing in environment variables.")

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)     # Open connection and setup DB
        .post_shutdown(close_db) # Close connection
        .persistence(PicklePersistence(filepath="bot_data.pickle")) # Temp storage
        .build()
    )
    
    original_start_handler = start
    
    app.add_handler(CommandHandler("search", search_book))
    app.add_handler(MessageHandler(
        filters.Document.PDF & filters.ChatType.CHANNEL,
        handle_pdf
    ))

    # Register admin handlers (includes tracking logic)
    register_admin_handlers(app, original_start_handler)

    
    # Run Webhook if WEB_HOST is available, otherwise fall back to Polling
    if base_url:
        webhook_url = f'https://{base_url}'
        
        print(f"🤖 Running bot via Webhook on: {webhook_url}:{port}")
        
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token, 
            webhook_url=f"{webhook_url}/{token}",
            secret_token=os.getenv("WEBHOOK_SECRET")
        )
    else:
        print("⚠️ WEB_HOST not available. Falling back to Polling mode. Ensure only one instance is running.")
        app.run_polling(poll_interval=1.0)


def run_polling_fallback(token):
    """Fallback function for Polling mode (used internally by run_bot)."""
    # This function is not used directly externally, but left for completeness/debugging.
    # The run_bot function handles the fallback logic now.
    pass


if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"Fatal error occurred: {e}")
