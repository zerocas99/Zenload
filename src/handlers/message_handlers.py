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
        if not url:
            return False
        url_lower = url.lower()
        return any(domain in url_lower for domain in ['youtube.com', 'youtu.be', 'music.youtube.com'])



    async def _process_url(self, url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process URL from message or command"""
        user_id = update.effective_user.id
        
        # Get downloader for URL
        downloader = DownloaderFactory.get_downloader(url)
        if not downloader:
            try:
                await update.message.reply_text(
                    self.get_message(user_id, 'unsupported_url')
                )
            except Exception:
                await update.effective_chat.send_message(
                    self.get_message(user_id, 'unsupported_url')
                )
            return

        # Check if this is Instagram all stories URL
        if hasattr(downloader, '_is_all_stories_url') and downloader._is_all_stories_url(url):
            await self._process_all_stories(url, update, downloader)
            return

        is_youtube = self._is_youtube_url(url)
        status_message = None

        try:
            if is_youtube:
                try:
                    status_message = await update.message.reply_text("Loading video info...")
                except Exception:
                    try:
                        status_message = await update.effective_chat.send_message("Loading video info...")
                    except Exception:
                        pass
                
                formats = await downloader.get_formats(url)
                video_info = await downloader.get_video_info(url)
                
                # Store URL in context for callback
                if not context.user_data:
                    context.user_data.clear()
                context.user_data['pending_url'] = url

                title = (video_info or {}).get('title', 'YouTube')
                caption = f"Video: {title}"
                thumbnail_url = (video_info or {}).get('thumbnail')
                
                if status_message:
                    try:
                        await status_message.delete()
                    except Exception:
                        pass
                    status_message = None
                
                keyboard = self.keyboard_builder.build_format_selection_keyboard(user_id, formats or [])
                
                if thumbnail_url:
                    try:
                        await update.message.reply_photo(
                            photo=thumbnail_url,
                            caption=caption,
                            reply_markup=keyboard
                        )
                        return
                    except Exception as e:
                        logger.debug(f"Failed to send thumbnail: {e}")
                
                await update.message.reply_text(
                    caption,
                    reply_markup=keyboard
                )
                return
            
            # For non-YouTube platforms - download immediately with best quality
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
                status_message = None
            
            # Check if this is Instagram story - always download all stories
            is_instagram_story = (
                hasattr(downloader, '_is_story_url') and 
                downloader._is_story_url(url)
            )
            
            if is_instagram_story:
                # For Instagram stories - always download all stories from user
                download_task = asyncio.create_task(
                    self._process_all_stories(url, update, downloader)
                )
            else:
                # Normal download
                download_task = asyncio.create_task(
                    self.download_manager.process_download(
                        downloader, 
                        url, 
                        update, 
                        None,
                        'best'
                    )
                )
            
            task_key = f"{user_id}:{url}"
            self._download_tasks[task_key] = download_task
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
                except Exception:
                    pass

    async def _download_instagram_story_with_fallback(self, downloader, url: str, update: Update):
        """Download Instagram story: try Cobalt for specific story, fallback to all stories"""
        from ..utils.cobalt_service import cobalt
        import aiohttp
        from pathlib import Path
        
        user_id = update.effective_user.id
        settings = self.settings_manager.get_settings(user_id)
        lang = settings.language
        
        # Try Cobalt first for specific story
        logger.info(f"[Instagram] Trying Cobalt for specific story: {url}")
        
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=15
            )
            
            if result.success and result.url:
                # Cobalt worked! Download and send
                logger.info("[Instagram] Cobalt success for specific story")
                
                download_dir = Path(__file__).parent.parent / "downloads"
                download_dir.mkdir(exist_ok=True)
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        result.url,
                        headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status == 200:
                            content = await response.read()
                            
                            # Detect type
                            is_video = len(content) > 8 and content[4:8] == b'ftyp'
                            ext = 'mp4' if is_video else 'jpg'
                            filename = f"story_{hash(url) % 100000}.{ext}"
                            file_path = download_dir / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(content)
                            
                            # Send to user
                            if lang == 'ru':
                                caption = "📥 Скачано через @ZeroLoader_Bot\n👨‍💻 Разработчик: @zerob1ade"
                            else:
                                caption = "📥 Downloaded via @ZeroLoader_Bot\n👨‍💻 Dev: @zerob1ade"
                            
                            with open(file_path, 'rb') as f:
                                if is_video:
                                    await update.effective_message.reply_video(
                                        video=f,
                                        caption=caption,
                                        supports_streaming=True
                                    )
                                else:
                                    await update.effective_message.reply_photo(
                                        photo=f,
                                        caption=caption
                                    )
                            
                            # Cleanup
                            try:
                                file_path.unlink()
                            except:
                                pass
                            
                            return
                            
        except Exception as e:
            logger.info(f"[Instagram] Cobalt failed for specific story: {e}")
        
        # Cobalt failed - download all stories
        logger.info("[Instagram] Falling back to all stories")
        await self._process_all_stories(url, update, downloader)

    async def _process_all_stories(self, url: str, update: Update, downloader):
        """Process all Instagram stories from a user"""
        user_id = update.effective_user.id
        
        # Get language for messages
        settings = self.settings_manager.get_settings(user_id)
        lang = settings.language
        
        # Send loading message
        if lang == 'ru':
            loading_msg = await update.message.reply_text("⏳ Загружаю все сторис...")
        else:
            loading_msg = await update.message.reply_text("⏳ Loading all stories...")
        
        try:
            # Download all stories
            stories = await downloader.download_all_stories(url)
            
            if not stories:
                await loading_msg.edit_text(
                    "❌ Не найдено сторис" if lang == 'ru' else "❌ No stories found"
                )
                return
            
            # Update message
            count = len(stories)
            if lang == 'ru':
                await loading_msg.edit_text(f"📤 Отправляю {count} сторис...")
            else:
                await loading_msg.edit_text(f"📤 Sending {count} stories...")
            
            # Send each story
            sent = 0
            for metadata, file_path, media_type in stories:
                try:
                    with open(file_path, 'rb') as f:
                        if media_type == 'video':
                            await update.effective_chat.send_video(
                                video=f,
                                supports_streaming=True,
                                read_timeout=60,
                                write_timeout=60
                            )
                        else:
                            await update.effective_chat.send_photo(
                                photo=f,
                                read_timeout=30,
                                write_timeout=30
                            )
                    sent += 1
                    
                    # Clean up file
                    try:
                        file_path.unlink()
                    except:
                        pass
                        
                except Exception as e:
                    logger.warning(f"Failed to send story: {e}")
                    continue
            
            # Final message
            if lang == 'ru':
                caption = f"📥 Скачано {sent} сторис через @ZeroLoader_Bot\n👨‍💻 Разработчик: @zerob1ade"
            else:
                caption = f"📥 Downloaded {sent} stories via @ZeroLoader_Bot\n👨‍💻 Dev: @zerob1ade"
            
            await loading_msg.edit_text(caption)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"All stories download failed: {error_msg}")
            
            if lang == 'ru':
                await loading_msg.edit_text(f"❌ Ошибка: {error_msg}")
            else:
                await loading_msg.edit_text(f"❌ Error: {error_msg}")
