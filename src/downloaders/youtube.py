import re
import os
import logging
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import yt_dlp
from urllib.parse import urlparse, parse_qs
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class YouTubeDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()
        self.cookie_file = Path(__file__).parent.parent.parent / "cookies" / "youtube.txt"
        self._video_info_cache = {}
        # Import Cobalt service
        try:
            from ..utils.cobalt_service import cobalt
            self._cobalt = cobalt
        except:
            self._cobalt = None

    def platform_id(self) -> str:
        return 'youtube'

    def _is_music_url(self, url: str) -> bool:
        return 'music.youtube.com' in url.lower()

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(
            parsed.netloc and any(domain in parsed.netloc.lower() 
            for domain in ['youtube.com', 'www.youtube.com', 'youtu.be', 'music.youtube.com'])
        )

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'
        if 'music.youtube.com' in parsed.netloc:
            if '/watch' in parsed.path:
                query = parse_qs(parsed.query)
                video_id = query.get('v', [None])[0]
                if video_id:
                    return f'https://www.youtube.com/watch?v={video_id}'
            return url
        if 'youtube.com' in parsed.netloc:
            if '/shorts/' in parsed.path:
                video_id = parsed.path.split('/shorts/')[1].split('?')[0]
                return f'https://www.youtube.com/watch?v={video_id}'
        return url

    async def get_video_info(self, url: str) -> Dict:
        """Get video info including title, thumbnail, duration"""
        processed_url = self.preprocess_url(url)
        if processed_url in self._video_info_cache:
            return self._video_info_cache[processed_url]
        
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        if self.cookie_file.exists():
            ydl_opts['cookiefile'] = str(self.cookie_file)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, processed_url, download=False)
            if info:
                result = {
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration', 0),
                    'channel': info.get('channel') or info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'id': info.get('id'),
                    'formats': info.get('formats', [])
                }
                self._video_info_cache[processed_url] = result
                return result
        except Exception as e:
            logger.debug(f"[YouTube] get_video_info failed: {e}")
        return {}

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats for URL"""
        try:
            self.update_progress('status_getting_info', 0)
            info = await self.get_video_info(url)
            
            if info and info.get('formats'):
                formats = []
                seen = set()
                for f in info['formats']:
                    height = f.get('height')
                    if not height:
                        continue
                    quality = f"{height}p"
                    if quality not in seen and height in [360, 480, 720, 1080, 1440, 2160]:
                        formats.append({'id': str(height), 'quality': quality, 'ext': 'mp4'})
                        seen.add(quality)
                formats = sorted(formats, key=lambda x: int(x['id']), reverse=True)[:4]
                return formats
            raise DownloadError("Не удалось получить информацию о видео")
        except Exception as e:
            logger.error(f"[YouTube] Format extraction failed: {e}")
            raise DownloadError(f"Ошибка при получении форматов: {str(e)}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video/audio from URL - uses Cobalt first, then yt-dlp fallback"""
        try:
            self.update_progress('status_downloading', 0)
            processed_url = self.preprocess_url(url)
            is_music = self._is_music_url(url)
            logger.info(f"[YouTube] Downloading: {processed_url} (music={is_music}, format={format_id})")

            download_dir = Path(__file__).parent.parent.parent / "downloads"
            download_dir.mkdir(exist_ok=True)
            
            # For YouTube Music - download as audio with metadata
            if is_music:
                return await self._download_music(url, download_dir)
            
            # For audio format
            if format_id == 'audio':
                return await self._download_audio(processed_url, download_dir)
            
            # Try Cobalt first (most reliable for YouTube)
            if self._cobalt:
                try:
                    logger.info("[YouTube] Trying Cobalt API...")
                    quality = format_id if format_id and format_id != 'best' else "1080"
                    result = await self._cobalt.request(processed_url, video_quality=quality)
                    
                    if result.success and result.url:
                        logger.info("[YouTube] Cobalt success, downloading...")
                        self.update_progress('status_downloading', 30)
                        
                        # Download the file
                        import requests
                        response = await asyncio.to_thread(
                            requests.get, result.url, 
                            headers={'User-Agent': 'Mozilla/5.0'}, 
                            timeout=300
                        )
                        
                        if response.status_code == 200:
                            # Extract video ID for filename
                            video_id = processed_url.split('v=')[-1].split('&')[0] if 'v=' in processed_url else 'video'
                            filename = result.filename or f"{video_id}.mp4"
                            file_path = download_dir / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(response.content)
                            
                            self.update_progress('status_downloading', 100)
                            logger.info(f"[YouTube] Cobalt download completed: {file_path}")
                            return "", file_path
                except Exception as e:
                    logger.warning(f"[YouTube] Cobalt failed: {e}, trying yt-dlp...")
            
            # Fallback to yt-dlp
            return await self._download_with_ytdlp(processed_url, download_dir, format_id)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[YouTube] Download failed: {error_msg}")
            if "Private video" in error_msg:
                raise DownloadError("Это приватное видео")
            elif "Sign in" in error_msg:
                raise DownloadError("Требуется авторизация")
            else:
                raise DownloadError(f"Ошибка загрузки: {error_msg}")

    async def _download_with_ytdlp(self, url: str, download_dir: Path, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download using yt-dlp"""
        self.update_progress('status_downloading', 10)
        
        if format_id == 'audio':
            format_str = 'bestaudio/best'
        elif format_id and format_id != 'best':
            format_str = f'best[height<={format_id}][ext=mp4]/best[height<={format_id}]/best[ext=mp4]/best'
        else:
            format_str = 'best[ext=mp4]/best'
        
        ydl_opts = {
            'format': format_str,
            'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }
        if self.cookie_file.exists():
            ydl_opts['cookiefile'] = str(self.cookie_file)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            if info:
                filename = ydl.prepare_filename(info)
                file_path = Path(filename).resolve()
                
                if not file_path.exists():
                    mp4_path = file_path.with_suffix('.mp4')
                    if mp4_path.exists():
                        file_path = mp4_path
                    else:
                        video_id = info.get('id', '')
                        for f in download_dir.glob(f"{video_id}.*"):
                            if f.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                                file_path = f
                                break
                
                if file_path.exists():
                    logger.info(f"[YouTube] yt-dlp download completed: {file_path}")
                    return "", file_path

        raise DownloadError("Не удалось загрузить видео")

    async def _download_audio(self, url: str, download_dir: Path) -> Tuple[str, Path]:
        """Download as audio only - uses Cobalt first"""
        try:
            self.update_progress('status_downloading', 10)
            
            # Try Cobalt first
            if self._cobalt:
                try:
                    logger.info("[YouTube] Trying Cobalt for audio...")
                    result = await self._cobalt.request(url, download_mode="audio", audio_format="mp3")
                    
                    if result.success and result.url:
                        import requests
                        response = await asyncio.to_thread(
                            requests.get, result.url,
                            headers={'User-Agent': 'Mozilla/5.0'},
                            timeout=180
                        )
                        
                        if response.status_code == 200:
                            video_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else 'audio'
                            filename = result.filename or f"{video_id}.mp3"
                            file_path = download_dir / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(response.content)
                            
                            logger.info(f"[YouTube] Cobalt audio download completed: {file_path}")
                            return "", file_path
                except Exception as e:
                    logger.warning(f"[YouTube] Cobalt audio failed: {e}")
            
            # Fallback to yt-dlp
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            if self.cookie_file.exists():
                ydl_opts['cookiefile'] = str(self.cookie_file)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            
            if info:
                video_id = info.get('id', 'audio')
                for ext in ['.m4a', '.mp3', '.webm', '.opus', '.mp4']:
                    audio_path = download_dir / f"{video_id}{ext}"
                    if audio_path.exists():
                        return "", audio_path
                
                for f in download_dir.glob(f"{video_id}.*"):
                    return "", f
            
            raise DownloadError("Не удалось скачать аудио")
            
        except Exception as e:
            logger.error(f"[YouTube] Audio download failed: {e}")
            raise DownloadError(f"Ошибка загрузки аудио: {str(e)}")

    async def _download_music(self, url: str, download_dir: Path) -> Tuple[str, Path, Optional[str]]:
        """Download YouTube Music as audio with metadata"""
        try:
            self.update_progress('status_downloading', 10)
            processed_url = self.preprocess_url(url)
            
            # Get info first
            info = await self.get_video_info(url)
            title = info.get('title', 'Unknown') if info else 'Unknown'
            artist = info.get('channel', 'Unknown') if info else 'Unknown'
            duration = info.get('duration', 0) if info else 0
            view_count = info.get('view_count', 0) if info else 0
            video_id = info.get('id', 'audio') if info else 'audio'
            thumbnail_url = info.get('thumbnail') if info else None
            
            self.update_progress('status_downloading', 30)
            
            # Try Cobalt first
            audio_path = None
            if self._cobalt:
                try:
                    logger.info("[YouTube Music] Trying Cobalt...")
                    result = await self._cobalt.request(processed_url, download_mode="audio", audio_format="mp3")
                    
                    if result.success and result.url:
                        import requests
                        response = await asyncio.to_thread(
                            requests.get, result.url,
                            headers={'User-Agent': 'Mozilla/5.0'},
                            timeout=180
                        )
                        
                        if response.status_code == 200:
                            filename = result.filename or f"{video_id}.mp3"
                            audio_path = download_dir / filename
                            
                            with open(audio_path, 'wb') as f:
                                f.write(response.content)
                            
                            logger.info(f"[YouTube Music] Cobalt download completed: {audio_path}")
                except Exception as e:
                    logger.warning(f"[YouTube Music] Cobalt failed: {e}")
            
            # Fallback to yt-dlp
            if not audio_path or not audio_path.exists():
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': str(download_dir / f'{video_id}.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                }
                if self.cookie_file.exists():
                    ydl_opts['cookiefile'] = str(self.cookie_file)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    await asyncio.to_thread(ydl.extract_info, processed_url, download=True)
                
                for ext in ['.m4a', '.mp3', '.webm', '.opus', '.mp4']:
                    path = download_dir / f"{video_id}{ext}"
                    if path.exists():
                        audio_path = path
                        break
            
            if audio_path and audio_path.exists():
                logger.info(f"[YouTube Music] Downloaded: {title} - {artist}")
                self.update_progress('status_downloading', 100)
                
                # Format metadata
                minutes = duration // 60
                seconds = duration % 60
                length = f"{minutes}:{seconds:02d}"
                
                if view_count >= 1_000_000:
                    plays = f"{view_count/1_000_000:.1f}M"
                elif view_count >= 1_000:
                    plays = f"{view_count/1_000:.1f}K"
                else:
                    plays = str(view_count)
                
                metadata = f"{title} | By: {artist} | Length: {length} | Plays: {plays} | <a href=\"{url}\">Ссылка</a>"
                
                # Return with thumbnail URL
                if thumbnail_url:
                    metadata = f"THUMB:{thumbnail_url}|{metadata}"
                
                return metadata, audio_path, thumbnail_url
            
            raise DownloadError("Не удалось найти скачанный файл")
            
        except Exception as e:
            logger.error(f"[YouTube Music] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки музыки: {str(e)}")
