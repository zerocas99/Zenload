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
        # Import YouTube JS fallback (ytdl-core-enhanced) - DISABLED: YouTube blocks datacenter IPs
        # try:
        #     from ..utils.youtube_js_fallback import youtube_js
        #     self._youtube_js = youtube_js
        # except:
        #     self._youtube_js = None
        self._youtube_js = None  # Disabled - YouTube blocks datacenter IPs
        # Import Piped fallback - DISABLED: Most instances are down
        # try:
        #     from ..utils.piped_fallback import piped
        #     self._piped = piped
        # except:
        #     self._piped = None
        self._piped = None  # Disabled - most instances are down

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
        
        # Return basic info without calling yt-dlp (to avoid 403 errors)
        # Cobalt will handle the actual download
        video_id = None
        if 'v=' in processed_url:
            video_id = processed_url.split('v=')[-1].split('&')[0]
        elif 'youtu.be/' in url:
            video_id = url.split('youtu.be/')[-1].split('?')[0]
        
        result = {
            'title': 'YouTube Video',
            'thumbnail': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg' if video_id else None,
            'duration': 0,
            'channel': 'Unknown',
            'view_count': 0,
            'id': video_id,
            'formats': []
        }
        self._video_info_cache[processed_url] = result
        return result

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats for URL - simplified, Cobalt handles quality"""
        # Return standard formats - Cobalt will handle actual quality selection
        return [
            {'id': '1080', 'quality': '1080p', 'ext': 'mp4'},
            {'id': '720', 'quality': '720p', 'ext': 'mp4'},
            {'id': '480', 'quality': '480p', 'ext': 'mp4'},
            {'id': '360', 'quality': '360p', 'ext': 'mp4'},
        ]

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
                    logger.warning(f"[YouTube] Cobalt failed: {e}, trying JS fallback...")
            
            # Try YouTube JS fallback (ytdl-core-enhanced)
            if self._youtube_js:
                try:
                    logger.info("[YouTube] Trying ytdl-core-enhanced via Node.js...")
                    result = await self._youtube_js.get_video_url(processed_url)
                    
                    if result.success and result.content:
                        logger.info(f"[YouTube] JS fallback success, got {len(result.content)} bytes")
                        self.update_progress('status_downloading', 80)
                        
                        video_id = processed_url.split('v=')[-1].split('&')[0] if 'v=' in processed_url else 'video'
                        ext = result.container or 'mp4'
                        filename = f"{video_id}.{ext}"
                        file_path = download_dir / filename
                        
                        with open(file_path, 'wb') as f:
                            f.write(result.content)
                        
                        self.update_progress('status_downloading', 100)
                        logger.info(f"[YouTube] JS fallback download completed: {file_path}")
                        return "", file_path
                    else:
                        logger.warning(f"[YouTube] JS fallback failed: {result.error}")
                except Exception as e:
                    logger.warning(f"[YouTube] JS fallback failed: {e}, trying Piped...")
            
            # Try Piped API
            if self._piped:
                try:
                    logger.info("[YouTube] Trying Piped API...")
                    quality = format_id if format_id and format_id != 'best' else "720"
                    result = await self._piped.get_video_url(processed_url, quality)
                    
                    if result.success and result.url:
                        logger.info("[YouTube] Piped success, downloading...")
                        self.update_progress('status_downloading', 30)
                        
                        import requests
                        response = await asyncio.to_thread(
                            requests.get, result.url,
                            headers={'User-Agent': 'Mozilla/5.0'},
                            timeout=300
                        )
                        
                        if response.status_code == 200:
                            video_id = processed_url.split('v=')[-1].split('&')[0] if 'v=' in processed_url else 'video'
                            filename = f"{video_id}.mp4"
                            file_path = download_dir / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(response.content)
                            
                            self.update_progress('status_downloading', 100)
                            logger.info(f"[YouTube] Piped download completed: {file_path}")
                            return "", file_path
                except Exception as e:
                    logger.warning(f"[YouTube] Piped failed: {e}, trying yt-dlp...")
            
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
        """Download as audio only - uses Cobalt first, then JS fallback"""
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
            
            # Try YouTube JS fallback
            if self._youtube_js:
                try:
                    logger.info("[YouTube] Trying JS fallback for audio...")
                    result = await self._youtube_js.get_audio_url(url)
                    
                    if result.success and result.content:
                        logger.info(f"[YouTube] JS audio success, got {len(result.content)} bytes")
                        
                        video_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else 'audio'
                        ext = result.container or 'm4a'
                        filename = f"{video_id}.{ext}"
                        file_path = download_dir / filename
                        
                        with open(file_path, 'wb') as f:
                            f.write(result.content)
                        
                        logger.info(f"[YouTube] JS fallback audio completed: {file_path}")
                        return "", file_path
                    else:
                        logger.warning(f"[YouTube] JS audio failed: {result.error}")
                except Exception as e:
                    logger.warning(f"[YouTube] JS fallback audio failed: {e}")
            
            # Try Piped API for audio
            if self._piped:
                try:
                    logger.info("[YouTube] Trying Piped for audio...")
                    result = await self._piped.get_audio_url(url)
                    
                    if result.success and result.url:
                        import requests
                        response = await asyncio.to_thread(
                            requests.get, result.url,
                            headers={'User-Agent': 'Mozilla/5.0'},
                            timeout=180
                        )
                        
                        if response.status_code == 200:
                            video_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else 'audio'
                            filename = f"{video_id}.m4a"
                            file_path = download_dir / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(response.content)
                            
                            logger.info(f"[YouTube] Piped audio completed: {file_path}")
                            return "", file_path
                except Exception as e:
                    logger.warning(f"[YouTube] Piped audio failed: {e}")
            
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
            
            # Extract video ID
            video_id = None
            if 'v=' in processed_url:
                video_id = processed_url.split('v=')[-1].split('&')[0]
            elif 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[-1].split('?')[0]
            
            if not video_id:
                video_id = 'audio'
            
            thumbnail_url = f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'
            
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
            
            # Try YouTube JS fallback
            if not audio_path or not audio_path.exists():
                if self._youtube_js:
                    try:
                        logger.info("[YouTube Music] Trying JS fallback...")
                        result = await self._youtube_js.get_audio_url(processed_url)
                        
                        if result.success and result.content:
                            logger.info(f"[YouTube Music] JS success, got {len(result.content)} bytes")
                            ext = result.container or 'm4a'
                            filename = f"{video_id}.{ext}"
                            audio_path = download_dir / filename
                            
                            with open(audio_path, 'wb') as f:
                                f.write(result.content)
                            
                            logger.info(f"[YouTube Music] JS fallback completed: {audio_path}")
                        else:
                            logger.warning(f"[YouTube Music] JS failed: {result.error}")
                    except Exception as e:
                        logger.warning(f"[YouTube Music] JS fallback failed: {e}")
            
            # Try Piped API
            if not audio_path or not audio_path.exists():
                if self._piped:
                    try:
                        logger.info("[YouTube Music] Trying Piped...")
                        result = await self._piped.get_audio_url(processed_url)
                        
                        if result.success and result.url:
                            import requests
                            response = await asyncio.to_thread(
                                requests.get, result.url,
                                headers={'User-Agent': 'Mozilla/5.0'},
                                timeout=180
                            )
                            
                            if response.status_code == 200:
                                filename = f"{video_id}.m4a"
                                audio_path = download_dir / filename
                                
                                with open(audio_path, 'wb') as f:
                                    f.write(response.content)
                                
                                logger.info(f"[YouTube Music] Piped completed: {audio_path}")
                    except Exception as e:
                        logger.warning(f"[YouTube Music] Piped failed: {e}")
            
            # Fallback to yt-dlp only if Cobalt failed
            if not audio_path or not audio_path.exists():
                logger.info("[YouTube Music] Trying yt-dlp fallback...")
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': str(download_dir / f'{video_id}.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                }
                if self.cookie_file.exists():
                    ydl_opts['cookiefile'] = str(self.cookie_file)
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        await asyncio.to_thread(ydl.extract_info, processed_url, download=True)
                    
                    for ext in ['.m4a', '.mp3', '.webm', '.opus', '.mp4']:
                        path = download_dir / f"{video_id}{ext}"
                        if path.exists():
                            audio_path = path
                            break
                except Exception as e:
                    logger.warning(f"[YouTube Music] yt-dlp also failed: {e}")
            
            if audio_path and audio_path.exists():
                logger.info(f"[YouTube Music] Downloaded successfully")
                self.update_progress('status_downloading', 100)
                
                # Basic metadata (we don't have full info without yt-dlp)
                metadata = f"YouTube Music | <a href=\"{url}\">Ссылка</a>"
                
                # Return with thumbnail URL
                if thumbnail_url:
                    metadata = f"THUMB:{thumbnail_url}|{metadata}"
                
                return metadata, audio_path, thumbnail_url
            
            raise DownloadError("Не удалось скачать музыку")
            
        except Exception as e:
            logger.error(f"[YouTube Music] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки музыки: {str(e)}")
