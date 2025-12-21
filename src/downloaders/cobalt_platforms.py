"""
Universal Cobalt-based downloader for multiple platforms.
Supports: VK, OK, Rutube, Facebook, Twitch, Bilibili, Dailymotion, 
Vimeo, Tumblr, Streamable, Loom, Bluesky, Reddit, Snapchat, Xiaohongshu
"""

import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse
import aiohttp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)


# Platform configurations
PLATFORMS = {
    'vk': {
        'domains': ['vk.com', 'vkvideo.ru'],
        'name': 'VK Video',
    },
    'ok': {
        'domains': ['ok.ru', 'odnoklassniki.ru'],
        'name': 'Одноклассники',
    },
    'rutube': {
        'domains': ['rutube.ru'],
        'name': 'Rutube',
    },
    'facebook': {
        'domains': ['facebook.com', 'fb.watch', 'fb.com'],
        'name': 'Facebook',
    },
    'twitch': {
        'domains': ['twitch.tv', 'clips.twitch.tv'],
        'name': 'Twitch',
    },
    'bilibili': {
        'domains': ['bilibili.com', 'b23.tv'],
        'name': 'Bilibili',
    },
    'dailymotion': {
        'domains': ['dailymotion.com', 'dai.ly'],
        'name': 'Dailymotion',
    },
    'vimeo': {
        'domains': ['vimeo.com'],
        'name': 'Vimeo',
    },
    'tumblr': {
        'domains': ['tumblr.com'],
        'name': 'Tumblr',
    },
    'streamable': {
        'domains': ['streamable.com'],
        'name': 'Streamable',
    },
    'loom': {
        'domains': ['loom.com'],
        'name': 'Loom',
    },
    'bluesky': {
        'domains': ['bsky.app', 'bsky.social'],
        'name': 'Bluesky',
    },
    'reddit': {
        'domains': ['reddit.com', 'redd.it'],
        'name': 'Reddit',
    },
    'snapchat': {
        'domains': ['snapchat.com', 'story.snapchat.com'],
        'name': 'Snapchat',
    },
    'xiaohongshu': {
        'domains': ['xiaohongshu.com', 'xhslink.com'],
        'name': 'Xiaohongshu',
    },
    'newgrounds': {
        'domains': ['newgrounds.com'],
        'name': 'Newgrounds',
    },
}


class CobaltPlatformDownloader(BaseDownloader):
    """Universal downloader for platforms supported by Cobalt"""
    
    def __init__(self):
        super().__init__()
        self._detected_platform = None
    
    def platform_id(self) -> str:
        return self._detected_platform or 'cobalt'
    
    def _detect_platform(self, url: str) -> Optional[str]:
        """Detect which platform the URL belongs to"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        
        for platform_id, config in PLATFORMS.items():
            if any(d in domain for d in config['domains']):
                return platform_id
        return None
    
    def can_handle(self, url: str) -> bool:
        """Check if URL is from any supported platform"""
        platform = self._detect_platform(url)
        if platform:
            self._detected_platform = platform
            return True
        return False
    
    def get_platform_name(self, url: str) -> str:
        """Get human-readable platform name"""
        platform = self._detect_platform(url)
        if platform and platform in PLATFORMS:
            return PLATFORMS[platform]['name']
        return 'Video'

    async def get_direct_url(self, url: str) -> Tuple[Optional[str], Optional[str], bool, Optional[str], bool, Optional[list]]:
        """Try to get direct URL for fast sending"""
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=15
            )
            
            if result.success:
                if result.picker and len(result.picker) > 0:
                    # Multiple items (e.g., Reddit gallery)
                    direct_url = result.picker[0].get('url')
                    all_items = [item.get('url') for item in result.picker if item.get('url')]
                    return direct_url, "", False, None, len(all_items) > 1, all_items
                elif result.url:
                    is_audio = result.url.endswith(('.mp3', '.m4a', '.wav', '.opus'))
                    return result.url, "", is_audio, None, False, None
                    
        except Exception as e:
            logger.debug(f"[Cobalt] get_direct_url failed: {e}")
        
        return None, None, False, None, False, None

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        platform = self._detect_platform(url)
        platform_name = PLATFORMS.get(platform, {}).get('name', 'Video')
        
        # Cobalt handles quality automatically
        self.update_progress('status_getting_info', 100)
        return [
            {'id': '1080', 'quality': '1080p', 'ext': 'mp4'},
            {'id': '720', 'quality': '720p', 'ext': 'mp4'},
            {'id': '480', 'quality': '480p', 'ext': 'mp4'},
            {'id': 'best', 'quality': f'Best ({platform_name})', 'ext': 'mp4'},
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video via Cobalt"""
        platform = self._detected_platform or self._detect_platform(url)
        platform_name = PLATFORMS.get(platform, {}).get('name', 'Video')
        
        logger.info(f"[{platform_name}] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        self.update_progress('status_downloading', 10)
        
        # Determine quality
        quality = "1080"
        if format_id and format_id != 'best':
            quality = format_id.replace('p', '')
        
        # Try Cobalt with timeout
        try:
            result = await asyncio.wait_for(
                cobalt.request(url, video_quality=quality),
                timeout=30
            )
            
            if result.success:
                download_url = result.url
                
                # Handle picker (multiple items)
                if result.picker and len(result.picker) > 0:
                    download_url = result.picker[0].get('url')
                
                if download_url:
                    self.update_progress('status_downloading', 30)
                    
                    # Download file
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            download_url,
                            headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                'Accept': '*/*',
                            },
                            timeout=aiohttp.ClientTimeout(total=120, connect=15)
                        ) as response:
                            if response.status == 200:
                                # Generate filename
                                filename = result.filename or f"{platform}_{os.urandom(4).hex()}.mp4"
                                file_path = download_dir / filename
                                
                                total_size = 0
                                with open(file_path, 'wb') as f:
                                    async for chunk in response.content.iter_chunked(1024 * 1024):
                                        if chunk:
                                            f.write(chunk)
                                            total_size += len(chunk)
                                
                                if total_size < 1000:
                                    logger.warning(f"[{platform_name}] File too small ({total_size} bytes)")
                                    if file_path.exists():
                                        file_path.unlink()
                                    raise Exception("Downloaded file is too small")
                                
                                self.update_progress('status_downloading', 100)
                                logger.info(f"[{platform_name}] Downloaded: {file_path} ({total_size} bytes)")
                                return "", file_path
                            else:
                                raise Exception(f"HTTP {response.status}")
            
            error_msg = result.error or "Unknown error"
            logger.error(f"[{platform_name}] Cobalt failed: {error_msg}")
            raise DownloadError(f"Ошибка загрузки с {platform_name}: {error_msg}")
        
        except asyncio.TimeoutError:
            logger.error(f"[{platform_name}] Timeout - Cobalt took too long")
            raise DownloadError(f"Таймаут загрузки с {platform_name}")
        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"[{platform_name}] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
