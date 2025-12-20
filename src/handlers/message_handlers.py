import logging
from telegram import Update, Chat
from telegram.ext import ContextTypes
import re
from ..downloaders import DownloaderFactory
import asyncio

logger = logging.getLogger(__name__)

class MessageHandlers:
    def __init__(self, keyboard_builder, settings_manager, download_manager, localization, activity_logger=None):
        self.keyboard_builder = keyboard_builder
        self.settings_manager = settings_manager
        self.download_manager = download_manager
        self.localization = localization
        self.activity_logger = activity_logger
        self._download_tasks = {}

    def get_message(self, user_id: int, key: str, **kwargs) -> str:
        """Get localized message"""
        settings = self.settings_manager.get_settings(user_id)
        language = settings.language
        return self.localization.get(language, key, **kwargs)
        
    def _extract_url(self, text: str) -> str:
        """Extract URL from text"""
        if not text:
            return None
        # URL extraction with support for various URL formats
        urls = re.findall(r'https?://[^\s]+', text)
        return urls[0] if urls else None

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages with URLs"""
        message = update.message
        user_id = update.effective_user.id
        
        # Update user information with each message
        user = update.effective_user
        self.settings_manager.update_settings(
            user_id=user_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            is_premium=user.is_premium if hasattr(user, 'is_premium') else False
        )

        message_text = message.text or ''

        # Handle group chat messages with bot mention
        if update.effective_chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            # Check if our bot is actually mentioned
            bot_username = context.bot.username
            if not bot_username or f"@{bot_username}" not in message_text:
                # Not our bot being mentioned
                return
                
            # Try to find URL in the message text first
            url = self._extract_url(message_text)
            
            # If no URL found and it's a reply, check the replied message
            if not url and message.reply_to_message:
                replied_text = message.reply_to_message.text
                url = self._extract_url(replied_text)
            
            # Process the URL if found
            if url:
                asyncio.create_task(self._process_url(url, update, context))
            else:
                # Try to send message without reply if we don't have admin rights
                try:
                    await message.reply_text(
                        self.get_message(user_id, 'unsupported_url')
                    )
                except Exception:
                    await update.effective_chat.send_message(
                        self.get_message(user_id, 'unsupported_url')
                    )
            return

        # Handle private chat messages (we already returned for non-private above)
        message_text = message.text.strip()

        # Handle keyboard shortcuts first
        if await self._handle_keyboard_shortcuts(message_text, user_id, update, context):
            return

        # Process URL
        url = self._extract_url(message_text)
        if url:
            asyncio.create_task(self._process_url(url, update, context))
        else:
            await message.reply_text(self.get_message(user_id, 'unsupported_url'))
            
    async def _handle_keyboard_shortcuts(self, message_text: str, user_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Handle keyboard shortcuts and return True if handled"""
        from .command_handlers import CommandHandlers

        if message_text == self.get_message(user_id, 'btn_settings'):
            await CommandHandlers(self.keyboard_builder, self.settings_manager, self.localization).settings_command(update, context)
            return True
        elif message_text == self.get_message(user_id, 'btn_help'):
            await CommandHandlers(self.keyboard_builder, self.settings_manager, self.localization).help_command(update, context)
            return True
        elif message_text == self.get_message(user_id, 'btn_donate'):
            await CommandHandlers(self.keyboard_builder, self.settings_manager, self.localization).donate_command(update, context)
            return True

        return False

    async def _process_url(self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process URL from message or command"""
        user_id = update.effective_user.id
        
        # Get downloader for URL
        downloader = DownloaderFactory.get_downloader(url)
        if not downloader:
            try:
                # Try to reply first
                await update.message.reply_text(
                    self.get_message(user_id, 'unsupported_url')
                )
            except Exception:
                # If can't reply (no admin rights), send without reply
                await update.effective_chat.send_message(
                    self.get_message(user_id, 'unsupported_url')
                )
            return

        # Send initial status
        try:
            status_message = await update.message.reply_text(
                self.get_message(user_id, 'processing')
            )
        except Exception:
            # If can't reply (no admin rights), try without reply
            status_message = await update.effective_chat.send_message(
                self.get_message(user_id, 'processing')
            )

        if not status_message:
            return  # Can't send messages at all

        try:
            # Get available formats
            formats = await downloader.get_formats(url)
            
            if formats:
                # Store URL in context for callback
                if not context.user_data:
                    context.user_data.clear()
                context.user_data['pending_url'] = url

                # Get user settings
                settings = self.settings_manager.get_settings(user_id)
                
                # If default quality is set and not 'ask', start download
                if settings.default_quality != 'ask':
                    # Create download task
                    download_task = asyncio.create_task(
                        self.download_manager.process_download(
                            downloader, 
                            url, 
                            update, 
                            status_message, 
                            settings.default_quality
                        )
                    )
                    
                    # Store task reference
                    task_key = f"{user_id}:{url}"
                    self._download_tasks[task_key] = download_task
                    
                    # Clean up task when done
                    download_task.add_done_callback(
                        lambda t: self._download_tasks.pop(task_key, None)
                    )
                    return
                
                # Show quality selection keyboard
                await status_message.edit_text(
                    self.get_message(user_id, 'select_quality'),
                    reply_markup=self.keyboard_builder.build_format_selection_keyboard(user_id, formats)
                )
            else:
                # If no formats available, download with default settings
                # Create download task
                download_task = asyncio.create_task(
                    self.download_manager.process_download(
                        downloader, 
                        url, 
                        update, 
                        status_message
                    )
                )
                
                # Store task reference
                task_key = f"{user_id}:{url}"
                self._download_tasks[task_key] = download_task
                
                # Clean up task when done
                download_task.add_done_callback(
                    lambda t: self._download_tasks.pop(task_key, None)
                )

        except Exception as e:
            try:
                await update.message.reply_text(
                    self.get_message(user_id, 'error_occurred')
                )
            except Exception:
                await update.effective_chat.send_message(
                    self.get_message(user_id, 'error_occurred')
                )
            logger.error(f"Unexpected error processing {url}: {e}")
            await status_message.delete()

