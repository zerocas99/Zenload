"""Instagram downloader using Cobalt API with alternative services and yt-dlp fallback"""

import re
import os
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt
from ..utils.instagram_api import instagram_api
from ..utils.instagram_js_fallback import instagram_js_fallback
from ..utils.instagram_stories_service import instagram_stories_service

logger = logging.getLogger(__name__)

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

    def _extract_shortcode(self, url: str) -> Optional[str]:
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/reels/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
            r'instagram\.com/stories/[^/]+/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _extract_username(self, url: str) -> Optional[str]:
        """Extract username from Instagram URL"""
        match = re.search(r'instagram\.com/stories/([^/]+)', url)
        if match:
            return match.group(1)
        return None

    def _is_story_url(self, url: str) -> bool:
        """Check if URL is an Instagram Story"""
        return '/stories/' in url

    def _is_all_stories_url(self, url: str) -> bool:
        """Check if URL is for all stories (no specific story ID)"""
        if '/stories/' not in url:
            return False
        # URL like instagram.com/stories/username/ without story ID
        match = re.search(r'instagram\.com/stories/([^/]+)/?$', url)
        return match is not None

    def platform_id(self) -> str:
        return 'instagram'

    def can_handle(self, url: str) -> bool:
        return any(x in url for x in ["instagram.com", "instagr.am"])

    async def get_direct_url(self, url: str) -> Tuple[Optional[str], Optional[str], bool, Optional[str], bool, Optional[list]]:
        """
        Get direct URL for fast sending.
        Returns: (direct_url, metadata, is_audio, audio_url, is_photo, all_items)
        """
        # For all stories URL - need to download all
        if self._is_all_stories_url(url):
            return None, None, False, None, False, None
        
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=10
            )
            
            if result.success:
                # Handle picker (carousel/multiple items)
                if result.picker and len(result.picker) > 0:
                    all_items = []
                    for item in result.picker:
                        item_url = item.get('url', '')
                        item_type = self._detect_media_type(item_url)
                        all_items.append({
                            'url': item_url,
                            'type': item_type
                        })
                    
                    first_url = all_items[0]['url']
                    is_photo = all_items[0]['type'] == 'photo'
                    logger.info(f"[Instagram] Got picker with {len(all_items)} items")
                    return first_url, "", False, None, is_photo, all_items
                
                elif result.url:
                    media_type = self._detect_media_type(result.url)
                    is_photo = media_type == 'photo'
                    is_audio = media_type == 'audio'
                    logger.info(f"[Instagram] Got direct URL (type={media_type})")
                    return result.url, "", is_audio, None, is_photo, None
                
        except Exception as e:
            logger.debug(f"[Instagram] get_direct_url failed: {e}")
        
        return None, None, False, None, False, None

    def _detect_media_type(self, url: str) -> str:
        """Detect media type from URL"""
        url_lower = url.lower()
        
        # Check file extension
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.heic']):
            return 'photo'
        if any(ext in url_lower for ext in ['.mp4', '.mov', '.webm', '.m4v']):
            return 'video'
        if any(ext in url_lower for ext in ['.mp3', '.m4a', '.wav', '.ogg', '.opus']):
            return 'audio'
        
        # Check URL patterns
        if 'scontent' in url_lower and 'video' not in url_lower:
            # Instagram CDN - check for video indicators
            if '_n.jpg' in url_lower or 'e35/' in url_lower:
                return 'photo'
        
        # Default to video for Instagram
        return 'video'

    async def _detect_media_type_by_headers(self, url: str) -> str:
        """Detect media type by checking HTTP headers"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(
                    url,
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=True
                ) as response:
                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    if 'image' in content_type:
                        return 'photo'
                    elif 'video' in content_type:
                        return 'video'
                    elif 'audio' in content_type:
                        return 'audio'
        except:
            pass
        
        return self._detect_media_type(url)

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
        
        logger.info(f"[Instagram] Cobalt failed ({result.error}), trying yt-dlp")
        try:
            def extract():
                with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[Instagram] Format error: {e}")
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download_all_stories(self, url: str) -> List[Tuple[str, Path, str]]:
        """
        Download all stories from a user.
        Returns: List of (metadata, file_path, media_type)
        """
        username = self._extract_username(url)
        if not username:
            raise DownloadError("Не удалось определить username")
        
        logger.info(f"[Instagram] Downloading all stories for @{username}")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # Get all stories
        stories = await instagram_stories_service.get_stories(url)
        if not stories:
            raise DownloadError(f"Не найдено сторис у @{username}. Возможно, аккаунт приватный или сторис нет.")
        
        logger.info(f"[Instagram] Found {len(stories)} stories for @{username}")
        
        downloaded = []
        for i, story in enumerate(stories):
            media_url = story.get('url')
            if not media_url:
                continue
            
            try:
                # Detect type
                media_type = await self._detect_media_type_by_headers(media_url)
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        media_url,
                        headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status != 200:
                            continue
                        
                        content = await response.read()
                        
                        # Double-check type by content
                        if len(content) > 8 and content[4:8] == b'ftyp':
                            media_type = 'video'
                        
                        ext = 'mp4' if media_type == 'video' else 'jpg'
                        filename = f"story_{username}_{i+1}_{os.urandom(3).hex()}.{ext}"
                        file_path = download_dir / filename
                        
                        with open(file_path, 'wb') as f:
                            f.write(content)
                        
                        if file_path.exists() and file_path.stat().st_size > 500:
                            downloaded.append(("", file_path, media_type))
                            logger.info(f"[Instagram] Downloaded story {i+1}/{len(stories)}: {media_type}")
                        
            except Exception as e:
                logger.warning(f"[Instagram] Failed to download story {i+1}: {e}")
                continue
        
        if not downloaded:
            raise DownloadError("Не удалось скачать ни одну сторис")
        
        return downloaded

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video/photo - Cobalt first, then fallbacks"""
        shortcode = self._extract_shortcode(url) or 'media'
        is_story = self._is_story_url(url)
        logger.info(f"[Instagram] Downloading: {shortcode} (story: {is_story})")
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # === Stories handling ===
        if is_story:
            self.update_progress('status_downloading', 5)
            logger.info("[Instagram] Story detected, trying stories service...")
            
            try:
                filename, file_path = await instagram_stories_service.download(
                    url,
                    download_dir,
                    progress_callback=self.update_progress
                )
                
                if file_path and file_path.exists():
                    logger.info("[Instagram] Story downloaded via stories service")
                    return "", file_path
            except Exception as e:
                logger.warning(f"[Instagram] Stories service failed: {e}")
        
        # === 1. Try Cobalt ===
        self.update_progress('status_downloading', 10)
        
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=COBALT_TIMEOUT
            )
            
            if result.success:
                download_url = result.url
                
                # Handle picker
                if result.picker and len(result.picker) > 0:
                    download_url = result.picker[0].get('url')
                
                if download_url:
                    # Detect type
                    media_type = await self._detect_media_type_by_headers(download_url)
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            download_url,
                            headers={'User-Agent': 'Mozilla/5.0'},
                            timeout=aiohttp.ClientTimeout(total=120)
                        ) as response:
                            if response.status == 200:
                                content = await response.read()
                                
                                # Check content for type
                                if len(content) > 8 and content[4:8] == b'ftyp':
                                    media_type = 'video'
                                
                                ext = 'mp4' if media_type == 'video' else 'jpg'
                                filename = result.filename or f"instagram_{shortcode}.{ext}"
                                
                                # Fix extension if needed
                                if media_type == 'photo' and filename.endswith('.mp4'):
                                    filename = filename.replace('.mp4', '.jpg')
                                elif media_type == 'video' and filename.endswith('.jpg'):
                                    filename = filename.replace('.jpg', '.mp4')
                                
                                file_path = download_dir / filename
                                
                                with open(file_path, 'wb') as f:
                                    f.write(content)
                                
                                if file_path.exists() and file_path.stat().st_size > 500:
                                    logger.info(f"[Instagram] Downloaded via Cobalt: {media_type}")
                                    return "", file_path
                
        except asyncio.TimeoutError:
            logger.warning(f"[Instagram] Cobalt timeout")
        except Exception as e:
            logger.warning(f"[Instagram] Cobalt error: {e}")
        
        # === 2. Try JS API Fallback ===
        logger.info("[Instagram] Trying JS API fallback")
        self.update_progress('status_downloading', 30)
        
        try:
            filename, file_path = await instagram_js_fallback.download(
                url,
                download_dir,
                progress_callback=self.update_progress
            )
            
            if file_path and file_path.exists():
                logger.info("[Instagram] JS fallback success")
                return "", file_path
                
        except Exception as e:
            logger.warning(f"[Instagram] JS fallback error: {e}")
        
        # === 3. Try Alternative APIs ===
        logger.info("[Instagram] Trying alternative APIs")
        self.update_progress('status_downloading', 50)
        
        filename, file_path = await instagram_api.download(
            url,
            download_dir,
            progress_callback=self.update_progress
        )
        
        if file_path and file_path.exists():
            return "", file_path
        
        # === 4. yt-dlp fallback (skip for stories) ===
        if is_story:
            raise DownloadError("Не удалось скачать Story. Возможно, аккаунт приватный.")
        
        logger.info("[Instagram] Trying yt-dlp")
        self.update_progress('status_downloading', 70)
        
        try:
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = str(download_dir / f"instagram_{shortcode}.%(ext)s")
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if info:
                for f in download_dir.glob(f"instagram_{shortcode}.*"):
                    if f.is_file():
                        return "", f
            
            raise DownloadError("File not found after download")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Instagram] Download failed: {error_msg}")
            
            if "login" in error_msg.lower():
                raise DownloadError("Контент требует авторизации")
            
            raise DownloadError(f"Ошибка загрузки: {error_msg}")
