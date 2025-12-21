"""
Universal Cobalt-based downloader for multiple platforms.
Supports all platforms from Cobalt API with fast direct URL sending.
"""

import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import aiohttp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)

# All platforms supported by Cobalt with ALL possible domains
PLATFORMS = {
    'vk': {
        'domains': ['vk.com', 'vkvideo.ru', 'm.vk.com', 'vk.ru'],
        'name': 'VK Video',
    },
    'ok': {
        'domains': ['ok.ru', 'odnoklassniki.ru', 'm.ok.ru'],
        'name': 'Одноклассники',
    },
    'rutube': {
        'domains': ['rutube.ru', 'm.rutube.ru'],
        'name': 'Rutube',
    },
    'facebook': {
        'domains': ['facebook.com', 'fb.watch', 'fb.com', 'm.facebook.com', 'www.facebook.com', 'web.facebook.com'],
        'name': 'Facebook',
    },
    'twitch': {
        'domains': ['twitch.tv', 'clips.twitch.tv', 'm.twitch.tv', 'www.twitch.tv'],
        'name': 'Twitch',
    },
    'bilibili': {
        'domains': ['bilibili.com', 'b23.tv', 'www.bilibili.com', 'm.bilibili.com', 'bilibili.tv'],
        'name': 'Bilibili',
    },
    'dailymotion': {
        'domains': ['dailymotion.com', 'dai.ly', 'www.dailymotion.com'],
        'name': 'Dailymotion',
    },
    'vimeo': {
        'domains': ['vimeo.com', 'player.vimeo.com', 'www.vimeo.com'],
        'name': 'Vimeo',
    },
    'tumblr': {
        'domains': ['tumblr.com', 'www.tumblr.com', 't.umblr.com'],
        'name': 'Tumblr',
    },
    'streamable': {
        'domains': ['streamable.com'],
        'name': 'Streamable',
    },
    'loom': {
        'domains': ['loom.com', 'www.loom.com'],
        'name': 'Loom',
    },
    'bluesky': {
        'domains': ['bsky.app', 'bsky.social'],
        'name': 'Bluesky',
    },
    'reddit': {
        'domains': ['reddit.com', 'redd.it', 'www.reddit.com', 'old.reddit.com', 'new.reddit.com', 'v.redd.it'],
        'name': 'Reddit',
    },
    'snapchat': {
        'domains': ['snapchat.com', 'story.snapchat.com', 'www.snapchat.com', 't.snapchat.com'],
        'name': 'Snapchat',
    },
    'xiaohongshu': {
        'domains': ['xiaohongshu.com', 'xhslink.com', 'www.xiaohongshu.com'],
        'name': 'Xiaohongshu',
    },
    'newgrounds': {
        'domains': ['newgrounds.com', 'www.newgrounds.com'],
        'name': 'Newgrounds',
    },
    'twitter': {
        'domains': ['twitter.com', 'x.com', 't.co', 'mobile.twitter.com', 'mobile.x.com', 'fxtwitter.com', 'vxtwitter.com', 'fixupx.com'],
        'name': 'Twitter/X',
    },
}


class CobaltPlatformDownloader(BaseDownloader):
    """Universal downloader for platforms supported by Cobalt with fast send"""
    
    def __init__(self):
        super().__init__()
        self._detected_platform = None
    
    def platform_id(self) -> str:
        return self._detected_platform or 'cobalt'
    
    def _detect_platform(self, url: str) -> Optional[str]:
        """Detect which platform the URL belongs to"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. and m. prefixes for comparison
        clean_domain = domain
        for prefix in ['www.', 'm.', 'mobile.', 'web.']:
            if clean_domain.startswith(prefix):
                clean_domain = clean_domain[len(prefix):]
                break  # Only remove one prefix
        
        logger.info(f"[Cobalt] Checking domain: {domain} -> {clean_domain}")
        
        for platform_id, config in PLATFORMS.items():
            for d in config['domains']:
                # Clean the config domain too
                clean_d = d.lower()
                for prefix in ['www.', 'm.', 'mobile.', 'web.']:
                    if clean_d.startswith(prefix):
                        clean_d = clean_d[len(prefix):]
                        break  # Only remove one prefix
                
                # Exact match or subdomain match
                if clean_domain == clean_d or clean_domain.endswith('.' + clean_d):
                    logger.info(f"[Cobalt] Detected platform {platform_id} for domain {domain}")
                    return platform_id
                
                # Also check original domain for special cases like clips.twitch.tv
                if domain == d.lower() or domain.endswith('.' + d.lower()):
                    logger.info(f"[Cobalt] Detected platform {platform_id} for domain {domain} (exact)")
                    return platform_id
        
        logger.info(f"[Cobalt] No platform detected for domain: {domain}")
        return None
    
    def can_handle(self, url: str) -> bool:
        """Check if URL is from any supported platform"""
        platform = self._detect_platform(url)
        if platform:
            self._detected_platform = platform
            logger.info(f"[Cobalt] can_handle=True for {platform}: {url[:80]}")
            return True
        logger.debug(f"[Cobalt] can_handle=False: {url[:80]}")
        return False
    
    def get_platform_name(self, url: str = None) -> str:
        """Get human-readable platform name"""
        platform = self._detected_platform or (self._detect_platform(url) if url else None)
        if platform and platform in PLATFORMS:
            return PLATFORMS[platform]['name']
        return 'Video'

    async def get_direct_url(self, url: str) -> Tuple[Optional[str], Optional[str], bool, Optional[str], bool, Optional[list]]:
        """
        Get direct URL for fast sending (without downloading to server).
        Returns: (direct_url, metadata, is_audio, audio_url, is_gallery, all_items)
        """
        try:
            # Fast timeout for direct URL
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=10
            )
            
            if result.success:
                if result.picker and len(result.picker) > 0:
                    # Multiple items (gallery)
                    direct_url = result.picker[0].get('url')
                    all_items = [item.get('url') for item in result.picker if item.get('url')]
                    is_gallery = len(all_items) > 1
                    logger.info(f"[Cobalt] Got picker with {len(all_items)} items")
                    return direct_url, "", False, None, is_gallery, all_items
                elif result.url:
                    is_audio = any(result.url.endswith(ext) for ext in ['.mp3', '.m4a', '.wav', '.opus', '.ogg'])
                    logger.info(f"[Cobalt] Got direct URL (audio={is_audio})")
                    return result.url, "", is_audio, None, False, None
            else:
                logger.debug(f"[Cobalt] No direct URL: {result.error}")
                    
        except asyncio.TimeoutError:
            logger.debug("[Cobalt] Direct URL timeout")
        except Exception as e:
            logger.debug(f"[Cobalt] get_direct_url error: {e}")
        
        return None, None, False, None, False, None

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        platform_name = self.get_platform_name(url)
        return [
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
        
        # Try Cobalt with timeout
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=20
            )
            
            if result.success:
                download_url = result.url
                
                # Handle picker (multiple items)
                if result.picker and len(result.picker) > 0:
                    download_url = result.picker[0].get('url')
                
                if download_url:
                    self.update_progress('status_downloading', 30)
                    
                    # Fast download with short timeout
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            download_url,
                            headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                'Accept': '*/*',
                            },
                            timeout=aiohttp.ClientTimeout(total=60, connect=10)
                        ) as response:
                            if response.status == 200:
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
            logger.error(f"[{platform_name}] Timeout")
            raise DownloadError(f"Таймаут загрузки с {platform_name}")
        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"[{platform_name}] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
