"""Instagram downloader using Cobalt API with alternative services and yt-dlp fallback"""

import os
import re
import logging
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt
from ..utils.instagram_api import instagram_api

logger = logging.getLogger(__name__)


class InstagramDownloader(BaseDownloader):
    """Instagram downloader using Cobalt API with yt-dlp fallback"""
    
    def __init__(self):
        super().__init__()
        self._cookies_file = None
        self._setup_cookies()
        self.ydl_opts.update({
            'format': 'best',
            'nooverwrites': True,
            'quiet': True,
            'no_warnings': True,
        })
        if self._cookies_file:
            self.ydl_opts['cookiefile'] = self._cookies_file

    def _setup_cookies(self):
        """Setup cookies from environment variable"""
        cookies = os.getenv('INSTAGRAM_COOKIES')
        if cookies:
            try:
                # Create temp file with cookies in Netscape format
                fd, path = tempfile.mkstemp(suffix='.txt', prefix='ig_cookies_')
                with os.fdopen(fd, 'w') as f:
                    # Write Netscape cookie header
                    f.write("# Netscape HTTP Cookie File\n")
                    f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n\n")
                    
                    # Parse cookies - expect format: name1=value1; name2=value2
                    for cookie in cookies.split(';'):
                        cookie = cookie.strip()
                        if '=' in cookie:
                            name, value = cookie.split('=', 1)
                            name = name.strip()
                            value = value.strip()
                            # Write in Netscape format
                            f.write(f".instagram.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
                
                self._cookies_file = path
                logger.info("[Instagram] Cookies loaded from environment")
            except Exception as e:
                logger.error(f"[Instagram] Failed to setup cookies: {e}")
                self._cookies_file = None
        else:
            logger.info("[Instagram] No INSTAGRAM_COOKIES env var found")

    def _extract_shortcode(self, url: str) -> Optional[str]:
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/reels/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def platform_id(self) -> str:
        return 'instagram'

    def can_handle(self, url: str) -> bool:
        return any(x in url for x in ["instagram.com", "instagr.am"])

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        
        # Try Cobalt first
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
        
        # Fallback to yt-dlp
        logger.info(f"[Instagram] Cobalt failed ({result.error}), trying yt-dlp")
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[Instagram] Format error: {e}")
            # Even if format extraction fails, we can try downloading
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, alternative APIs, then yt-dlp fallback"""
        shortcode = self._extract_shortcode(url) or 'video'
        logger.info(f"[Instagram] Downloading: {shortcode}")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # === 1. Try Cobalt ===
        self.update_progress('status_downloading', 10)
        filename, file_path = await cobalt.download(
            url, 
            download_dir,
            progress_callback=self.update_progress
        )
        
        if file_path and file_path.exists():
            metadata = f"Instagram\n<a href=\"{url}\">Ссылка</a>"
            return metadata, file_path
        
        # === 2. Try Alternative Instagram APIs ===
        logger.info("[Instagram] Cobalt failed, trying alternative APIs")
        self.update_progress('status_downloading', 20)
        
        filename, file_path = await instagram_api.download(
            url,
            download_dir,
            progress_callback=self.update_progress
        )
        
        if file_path and file_path.exists():
            metadata = f"Instagram\n<a href=\"{url}\">Ссылка</a>"
            return metadata, file_path
        
        # === 3. Fallback to yt-dlp ===
        logger.info("[Instagram] Alternative APIs failed, trying yt-dlp")
        self.update_progress('status_downloading', 40)
        
        try:
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = str(download_dir / f"instagram_{shortcode}.%(ext)s")
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if not info:
                raise DownloadError("Failed to download video")
            
            # Find file
            filename = f"instagram_{shortcode}.mp4" # Assuming mp4
            file_path = download_dir / filename
            
            # If exact filename not found, try to find what yt-dlp saved
            if not file_path.exists():
                for f in download_dir.glob(f"instagram_{shortcode}.*"):
                    file_path = f
                    break
            
            if not file_path.exists():
                 raise DownloadError("File downloaded but not found")

            metadata = f"Instagram\n<a href=\"{url}\">Ссылка</a>"
            return metadata, file_path
            
        except Exception as e:
            logger.error(f"[Instagram] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
