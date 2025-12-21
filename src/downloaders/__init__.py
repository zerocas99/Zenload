from typing import Optional, Type, List
import logging
from .base import BaseDownloader, DownloadError
from .instagram import InstagramDownloader
from .tiktok import TikTokDownloader
from .pinterest import PinterestDownloader
from .youtube import YouTubeDownloader
from .soundcloud import SoundcloudDownloader
from .cobalt_platforms import CobaltPlatformDownloader

logger = logging.getLogger(__name__)


class DownloaderFactory:
    """Factory class to manage and create appropriate downloaders"""
    
    _downloaders: List[Type[BaseDownloader]] = [
        InstagramDownloader,
        TikTokDownloader,
        PinterestDownloader,
        YouTubeDownloader,
        SoundcloudDownloader,
        CobaltPlatformDownloader,  # VK, OK, Rutube, Facebook, Twitch, Bilibili, etc.
    ]

    @classmethod
    def get_downloader(cls, url: str) -> Optional[BaseDownloader]:
        """Get appropriate downloader for the given URL"""
        logger.info(f"[Factory] Looking for downloader for: {url[:80]}...")
        for downloader_class in cls._downloaders:
            try:
                downloader = downloader_class()
                logger.debug(f"[Factory] Checking {downloader_class.__name__}...")
                if downloader.can_handle(url):
                    logger.info(f"[Factory] Found: {downloader_class.__name__}")
                    return downloader
            except Exception as e:
                logger.error(f"[Factory] Error with {downloader_class.__name__}: {e}")
                continue
        logger.warning(f"[Factory] No downloader found for: {url[:80]}")
        return None


__all__ = ['DownloaderFactory', 'DownloadError']
