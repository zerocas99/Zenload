"""Instagram downloader using Cobalt API with alternative services and yt-dlp fallback"""

import re
import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt
from ..utils.instagram_api import instagram_api
from ..utils.instagram_js_fallback import instagram_js_fallback

logger = logging.getLogger(__name__)

# Timeout for Cobalt operations (seconds)
COBALT_TIMEOUT = 25


class InstagramDownloader(BaseDownloader):
    """Instagram downloader using Cobalt API with yt-dlp fallback"""
    
    def __init__(self):
        super().__init__()
        self.ydl_opts.update({
            'format': 'best',
            'nooverwrites': True,
            'quiet': True,
            'no_warnings': True,
        })
        self._metadata_template = "Instagram\n{url}"

    def _extract_shortcode(self, url: str) -> Optional[str]:
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/reels/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
            r'instagram\.com/stories/[^/]+/(\d+)',  # Stories have numeric IDs
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _is_story_url(self, url: str) -> bool:
        """Check if URL is an Instagram Story"""
        return '/stories/' in url

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
            
            _ = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[Instagram] Format error: {e}")
            # Even if format extraction fails, we can try downloading
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, JS fallback, alternative APIs, then yt-dlp"""
        shortcode = self._extract_shortcode(url) or 'video'
        is_story = self._is_story_url(url)
        logger.info(f"[Instagram] Downloading: {shortcode} (story: {is_story})")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # === 1. Try Cobalt with timeout ===
        self.update_progress('status_downloading', 10)
        cobalt_success = False
        
        try:
            filename, file_path = await asyncio.wait_for(
                cobalt.download(
                    url, 
                    download_dir,
                    progress_callback=self.update_progress
                ),
                timeout=COBALT_TIMEOUT
            )
            
            if file_path and file_path.exists():
                cobalt_success = True
                metadata = self._metadata_template.format(url=url)
                return metadata, file_path
                
        except asyncio.TimeoutError:
            logger.warning(f"[Instagram] Cobalt timeout after {COBALT_TIMEOUT}s, trying JS fallback")
        except Exception as e:
            logger.warning(f"[Instagram] Cobalt error: {e}, trying JS fallback")
        
        # === 2. Try JS API Fallback (only if Cobalt failed) ===
        if not cobalt_success:
            logger.info("[Instagram] Cobalt failed, trying JS API fallback")
            self.update_progress('status_downloading', 15)
            
            try:
                filename, file_path = await instagram_js_fallback.download(
                    url,
                    download_dir,
                    progress_callback=self.update_progress
                )
                
                if file_path and file_path.exists():
                    logger.info("[Instagram] JS fallback used successfully")
                    metadata = self._metadata_template.format(url=url)
                    return metadata, file_path
                    
            except Exception as e:
                logger.warning(f"[Instagram] JS fallback error: {e}")
        
        # === 3. Try Alternative Instagram APIs ===
        logger.info("[Instagram] JS fallback failed, trying alternative APIs")
        self.update_progress('status_downloading', 20)
        
        filename, file_path = await instagram_api.download(
            url,
            download_dir,
            progress_callback=self.update_progress
        )
        
        if file_path and file_path.exists():
            metadata = self._metadata_template.format(url=url)
            return metadata, file_path
        
        # === 4. Fallback to yt-dlp (skip for stories - requires auth) ===
        if is_story:
            logger.warning("[Instagram] Stories require authentication, skipping yt-dlp")
            raise DownloadError("Instagram Stories require authentication. Please use Reels or Posts instead.")
        
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
            filename = f"instagram_{shortcode}.mp4"  # Assuming mp4
            file_path = download_dir / filename
            
            # If exact filename not found, try to find what yt-dlp saved
            if not file_path.exists():
                for f in download_dir.glob(f"instagram_{shortcode}.*"):
                    file_path = f
                    break
            
            if not file_path.exists():
                raise DownloadError("File downloaded but not found")

            metadata = self._metadata_template.format(url=url)
            return metadata, file_path
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Instagram] Download failed: {error_msg}")
            
            # Provide more helpful error messages
            if "login" in error_msg.lower() or "log in" in error_msg.lower():
                raise DownloadError("This content requires Instagram login. Try Reels or public posts.")
            elif "video url" in error_msg.lower():
                raise DownloadError("Could not extract media. This might be an image post or carousel.")
            
            raise DownloadError(f"Instagram download failed: {error_msg}")
