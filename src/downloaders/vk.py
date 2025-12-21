"""VK (VKontakte) video downloader using yt-dlp with Cobalt fallback"""

import re
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse
import yt_dlp
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)


class VKDownloader(BaseDownloader):
    """VK video downloader using yt-dlp with Cobalt fallback"""
    
    def __init__(self):
        super().__init__()
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "vk.txt"
        
        # Import Cobalt service
        try:
            from ..utils.cobalt_service import cobalt
            self._cobalt = cobalt
        except:
            self._cobalt = None

    def platform_id(self) -> str:
        return 'vk'

    def can_handle(self, url: str) -> bool:
        """Check if URL is from VK"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and
            any(domain in parsed.netloc.lower() 
                for domain in ['vk.com', 'm.vk.com', 'vk.ru', 'vkvideo.ru'])
        )

    def preprocess_url(self, url: str) -> str:
        """Clean VK URL - convert mobile to desktop"""
        # Convert m.vk.com to vk.com
        url = url.replace('m.vk.com', 'vk.com')
        # Remove unnecessary parameters but keep video ID
        return url.split('&from=')[0]

    async def get_video_info(self, url: str) -> Dict:
        """Get video info including title, thumbnail, duration"""
        processed_url = self.preprocess_url(url)
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
            }
            
            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)
            
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(processed_url, download=False)
            
            info = await asyncio.to_thread(extract)
            
            if info:
                return {
                    'title': info.get('title', 'VK Video'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'id': info.get('id', ''),
                    'formats': info.get('formats', [])
                }
        except Exception as e:
            logger.warning(f"[VK] Failed to get video info: {e}")
        
        return {
            'title': 'VK Video',
            'thumbnail': None,
            'duration': 0,
            'uploader': 'Unknown',
            'view_count': 0,
            'id': '',
            'formats': []
        }

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats"""
        self.update_progress('status_getting_info', 0)
        processed_url = self.preprocess_url(url)
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)
            
            def extract():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(processed_url, download=False)
            
            info = await asyncio.to_thread(extract)
            self.update_progress('status_getting_info', 100)
            
            formats = []
            if info and 'formats' in info:
                seen = set()
                for f in info['formats']:
                    height = f.get('height')
                    if height and height not in seen:
                        quality = f"{height}p"
                        formats.append({
                            'id': f.get('format_id', 'best'),
                            'quality': quality,
                            'ext': f.get('ext', 'mp4')
                        })
                        seen.add(height)
            
            if formats:
                return sorted(formats, key=lambda x: int(x['quality'][:-1]) if x['quality'][:-1].isdigit() else 0, reverse=True)
            
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]
            
        except Exception as e:
            logger.error(f"[VK] Format error: {e}")
            return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, yt-dlp fallback"""
        logger.info(f"[VK] Downloading: {url}")
        self.update_progress('status_downloading', 0)
        
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        processed_url = self.preprocess_url(url)
        
        # === 1. Try Cobalt first ===
        if self._cobalt:
            try:
                logger.info("[VK] Trying Cobalt...")
                self.update_progress('status_downloading', 10)
                
                # Default to 720p to avoid huge files
                quality = format_id if format_id and format_id != 'best' else "720"
                result = await self._cobalt.request(processed_url, video_quality=quality)
                
                if result.success and result.url:
                    logger.info("[VK] Cobalt success, downloading...")
                    self.update_progress('status_downloading', 30)
                    
                    import requests
                    response = await asyncio.to_thread(
                        requests.get, result.url,
                        headers={'User-Agent': 'Mozilla/5.0'},
                        timeout=300
                    )
                    
                    if response.status_code == 200:
                        # Generate filename
                        video_id = self._extract_video_id(processed_url)
                        filename = result.filename or f"vk_{video_id}.mp4"
                        file_path = download_dir / filename
                        
                        with open(file_path, 'wb') as f:
                            f.write(response.content)
                        
                        self.update_progress('status_downloading', 100)
                        logger.info(f"[VK] Cobalt download completed: {file_path}")
                        return "", file_path
            except Exception as e:
                logger.warning(f"[VK] Cobalt failed: {e}, trying yt-dlp...")
        
        # === 2. Fallback to yt-dlp ===
        logger.info("[VK] Trying yt-dlp...")
        self.update_progress('status_downloading', 40)
        
        try:
            video_id = self._extract_video_id(processed_url)
            temp_filename = f"vk_{video_id or os.urandom(4).hex()}"
            
            # Format selection - default to 720p max to avoid huge files
            if format_id and format_id != 'best':
                # User selected specific quality
                height = format_id.replace('p', '') if format_id.endswith('p') else format_id
                format_str = f'best[height<={height}][ext=mp4]/best[height<={height}]/best[height<=720]'
            else:
                # Default: max 720p to avoid 5GB files
                format_str = 'best[height<=720][ext=mp4]/best[height<=720]/best[height<=480]'
            
            logger.info(f"[VK] Using format: {format_str}")
            
            ydl_opts = {
                'format': format_str,
                'outtmpl': str(download_dir / f"{temp_filename}.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [self._progress_hook],
            }
            
            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)
                logger.info(f"[VK] Using cookies file: {self.cookie_file}")
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(processed_url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if not info:
                raise DownloadError("Не удалось загрузить видео")
            
            # Find downloaded file
            for file in download_dir.glob(f"{temp_filename}.*"):
                if file.is_file():
                    self.update_progress('status_downloading', 100)
                    logger.info(f"[VK] yt-dlp download completed: {file}")
                    
                    # Build metadata
                    title = info.get('title', 'VK Video')
                    uploader = info.get('uploader', '')
                    metadata = f"🎬 {title}"
                    if uploader:
                        metadata += f"\n👤 {uploader}"
                    
                    return metadata, file
            
            raise DownloadError("Загруженный файл не найден")
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"[VK] yt-dlp error: {error_msg}")
            
            if "This video is only available for registered users" in error_msg:
                raise DownloadError("Это видео доступно только для зарегистрированных пользователей VK")
            elif "Video is not available" in error_msg:
                raise DownloadError("Видео недоступно или удалено")
            elif "Private video" in error_msg:
                raise DownloadError("Это приватное видео")
            else:
                raise DownloadError(f"Ошибка загрузки: {error_msg}")
                
        except Exception as e:
            logger.error(f"[VK] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from VK URL"""
        # Pattern: video-123456_789012 or video123456_789012
        match = re.search(r'video(-?\d+_\d+)', url)
        if match:
            return match.group(1)
        return os.urandom(4).hex()

    def _progress_hook(self, d: Dict[str, Any]):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 50) + 40  # 40-90%
                    self.update_progress('status_downloading', progress)
            except:
                pass
        elif d['status'] == 'finished':
            self.update_progress('status_downloading', 95)
