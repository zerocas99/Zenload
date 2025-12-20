import os
import logging
import re
import asyncio
from typing import Tuple, Dict, List, Callable, Any
from pathlib import Path
from abc import ABC, abstractmethod
import yt_dlp

from ..config import YTDLP_OPTIONS, DOWNLOADS_DIR

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Custom exception for download errors"""
    pass


class BaseDownloader(ABC):
    """Base class for all platform-specific downloaders"""
    
    def __init__(self):
        self.ydl_opts = YTDLP_OPTIONS.get(self.platform_id(), {}).copy()
        self._progress_callback = None
        self._loop = None

    def set_progress_callback(self, callback: Callable[[str, int], None]):
        """Set callback for progress updates"""
        self._progress_callback = callback
        self._loop = asyncio.get_running_loop()

    def update_progress(self, status: str, progress: int):
        """Update download progress"""
        if self._progress_callback and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._progress_callback(status, progress),
                self._loop
            )

    def _progress_hook(self, d: Dict[str, Any]):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading' and self._progress_callback:
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 80) + 10  # Scale between 10-90%
                    self.update_progress('status_downloading', progress)
            except Exception as e:
                logger.error(f"Error in progress hook: {e}")

    @staticmethod
    def _prepare_filename(title: str) -> str:
        """Prepare safe filename from title"""
        safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
        return safe_title[:100]

    @abstractmethod
    def platform_id(self) -> str:
        """Return the platform identifier"""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this downloader can handle the given URL"""
        pass

    def preprocess_url(self, url: str) -> str:
        """Preprocess URL before downloading. Override if needed."""
        return url

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats for the content"""
        try:
            self.update_progress('status_getting_info', 0)
            url = self.preprocess_url(url)
            logger.info(f"Getting formats for URL: {url}")

            def extract_info():
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    self.update_progress('status_getting_info', 30)
                    logger.info("Attempting to extract info with yt-dlp")
                    return ydl.extract_info(url, download=False)

            info = await asyncio.to_thread(extract_info)
            self.update_progress('status_getting_info', 60)
            formats = []
            if info and 'formats' in info:
                seen = set()
                for f in info['formats']:
                    if 'height' in f and f['height']:
                        quality = f"{f['height']}p"
                        if quality not in seen:
                            formats.append({
                                'id': f['format_id'],
                                'quality': quality,
                                'ext': f.get('ext', 'mp4')
                            })
                            seen.add(quality)
            self.update_progress('status_getting_info', 100)
            return sorted(formats, key=lambda x: int(x['quality'][:-1]), reverse=True)
        except Exception as e:
            logger.error(f"Error getting formats: {str(e)}", exc_info=True)
            return []

    def format_metadata(self, info: Dict) -> str:
        """Format content metadata for display"""
        metadata = []
        
        # Title (clean up hashtags and common spam)
        if title := info.get('title'):
            # Remove hashtags and clean up title
            clean_title = re.sub(r'#\w+\s*', '', title).strip()
            if clean_title:
                metadata.append(clean_title)
            
        # Author/Channel
        if uploader := info.get('uploader'):
            metadata.append(f"By: {uploader}")
        
        # Duration
        if duration := info.get('duration'):
            minutes = int(duration) // 60
            seconds = int(duration) % 60
            metadata.append(f"Length: {minutes}:{seconds:02d}")
        
        # View count (simplified)
        if view_count := info.get('view_count'):
            if view_count >= 1_000_000:
                metadata.append(f"Views: {view_count/1_000_000:.1f}M")
            elif view_count >= 1_000:
                metadata.append(f"Views: {view_count/1_000:.1f}K")
            else:
                metadata.append(f"Views: {view_count}")
        
        return " | ".join(metadata)

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        """Download content from supported platforms
        Returns: (formatted_metadata, file_path)"""
        try:
            self.update_progress('status_downloading', 0)
            url = self.preprocess_url(url)
            logger.info(f"Starting download for URL: {url}")
            temp_filename = f"temp_{self.platform_id()}_{os.urandom(4).hex()}"
            self.ydl_opts['outtmpl'] = str(DOWNLOADS_DIR / f"{temp_filename}.%(ext)s")
            
            if format_id:
                self.ydl_opts['format'] = format_id

            # Add progress hook
            logger.info(f"Using yt-dlp options: {self.ydl_opts}")
            self.ydl_opts['progress_hooks'] = [lambda d: self._progress_hook(d)]

            def download_content():
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            try:
                info = await asyncio.to_thread(download_content)
            except Exception as e:
                error_msg = str(e).lower()
                if 'login' in error_msg or 'cookie' in error_msg:
                    raise DownloadError("Authentication required. Content may be private.")
                elif 'not found' in error_msg or '404' in error_msg:
                    raise DownloadError("Content not found. It may have been deleted or is unavailable.")
                else:
                    logger.error(f"Download error for {url}: {str(e)}", exc_info=True)
                    raise DownloadError(f"Download error: {str(e)}")

            if not info:
                raise DownloadError("Failed to get content information")

            # Find downloaded file
            downloaded_file = None
            for file in DOWNLOADS_DIR.glob(f"{temp_filename}.*"):
                if file.is_file():
                    downloaded_file = file
                    break

            if not downloaded_file:
                raise DownloadError("File was downloaded but not found in the system")

            self.update_progress('status_downloading', 100)

            # Format metadata and return
            metadata = self.format_metadata(info)
            return metadata, downloaded_file

        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error downloading {url}: {str(e)}", exc_info=True)
            raise DownloadError(f"Download error: {str(e)}")
