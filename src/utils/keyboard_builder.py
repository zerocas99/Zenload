from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from typing import Optional

class KeyboardBuilder:
    def __init__(self, localization, settings_manager):
        self.localization = localization
        self.settings_manager = settings_manager

    def get_message(self, user_id: int, key: str, chat_id: Optional[int] = None, is_admin: bool = False, **kwargs) -> str:
        """Get localized message"""
        settings = self.settings_manager.get_settings(user_id, chat_id, is_admin)
        return self.localization.get(settings.language, key, **kwargs)

    def build_main_keyboard(self, user_id: int) -> ReplyKeyboardMarkup:
        """Build main keyboard with common actions - only for private chats"""
        keyboard = [
            [
                KeyboardButton(self.get_message(user_id, 'btn_settings')),
                KeyboardButton(self.get_message(user_id, 'btn_help')),
                KeyboardButton(self.get_message(user_id, 'btn_donate'))
            ]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def build_settings_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Build settings menu keyboard based on context - only language setting"""
        # For groups, add context to callback data
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""
        
        keyboard = [
            [
                InlineKeyboardButton(
                    self.get_message(user_id, 'btn_language', chat_id, is_admin),
                    callback_data=f"settings:language{context}"
                )
            ]
        ]
        
        return InlineKeyboardMarkup(keyboard)

    def build_language_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Build language selection keyboard"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""
        
        keyboard = [
            [
                InlineKeyboardButton(
                    self.get_message(user_id, 'btn_russian', chat_id, is_admin),
                    callback_data=f"set_lang:ru{context}"
                ),
                InlineKeyboardButton(
                    self.get_message(user_id, 'btn_english', chat_id, is_admin),
                    callback_data=f"set_lang:en{context}"
                )
            ],
            [InlineKeyboardButton(
                self.get_message(user_id, 'btn_back', chat_id, is_admin),
                callback_data=f"settings:back{context}"
            )]
        ]
        return InlineKeyboardMarkup(keyboard)

    def build_quality_keyboard(self, user_id: int, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Build quality selection keyboard"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""
        
        keyboard = [
            [InlineKeyboardButton(
                self.get_message(user_id, 'btn_ask', chat_id, is_admin),
                callback_data=f"set_quality:ask{context}"
            )],
            [InlineKeyboardButton(
                self.get_message(user_id, 'btn_best', chat_id, is_admin),
                callback_data=f"set_quality:best{context}"
            )],
            [InlineKeyboardButton(
                self.get_message(user_id, 'btn_back', chat_id, is_admin),
                callback_data=f"settings:back{context}"
            )]
        ]
        return InlineKeyboardMarkup(keyboard)

    def build_format_selection_keyboard(self, user_id: int, formats: list, chat_id: Optional[int] = None, is_admin: bool = False) -> InlineKeyboardMarkup:
        """Build format selection keyboard for YouTube downloads - compact design"""
        context = f":{chat_id}" if chat_id and chat_id < 0 else ""
        
        # Create row with video quality buttons (720p, 1080p side by side)
        video_buttons = []
        
        # Find 720p and 1080p formats
        has_720 = any(f['quality'] == '720p' for f in formats)
        has_1080 = any(f['quality'] == '1080p' for f in formats)
        
        if has_720:
            video_buttons.append(InlineKeyboardButton(
                "🎬 720p",
                callback_data=f"quality:720{context}"
            ))
        
        if has_1080:
            # Add hourglass emoji if 1080p (takes longer)
            video_buttons.append(InlineKeyboardButton(
                "🎬 1080p (⏳)",
                callback_data=f"quality:1080{context}"
            ))
        
        keyboard = []
        
        # Add video buttons row
        if video_buttons:
            keyboard.append(video_buttons)
        
        # Add audio button on separate row
        keyboard.append([InlineKeyboardButton(
            "🎵 Audio",
            callback_data=f"quality:audio{context}"
        )])
        
        return InlineKeyboardMarkup(keyboard)

