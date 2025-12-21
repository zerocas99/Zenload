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

        # Handle group chat messages
        if update.effective_chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            # Try to find URL in the message text first
            url = self._extract_url(message_text)
            
            # If no URL found and it's a reply, check the replied message
            if not url and message.reply_to_message:
                replied_text = message.reply_to_message.text or ''
                url = self._extract_url(replied_text)
            
            # Process the URL if found (no mention required)
            if url:
                # Check if URL is from supported platforms
                downloader = DownloaderFactory.get_downloader(url)
                if downloader:
                    asyncio.create_task(self._process_url(url, update, context))
            # Don't respond to non-URL messages in groups (to avoid spam)
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

    def _is_youtube_url(self, url: str) -> bool:
        """Check if URL is from YouTube (but NOT YouTube Music)"""
        # YouTube Music should be treated as audio, not video with quality selection
        if 'music.youtube.com' in url.lower():
            return False
        youtube_patterns = [
            'youtube.com', 'youtu.be', 'youtube.com/shorts',
            'youtube.com/watch', 'youtube.com/v/', 'youtube.com/embed/'
        ]
        return any(pattern in url.lower() for pattern in youtube_patterns)

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

        # Check if this is YouTube - only YouTube gets quality selection
        is_youtube = self._is_youtube_url(url)
        
        # Create a placeholder message (will be deleted immediately or used for quality selection)
        status_message = None
        if is_youtube:
            try:
                status_message = await update.message.reply_text("⏳")
            except Exception:
                try:
                    status_message = await update.effective_chat.send_message("⏳")
                except:
                    pass

        try:
            # Only get formats for YouTube
            if is_youtube:
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
                        # Delete status message immediately - no need to show it
                        if status_message:
                            try:
                                await status_message.delete()
                            except:
                                pass
                            status_message = None
                        
                        # Create download task without status message
                        download_task = asyncio.create_task(
                            self.download_manager.process_download(
                                downloader, 
                                url, 
                                update, 
                                None,  # No status message
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
                    
                    # Show quality selection keyboard for YouTube
                    if status_message:
                        await status_message.edit_text(
                            self.get_message(user_id, 'select_quality'),
                            reply_markup=self.keyboard_builder.build_format_selection_keyboard(user_id, formats)
                        )
                    return
            
            # For non-YouTube platforms - download immediately with best quality
            # Delete status message if exists
            if status_message:
                try:
                    await status_message.delete()
                except:
                    pass
                status_message = None
            
            # Download with best quality (no format selection)
            download_task = asyncio.create_task(
                self.download_manager.process_download(
                    downloader, 
                    url, 
                    update, 
                    None,  # No status message
                    'best'  # Always best quality for non-YouTube
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
            if status_message:
                try:
                    await status_message.delete()
                except:
                    pass

