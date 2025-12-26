from typing import Dict, Any

# Language codes should match ISO 639-1
LOCALES: Dict[str, Dict[str, str]] = {
    'ru': {
        'welcome': (
            "⚡ ZeroLoad\n\n"
            "Скачивай видео и музыку одной ссылкой\n\n"
            "📱 Instagram · TikTok · Pinterest\n"
            "🎬 YouTube · SoundCloud\n\n"
            "Просто отправь ссылку →\n\n"
            "👨‍💻 Dev: @zerob1ade"
        ),
        'btn_settings': "⚙️ Настройки",
        'btn_help': "❓ Помощь",
        'btn_language': "🌐 Язык",
        'btn_quality': "📊 Качество",
        'btn_back': "← Назад",
        'btn_russian': "🇷🇺 Русский",
        'btn_english': "🇺🇸 English",
        'btn_ask': "🔄 Спрашивать",
        'btn_best': "⭐ Лучшее",
        'btn_donate': "💝 Донат",
        'help': (
            "📖 Как пользоваться\n\n"
            "1️⃣ Отправь ссылку на видео или музыку\n"
            "2️⃣ Выбери качество (если нужно)\n"
            "3️⃣ Получи файл\n\n"
            "⚙️ Настройки\n"
            "• Язык интерфейса\n"
            "• Качество по умолчанию\n\n"
            "💡 Совет: контент должен быть публичным\n\n"
            "🔧 Технологии\n"
            "Бот использует несколько методов загрузки.\n"
            "Если основной не сработал — автоматически\n"
            "переключается на резервный (JS API)."
        ),
        'unsupported_url': (
            "❌ Ссылка не поддерживается\n\n"
            "✅ Поддерживаются:\n"
            "• Instagram\n"
            "• TikTok\n"
            "• YouTube\n"
            "• Pinterest\n"
            "• SoundCloud"
        ),
        'settings_menu': (
            "⚙️ Настройки\n\n"
            "🌐 Язык: {language}"
        ),
        'processing': "⏳ Обработка...",
        'select_quality': "📊 Выбери качество:",
        'best_quality': "⭐ Лучшее",
        'quality_format': "📹 {quality} ({ext})",
        'select_language': "🌐 Выбери язык:",
        'select_default_quality': "📊 Качество по умолчанию:",
        'ask_every_time': "🔄 Спрашивать",
        'best_available': "⭐ Лучшее",
        'downloading': "📥 Загрузка...",
        'session_expired': "⏰ Сессия истекла. Отправь ссылку заново.",
        'invalid_url': "❌ Неверная ссылка",
        'error_occurred': "❌ Ошибка при обработке запроса",
        'error_file_too_large': "❌ Файл слишком большой (более 500MB). Попробуй выбрать качество 720p.",
        'download_failed': (
            "❌ Ошибка загрузки\n\n"
            "{error}\n\n"
            "💡 Возможные причины:\n"
            "• Приватный аккаунт\n"
            "• Контент удалён\n"
            "• Временная ошибка сервиса"
        ),
        'story_auth_required': (
            "🔒 Stories требуют авторизации\n\n"
            "💡 Попробуй скачать Reels или посты"
        ),
        'auth_required': (
            "🔒 Требуется авторизация\n\n"
            "💡 Возможные причины:\n"
            "• Приватный аккаунт\n"
            "• Контент недоступен"
        ),
        'donate': (
            "💝 Поддержи разработку\n\n"
            "Выбери сумму в Telegram Stars"
        ),
        'invoice_title': "Поддержать ZeroLoad",
        'invoice_description': "Спасибо за поддержку!",
        'price_label': "💝 100 Stars",
        'payment_support': "По вопросам оплаты: @binarybliss",
        'payment_success': "💝 Спасибо за поддержку!",
        'group_welcome': (
            "⚡ ZeroLoad готов к работе\n\n"
            "Отправляйте ссылки — бот скачает автоматически"
        ),
        'group_welcome_admin': (
            "⚡ ZeroLoad активирован\n\n"
            "Отправляйте ссылки — бот скачает автоматически\n\n"
            "⚙️ Настройки группы: /settings"
        ),
        'missing_url': "❌ Укажи ссылку после /zen",
        # Status messages
        'status_getting_info': "🔍 Получение информации... {progress}%",
        'status_downloading': "📥 Загрузка... {progress}%",
        'status_compressing': "🗜️ Сжатие видео... {progress}%",
        'status_processing': "⚙️ Обработка... {progress}%",
        'status_sending': "📤 Отправка... {progress}%",
        'status_fallback': "🔄 Пробую альтернативный метод...",
        'status_done': "✅ Готово!",
        'admin_only': "⛔ Только для администраторов",
        'group_settings_menu': "⚙️ Настройки группы\n\n🌐 Язык: {language}\n📊 Качество: {quality}",
        'settings_unchanged': "✓ Настройки сохранены",
        # Rate limit and concurrent download messages
        'error_too_many_downloads': (
            "⏳ Слишком много загрузок\n\n"
            "Подожди завершения текущих"
        ),
        'error_rate_limit': "⏳ Подожди несколько секунд..."
    },
    'en': {
        'welcome': (
            "⚡ ZeroLoad\n\n"
            "Download videos & music with one link\n\n"
            "📱 Instagram · TikTok · Pinterest\n"
            "🎬 YouTube · SoundCloud\n\n"
            "Just send a link →\n\n"
            "👨‍💻 Dev: @zerob1ade"
        ),
        'btn_settings': "⚙️ Settings",
        'btn_help': "❓ Help",
        'btn_language': "🌐 Language",
        'btn_quality': "📊 Quality",
        'btn_back': "← Back",
        'btn_russian': "🇷🇺 Русский",
        'btn_english': "🇺🇸 English",
        'btn_ask': "🔄 Ask",
        'btn_best': "⭐ Best",
        'btn_donate': "💝 Donate",
        'help': (
            "📖 How to use\n\n"
            "1️⃣ Send a video or music link\n"
            "2️⃣ Choose quality (if needed)\n"
            "3️⃣ Get your file\n\n"
            "⚙️ Settings\n"
            "• Interface language\n"
            "• Default quality\n\n"
            "💡 Tip: content must be public\n\n"
            "🔧 Technology\n"
            "Bot uses multiple download methods.\n"
            "If primary fails — automatically switches\n"
            "to backup method (JS API)."
        ),
        'unsupported_url': (
            "❌ Unsupported link\n\n"
            "✅ Supported:\n"
            "• Instagram\n"
            "• TikTok\n"
            "• YouTube\n"
            "• Pinterest\n"
            "• SoundCloud"
        ),
        'settings_menu': (
            "⚙️ Settings\n\n"
            "🌐 Language: {language}"
        ),
        'processing': "⏳ Processing...",
        'select_quality': "📊 Select quality:",
        'best_quality': "⭐ Best",
        'quality_format': "📹 {quality} ({ext})",
        'select_language': "🌐 Select language:",
        'select_default_quality': "📊 Default quality:",
        'ask_every_time': "🔄 Ask",
        'best_available': "⭐ Best",
        'downloading': "📥 Downloading...",
        'session_expired': "⏰ Session expired. Send link again.",
        'invalid_url': "❌ Invalid link",
        'error_occurred': "❌ Error processing request",
        'error_file_too_large': "❌ File too large (over 500MB). Try selecting 720p quality.",
        'download_failed': (
            "❌ Download failed\n\n"
            "{error}\n\n"
            "💡 Possible reasons:\n"
            "• Private account\n"
            "• Content deleted\n"
            "• Temporary service error"
        ),
        'story_auth_required': (
            "🔒 Stories require authentication\n\n"
            "💡 Try downloading Reels or posts"
        ),
        'auth_required': (
            "🔒 Authentication required\n\n"
            "💡 Possible reasons:\n"
            "• Private account\n"
            "• Content unavailable"
        ),
        'donate': (
            "💝 Support development\n\n"
            "Choose amount in Telegram Stars"
        ),
        'invoice_title': "Support ZeroLoad",
        'invoice_description': "Thank you for your support!",
        'price_label': "💝 100 Stars",
        'payment_support': "Payment support: @binarybliss",
        'payment_success': "💝 Thank you for your support!",
        'group_welcome': (
            "⚡ ZeroLoad is ready\n\n"
            "Send links — bot will download automatically"
        ),
        'group_welcome_admin': (
            "⚡ ZeroLoad activated\n\n"
            "Send links — bot will download automatically\n\n"
            "⚙️ Group settings: /settings"
        ),
        'missing_url': "❌ Provide a link after /zen",
        # Status messages
        'status_getting_info': "🔍 Getting info... {progress}%",
        'status_downloading': "📥 Downloading... {progress}%",
        'status_compressing': "🗜️ Compressing video... {progress}%",
        'status_processing': "⚙️ Processing... {progress}%",
        'status_sending': "📤 Sending... {progress}%",
        'status_fallback': "🔄 Trying alternative method...",
        'status_done': "✅ Done!",
        'admin_only': "⛔ Admins only",
        'group_settings_menu': "⚙️ Group Settings\n\n🌐 Language: {language}\n📊 Quality: {quality}",
        'settings_unchanged': "✓ Settings saved",
        # Rate limit and concurrent download messages
        'error_too_many_downloads': (
            "⏳ Too many downloads\n\n"
            "Wait for current ones to finish"
        ),
        'error_rate_limit': "⏳ Wait a few seconds..."
    }
}

class Localization:
    @staticmethod
    def get(lang: str, key: str, **kwargs) -> str:
        """
        Get localized string by key and format it with provided kwargs
        Falls back to English if key not found in selected language
        """
        try:
            text = LOCALES.get(lang, LOCALES['en'])[key]
            return text.format(**kwargs) if kwargs else text
        except (KeyError, ValueError) as e:
            # Fallback to English if key not found or formatting fails
            try:
                text = LOCALES['en'][key]
                return text.format(**kwargs) if kwargs else text
            except (KeyError, ValueError):
                return f"Missing translation: {key}"
