[InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ])
        await update.message.reply_text(
            f"🚫 *المعذرة!* الاشتراك في القناة {CHANNEL_USERNAME} هو دليل دعمك لنا.\n\n"
            "اضغط على الزر ثم أعد إرسال الأمر.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # رسالة الترحيب بعد التحقق
    await update.message.reply_text(
        "🎉 أهلاً بك! هذا أول بوت مكتبة سريع من نوعه 📚\n"
        "يمكنك البحث عن أي كتاب مباشرة والحصول عليه في ثوانٍ.\n"
        "تجربة سلسة، واجهة بسيطة، وسرعة عالية.",
        parse_mode="Markdown"
    )

# ===============================================
# تشغيل البوت
# ===============================================
def run_bot():
    token = os.getenv("BOT_TOKEN")
    base_url = os.getenv("WEB_HOST")
    port = int(os.getenv("PORT", 8080))

    if not token:
        logger.error("🚨 BOT_TOKEN not found in environment.")
        return

    app = (
        Application.builder()
        .token(token)
        .post_init(init_db)
        .post_shutdown(close_db)
        .persistence(PicklePersistence(filepath="bot_data.pickle"))
        .build()
    )

    # أوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_books))
    app.add_handler(MessageHandler(filters.Document.PDF & filters.ChatType.CHANNEL, handle_pdf))
    app.add_handler(CallbackQueryHandler(callback_handler))

    register_admin_handlers(app, start)  # لوحة الإدارة

    if base_url:
        webhook_url = f"https://{base_url}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}"
        )
    else:
        logger.info("⚠️ WEB_HOST not available. Running in polling mode.")
        app.run_polling(poll_interval=1.0)

if name == "main":
    run_bot()
