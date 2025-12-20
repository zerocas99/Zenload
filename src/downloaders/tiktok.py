"""TikTok downloader - TikWm primary, Cobalt secondary, yt-dlp fallback"""

import re
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from time import sleep
from urllib.parse import urlparse
import yt_dlp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt
from ..utils.tikwm_service import tikwm_service

logger = logging.getLogger(__name__)


class TikTokDownloader(BaseDownloader):
    """TikTok downloader using Cobalt API with yt-dlp fallback"""
    
    def platform_id(self) -> str:
        return 'tiktok'

    def __init__(self):
        super().__init__()

    def can_handle(self, url: str) -> bool:
        """Check if URL is from TikTok"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower() 
                for domain in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'])
        )

    def preprocess_url(self, url: str) -> str:
        """Clean TikTok URL"""
        if any(domain in url for domain in ['vm.tiktok.com', 'vt.tiktok.com']):
            return url
        return url.split('?')[0]

    async def get_direct_url(self, url: str) -> Tuple[Optional[str], Optional[str], bool, Optional[str]]:
        """
        Try to get direct URL for fast sending (without downloading to server).
        Returns: (direct_url, metadata, is_audio, audio_url)
        """
        # Try TikWm first (faster and more reliable)
        try:
            direct_url, metadata, is_audio, audio_url = await tikwm_service.get_direct_url(url)
            if direct_url:
                logger.info(f"[TikTok] Got direct URL from TikWm")
                return direct_url, metadata, is_audio, audio_url
        except Exception as e:
            logger.debug(f"[TikTok] TikWm get_direct_url failed: {e}")
        
        # Fallback to Cobalt
        try:
            result = await asyncio.wait_for(
                cobalt.request(url),
                timeout=10
            )
            
            if result.success and result.url:
                metadata = f"TikTok\n<a href=\"{url}\">Ссылка</a>"
                is_audio = result.url.endswith(('.mp3', '.m4a', '.wav'))
                logger.info(f"[TikTok] Got direct URL from Cobalt")
                return result.url, metadata, is_audio, None
                
        except Exception as e:
            logger.debug(f"[TikTok] Cobalt get_direct_url failed: {e}")
        
        return None, None, False, None

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        
        # Try Cobalt first
        result = await cobalt.request(url)
        if result.success:
            self.update_progress('status_getting_info', 100)
            return [{'id': 'best', 'quality': 'Best (без водяного знака)', 'ext': 'mp4'}]
        
        # Fallback to yt-dlp
        logger.info(f"[TikTok] Cobalt failed ({result.error}), trying yt-dlp")
        try:
            ydl_opts = {
                'format': 'best',
                'quiet': True,
                'no_warnings': True,
            }
            
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            formats = []
            if info and 'formats' in info:
                seen = set()
                for f in info['formats']:
                    if f.get('height'):
                        quality = f"{f['height']}p"
                        if quality not in seen:
                            formats.append({'id': f['format_id'], 'quality': quality, 'ext': 'mp4'})
                            seen.add(quality)
            return sorted(formats, key=lambda x: int(x['quality'][:-1]), reverse=True) if formats else [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[TikTok] Format error: {e}")
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - TikWm first, Cobalt second, yt-dlp fallback"""
        logger.info(f"[TikTok] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # === 1. Try TikWm (fastest, no watermark) ===
        self.update_progress('status_downloading', 5)
        try:
            filename, file_path, metadata = await tikwm_service.download(
                url,
                download_dir,
                progress_callback=self.update_progress
            )
            
            if file_path and file_path.exists():
                logger.info("[TikTok] Downloaded via TikWm")
                return metadata, file_path
        except Exception as e:
            logger.warning(f"[TikTok] TikWm failed: {e}")
        
        # === 2. Try Cobalt (no watermark!) ===
        self.update_progress('status_downloading', 20)
        filename, file_path = await cobalt.download(
            url, 
            download_dir,
            progress_callback=self.update_progress,
            tiktok_watermark=False  # Without watermark
        )
        
        if file_path and file_path.exists():
            metadata = f"TikTok\n<a href=\"{url}\">Ссылка</a>"
            logger.info("[TikTok] Downloaded via Cobalt")
            return metadata, file_path
        
        # === 3. Fallback to yt-dlp ===
        logger.info("[TikTok] Cobalt failed, trying yt-dlp")
        self.update_progress('status_downloading', 40)
        
        try:
            temp_filename = f"tiktok_{os.urandom(4).hex()}"
            ydl_opts = {
                'format': format_id or 'best',
                'outtmpl': str(download_dir / f"{temp_filename}.%(ext)s"),
                'quiet': False,
                'no_warnings': True,
                'progress_hooks': [self._progress_hook],
            }
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if not info:
                raise DownloadError("Failed to download video")
            
            # Find downloaded file
            for file in download_dir.glob(f"{temp_filename}.*"):
                if file.is_file():
                    def format_number(num):
                        if not num: return "0"
                        if num >= 1000000: return f"{num/1000000:.1f}M"
                        if num >= 1000: return f"{num/1000:.1f}K"
                        return str(num)
                    
                    likes = format_number(info.get('like_count', 0))
                    username = info.get('uploader', '').replace('https://www.tiktok.com/@', '')
                    views = format_number(info.get('view_count', 0))
                    
                    metadata = f"TikTok | {views} | {likes}\nby <a href=\"{url}\">{username}</a>"
                    return metadata, file
            
            raise DownloadError("Downloaded file not found")
            
        except Exception as e:
            logger.error(f"[TikTok] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 60) + 30
                    self.update_progress('status_downloading', progress)
            except:
                pass
