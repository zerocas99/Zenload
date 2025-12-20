import logging
from pathlib import Path
from telegram import Update, Message
from telegram.error import BadRequest
from ..downloaders import DownloadError
import asyncio
from functools import partial
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from typing import Dict, Optional, Set
import time
from collections import defaultdict

# Configure logging to prevent duplicates
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class DownloadWorker:
    """Worker class to handle individual downloads"""
    def __init__(self, localization, settings_manager, session: aiohttp.ClientSession, activity_logger=None, keyboard_builder=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.session = session
        self.activity_logger = activity_logger
        self.keyboard_builder = keyboard_builder
        self._status_queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._current_message: Optional[Message] = None
        self._current_user_id: Optional[int] = None
        self._last_status: Optional[str] = None
        self._last_progress: Optional[int] = None
        self._status_task: Optional[asyncio.Task] = None
        self._last_update_time = 0
        self._update_interval = 0.3  # Faster status updates

    def get_message(self, user_id: int, key: str, **kwargs) -> str:
        """Get localized message"""
        settings = self.settings_manager.get_settings(user_id)
        language = settings.language
        return self.localization.get(language, key, **kwargs)

    async def update_status(self, message: Message, user_id: int, status_key: str, progress: int):
        """Update status message with current progress"""
        try:
            # Rate limit status updates
            current_time = time.time()
            if current_time - self._last_update_time < self._update_interval:
                return

            new_text = self.get_message(user_id, status_key, progress=progress)
            if new_text == self._last_status and progress == self._last_progress:
                return

            try:
                await asyncio.wait_for(message.edit_text(new_text), timeout=2.0)
                self._last_status = new_text
                self._last_progress = progress
                self._last_update_time = current_time
            except asyncio.TimeoutError:
                logger.debug("Status update timed out, skipping")
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error updating status: {e}")
        except Exception as e:
            logger.error(f"Error updating status: {e}")

    async def _process_status_updates(self):
        """Process status updates asynchronously"""
        try:
            while not self._stop_event.is_set():
                try:
                    status, progress = await asyncio.wait_for(
                        self._status_queue.get(),
                        timeout=0.1
                    )
                    if status == "STOP":
                        break

                    if self._current_message and self._current_user_id:
                        await self.update_status(
                            self._current_message,
                            self._current_user_id,
                            status,
                            progress
                        )
                        self._status_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing status update: {e}")
        except asyncio.CancelledError:
            pass

    async def progress_callback(self, status: str, progress: int):
        """Async callback for progress updates"""
        try:
            await self._status_queue.put((status, progress))
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")

    async def _try_direct_url_send(self, update: Update, direct_url: str, is_audio: bool = False, caption: str = None, is_photo: bool = False) -> bool:
        """Try to send media directly via URL (fast method). Returns True if successful."""
        try:
            if is_audio:
                await update.effective_message.reply_audio(
                    audio=direct_url,
                    caption=caption,
                    parse_mode='HTML',
                    read_timeout=20,
                    write_timeout=20,
                    connect_timeout=5,
                    pool_timeout=5
                )
            elif is_photo:
                await update.effective_message.reply_photo(
                    photo=direct_url,
                    caption=caption,
                    parse_mode='HTML',
                    read_timeout=20,
                    write_timeout=20,
                    connect_timeout=5,
                    pool_timeout=5
                )
            else:
                await update.effective_message.reply_video(
                    video=direct_url,
                    caption=caption,
                    parse_mode='HTML',
                    supports_streaming=True,
                    read_timeout=20,
                    write_timeout=20,
                    connect_timeout=5,
                    pool_timeout=5
                )
            return True
        except Exception as e:
            logger.debug(f"Direct URL send failed: {e}")
            return False

    async def _send_audio_auto(self, update: Update, audio_url: str, user_id: int):
        """Automatically send audio after video (for TikTok music)"""
        try:
            # Try sending audio directly via URL
            await update.effective_message.reply_audio(
                audio=audio_url,
                caption="🎵",
                read_timeout=30,
                write_timeout=30,
                connect_timeout=10,
                pool_timeout=10
            )
            logger.info("Auto audio send successful")
        except Exception as e:
            logger.debug(f"Auto audio send failed: {e}")
            # Try downloading and sending
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(audio_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            audio_data = await resp.read()
                            if len(audio_data) > 1000:  # Verify it's not empty
                                from io import BytesIO
                                audio_file = BytesIO(audio_data)
                                audio_file.name = "audio.mp3"
                                await update.effective_message.reply_audio(
                                    audio=audio_file,
                                    caption="🎵"
                                )
                                logger.info("Auto audio send via download successful")
            except Exception as e2:
                logger.debug(f"Auto audio download failed: {e2}")

    async def _send_media_group(self, update: Update, image_urls: list, caption: str = None) -> bool:
        """Send multiple images as a media group (for TikTok slideshows)"""
        try:
            from telegram import InputMediaPhoto
            
            # Telegram allows max 10 items in media group
            images_to_send = image_urls[:10]
            
            media_group = []
            for i, img_url in enumerate(images_to_send):
                # Only first image gets caption
                if i == 0 and caption:
                    media_group.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode='HTML'))
                else:
                    media_group.append(InputMediaPhoto(media=img_url))
            
            await update.effective_message.reply_media_group(
                media=media_group,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=10,
                pool_timeout=10
            )
            logger.info(f"Media group sent successfully ({len(images_to_send)} images)")
            return True
        except Exception as e:
            logger.debug(f"Media group send failed: {e}")
            return False

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None) -> None:
        """Process content download with error handling and cleanup"""
        user_id = update.effective_user.id
        file_path = None
        start_time = time.time()

        # Log download attempt if logger is available
        if self.activity_logger:
            self.activity_logger.log_download_attempt(user_id, url, downloader.__class__.__name__.lower())

        try:
            logger.info(f"Starting download for URL: {url}")
            
            # Reset state
            self._last_status = None
            self._last_progress = None
            self._current_message = status_message
            self._current_user_id = user_id
            self._stop_event.clear()
            self._last_update_time = 0
            
            # Start status update task
            self._status_task = asyncio.create_task(self._process_status_updates())
            
            # Set up progress callback
            downloader.set_progress_callback(self.progress_callback)
            
            # Initial status
            await self.update_status(status_message, user_id, 'status_getting_info', 0)
            
            # Try to get direct URL first (fast method)
            direct_url = None
            is_audio = False
            metadata = None
            audio_url = None
            is_photo = False
            all_images = None
            
            if hasattr(downloader, 'get_direct_url'):
                try:
                    result = await downloader.get_direct_url(url)
                    # Handle 3-tuple, 4-tuple, 5-tuple, and 6-tuple returns
                    if len(result) == 6:
                        direct_url, metadata, is_audio, audio_url, is_photo, all_images = result
                    elif len(result) == 5:
                        direct_url, metadata, is_audio, audio_url, is_photo = result
                        all_images = None
                    elif len(result) == 4:
                        direct_url, metadata, is_audio, audio_url = result
                        is_photo = False
                        all_images = None
                    else:
                        direct_url, metadata, is_audio = result
                        audio_url = None
                        is_photo = False
                        all_images = None
                    
                    # Add dev credit to metadata for direct URL sends
                    if direct_url:
                        settings = self.settings_manager.get_settings(user_id)
                        lang = settings.language
                        if lang == 'ru':
                            dev_credit = "\n\n📥 Скачано через @ZeroLoader_Bot\n👨‍💻 Разработчик: @zerob1ade"
                        else:
                            dev_credit = "\n\n📥 Downloaded via @ZeroLoader_Bot\n👨‍💻 Dev: @zerob1ade"
                        
                        if metadata:
                            metadata = metadata + dev_credit
                        else:
                            metadata = dev_credit.strip()
                    
                    if direct_url:
                        logger.info(f"Got direct URL, trying fast send... (photo={is_photo}, images={len(all_images) if all_images else 0})")
                        
                        # If multiple images (TikTok slideshow), send as media group
                        if is_photo and all_images and len(all_images) > 1:
                            if await self._send_media_group(update, all_images, metadata):
                                logger.info("Media group send successful!")
                                
                                # Send audio after slideshow if available
                                if audio_url:
                                    await self._send_audio_auto(update, audio_url, user_id)
                                
                                await status_message.edit_text("✅ @zerob1ade")
                                return
                        elif await self._try_direct_url_send(update, direct_url, is_audio, metadata, is_photo):
                            logger.info("Fast direct URL send successful!")
                            
                            # Auto-send audio if available (TikTok music) - but NOT for photos
                            if audio_url and not is_audio and not is_photo:
                                await self._send_audio_auto(update, audio_url, user_id)
                            
                            await status_message.edit_text("✅ @zerob1ade")
                            return
                        logger.info("Direct URL send failed, falling back to download...")
                except Exception as e:
                    logger.debug(f"get_direct_url failed: {e}")
            
            # Fallback: Download content to server
            result = await downloader.download(url, format_id)
            metadata, file_path = result
            logger.info(f"Download completed. File path: {file_path}")
            
            # Add dev credit to metadata
            settings = self.settings_manager.get_settings(user_id)
            lang = settings.language
            if lang == 'ru':
                dev_credit = "\n\n📥 Скачано через @ZeroLoader_Bot\n👨‍💻 Разработчик: @zerob1ade"
            else:
                dev_credit = "\n\n📥 Downloaded via @ZeroLoader_Bot\n👨‍💻 Dev: @zerob1ade"
            
            if metadata:
                metadata = metadata + dev_credit
            else:
                metadata = dev_credit.strip()
            
            # Sending phase
            await self.update_status(status_message, user_id, 'status_sending', 0)
            logger.info("Sending file to Telegram...")
            
            # Determine file type by extension
            file_ext = file_path.suffix.lower()
            is_audio_file = file_ext in ['.mp3', '.m4a', '.wav', '.ogg', '.flac']
            is_photo_file = file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            
            with open(file_path, 'rb') as file:
                if is_audio_file:
                    await update.effective_message.reply_audio(
                        audio=file,
                        caption=metadata,
                        parse_mode='HTML',
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=10,
                        pool_timeout=10
                    )
                elif is_photo_file:
                    await update.effective_message.reply_photo(
                        photo=file,
                        caption=metadata,
                        parse_mode='HTML',
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=10,
                        pool_timeout=10
                    )
                else:
                    await update.effective_message.reply_video(
                        video=file,
                        caption=metadata,
                        parse_mode='HTML',
                        supports_streaming=True,
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=10,
                        pool_timeout=10
                    )
            await self.update_status(status_message, user_id, 'status_sending', 100)
            logger.info("File sent successfully")

        except DownloadError as e:
            error_message = str(e)
            await update.effective_message.reply_text(
                self.get_message(user_id, 'download_failed', error=error_message)
            )
            logger.error(f"Download error for {url}: {error_message}")

        except Exception as e:
            await update.effective_message.reply_text(
                self.get_message(user_id, 'error_occurred')
            )
            logger.error(f"Unexpected error processing {url}: {e}", exc_info=True)

        finally:
            # Calculate processing time
            processing_time = time.time() - start_time
            
            # Log download completion if logger is available
            if self.activity_logger:
                success = file_path is not None  # If we have a file_path, download was successful
                file_ext = Path(file_path).suffix.lower() if file_path else ''
                if file_ext in ['.mp3', '.m4a', '.wav', '.ogg', '.flac']:
                    file_type = 'audio'
                elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    file_type = 'photo'
                else:
                    file_type = 'video'
                file_size = Path(file_path).stat().st_size if file_path else None
                error_type = str(e) if 'e' in locals() else None
                
                self.activity_logger.log_download_complete(
                    user_id=user_id,
                    url=url,
                    success=success,
                    file_type=file_type,
                    file_size=file_size,
                    processing_time=processing_time,
                    error=error_type
                )

            # Stop status update task
            self._stop_event.set()
            if self._status_task:
                await self._status_queue.put(("STOP", 0))
                self._status_task.cancel()
                try:
                    await self._status_task
                except asyncio.CancelledError:
                    pass

            # Clear state
            self._current_message = None
            self._current_user_id = None
            self._last_status = None
            self._last_progress = None

            # Cleanup downloaded file
            if file_path:
                try:
                    Path(file_path).unlink()
                    logger.info(f"Cleaned up file: {file_path}")
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")

            # Edit status message to show completion with dev credit
            try:
                await status_message.edit_text("✅ @zerob1ade")
                logger.info("Status message updated to done")
            except Exception as e:
                logger.debug(f"Error updating status message: {e}")

class DownloadManager:
    """High-performance download manager with optimized concurrency"""
    def __init__(self, localization, settings_manager, max_concurrent_downloads=50, max_downloads_per_user=5, activity_logger=None, keyboard_builder=None):
        self.localization = localization
        self.settings_manager = settings_manager
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_downloads_per_user = max_downloads_per_user
        self.activity_logger = activity_logger
        self.keyboard_builder = keyboard_builder
        
        # Audio URL cache for callback handling
        self.audio_cache: Dict[int, str] = {}
        
        # Initialize as None, will create when needed
        self.connector = None
        self.session = None
        self._loop = None
        
        # Active downloads tracking
        self.active_downloads: Dict[int, Dict[str, asyncio.Task]] = defaultdict(dict)
        self._downloads_lock = None
        
        # Download queue
        self.download_queue = None
        self._queue_processor_task = None
        self._queue_processor_running = False
        
        # Rate limiting per domain
        self.rate_limits: Dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(10)  # Increased from 5 to 10
        )

    async def _create_queue(self):
        """Create a new queue bound to the current event loop"""
        try:
            # Get current event loop or create new one if needed
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

            # Safely cleanup old queue if it exists
            if self.download_queue:
                try:
                    if not self.download_queue.empty():
                        await asyncio.wait_for(self.download_queue.join(), timeout=5.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Could not properly clean old queue: {e}")
                self.download_queue = None

            # Create new queue bound to current event loop
            self.download_queue = asyncio.PriorityQueue()
            logger.info("Successfully created new download queue")
        except Exception as e:
            logger.error(f"Error creating queue: {e}")
            # Don't raise, let the system try to recover
            self.download_queue = None

    async def _ensure_initialized(self):
        """Ensure manager is initialized with event loop"""
        try:
            # Get or create event loop
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(current_loop)
                current_loop = asyncio.get_running_loop()

            needs_init = (
                not self._loop or
                self._loop != current_loop or
                not self.session or
                self.session.closed
            )

            if needs_init:
                logger.info("Initializing download manager resources...")
                
                # Cleanup existing resources
                await self._cleanup_resources()
                
                # Initialize connector with optimized settings for speed
                self.connector = aiohttp.TCPConnector(
                    limit=100,  # Increased from 50
                    limit_per_host=30,  # Increased from 20
                    enable_cleanup_closed=True,
                    force_close=False,  # Keep connections alive
                    ttl_dns_cache=600,  # Longer DNS cache
                    ssl=False,  # Disable SSL verification for better performance
                    keepalive_timeout=30  # Keep connections alive longer
                )
                
                # Initialize session with optimized settings for speed
                self.session = aiohttp.ClientSession(
                    connector=self.connector,
                    timeout=aiohttp.ClientTimeout(
                        total=120,  # Reduced from 300
                        connect=10,  # Reduced from 60
                        sock_read=30,  # Reduced from 60
                        sock_connect=10  # Reduced from 60
                    ),
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': '*/*',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive'
                    }
                )
                
                # Initialize core components
                self._loop = current_loop
                self._downloads_lock = asyncio.Lock()
                
                # Initialize queue system
                await self._create_queue()
                self._queue_processor_running = True
                self._queue_processor_task = self._loop.create_task(self._process_queue())
                
                logger.info("Download manager successfully initialized")
                
        except Exception as e:
            logger.error(f"Error initializing download manager: {e}")
            # Attempt cleanup on initialization failure
            await self._cleanup_resources()
            raise

    async def _cleanup_resources(self):
        """Clean up existing resources"""
        # Stop queue processor
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_running = False
            self._queue_processor_task.cancel()
            try:
                await asyncio.wait_for(self._queue_processor_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                logger.warning(f"Error stopping queue processor: {e}")

        # Close existing session
        if self.session and not self.session.closed:
            try:
                await asyncio.wait_for(self.session.close(), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"Error closing session: {e}")

        # Clear state
        self.session = None
        self.connector = None
        self._queue_processor_task = None
        self.download_queue = None

    async def _process_queue(self):
        """Process the download queue"""
        while self._queue_processor_running:
            try:
                # Ensure we have a valid queue
                if not self.download_queue:
                    try:
                        await self._create_queue()
                    except Exception as e:
                        logger.error(f"Failed to create queue: {e}")
                        await asyncio.sleep(1)
                        continue

                # Get and process download task
                try:
                    _, worker, args = await asyncio.wait_for(self.download_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    if "different event loop" in str(e):
                        logger.warning("Queue bound to different event loop, recreating...")
                        self.download_queue = None
                        await asyncio.sleep(0.1)
                    else:
                        logger.error(f"Error getting from queue: {e}")
                    continue

                # Process the download
                try:
                    await worker.process_download(*args)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error processing download: {e}")
                finally:
                    try:
                        self.download_queue.task_done()
                    except Exception as e:
                        logger.error(f"Error marking task done: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Critical error in queue processor: {e}")
                await asyncio.sleep(1)

    async def process_download(self, downloader, url: str, update: Update, status_message: Message, format_id: str = None) -> None:
        """Process download request with optimized performance"""
        await self._ensure_initialized()
        
        user_id = update.effective_user.id
        
        async with self._downloads_lock:
            # Clean up completed downloads
            for uid, downloads in list(self.active_downloads.items()):
                self.active_downloads[uid] = {
                    url: task for url, task in downloads.items()
                    if not task.done()
                }
                if not self.active_downloads[uid]:
                    del self.active_downloads[uid]
            
            # Check user's concurrent downloads limit
            if len(self.active_downloads.get(user_id, {})) >= self.max_downloads_per_user:
                await status_message.edit_text(
                    DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger, self.keyboard_builder).get_message(
                        user_id, 'error_too_many_downloads'
                    )
                )
                return
            
            # Create worker and queue download
            worker = DownloadWorker(self.localization, self.settings_manager, self.session, self.activity_logger, self.keyboard_builder)
            priority = len(self.active_downloads.get(user_id, {}))  # Lower number = higher priority
            
            await self.download_queue.put((
                priority,
                worker,
                (downloader, url, update, status_message, format_id)
            ))

    async def cleanup(self):
        """Cleanup resources on shutdown"""
        try:
            # Ensure we're in a valid event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Stop queue processor first
            self._queue_processor_running = False
            if self._queue_processor_task and not self._queue_processor_task.done():
                self._queue_processor_task.cancel()
                try:
                    await asyncio.wait_for(self._queue_processor_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                    logger.warning(f"Queue processor cleanup error: {e}")
            
            # Wait for queue to empty with timeout
            if self.download_queue and not self.download_queue.empty():
                try:
                    await asyncio.wait_for(self.download_queue.join(), timeout=5.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Queue cleanup timeout: {e}")
            
            # Cancel active downloads
            if self._downloads_lock:
                try:
                    async with self._downloads_lock:
                        for downloads in self.active_downloads.values():
                            for task in downloads.values():
                                if not task.done():
                                    task.cancel()
                                    try:
                                        await asyncio.wait_for(task, timeout=2.0)
                                    except (asyncio.TimeoutError, asyncio.CancelledError):
                                        pass
                except Exception as e:
                    logger.error(f"Error cancelling downloads: {e}")
            
            # Close session
            if self.session and not self.session.closed:
                try:
                    await asyncio.wait_for(self.session.close(), timeout=5.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.warning(f"Session cleanup error: {e}")
            
            # Clear state
            self.download_queue = None
            self._queue_processor_task = None
            self.session = None
            self.connector = None
            self._loop = None
            self.active_downloads.clear()
            
            logger.info("Download manager cleanup completed")
            
        except Exception as e:
            logger.error(f"Fatal error during cleanup: {e}")
            raise



