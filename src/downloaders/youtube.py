import re
import os
import logging
import asyncio
import aiohttp
import tempfile
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
        self._video_info_cache = {}  # Cache video info for quality selection

    def platform_id(self) -> str:
        """Return platform identifier"""
        return 'youtube'

    def _is_music_url(self, url: str) -> bool:
        """Check if URL is YouTube Music"""
        return 'music.youtube.com' in url.lower()

    def can_handle(self, url: str) -> bool:
        """Check if URL is from YouTube or YouTube Music"""
        parsed = urlparse(url)
        return bool(
            parsed.netloc and any(domain in parsed.netloc.lower() 
            for domain in ['youtube.com', 'www.youtube.com', 'youtu.be', 'music.youtube.com'])
        )

    def preprocess_url(self, url: str) -> str:
        """Clean and validate YouTube URL"""
        parsed = urlparse(url)

        # Handle youtu.be URLs
        if 'youtu.be' in parsed.netloc:
            video_id = parsed.path.lstrip('/')
            return f'https://www.youtube.com/watch?v={video_id}'

        # Handle music.youtube.com URLs - convert to regular youtube for yt-dlp
        if 'music.youtube.com' in parsed.netloc:
            # Extract video ID and convert to regular YouTube URL
            if '/watch' in parsed.path:
                query = parse_qs(parsed.query)
                video_id = query.get('v', [None])[0]
                if video_id:
                    return f'https://www.youtube.com/watch?v={video_id}'
            return url

        # Handle youtube.com URLs
        if 'youtube.com' in parsed.netloc:
            # Handle various YouTube URL formats
            if '/watch' in parsed.path:
                # Regular video URL
                return url
            elif '/shorts/' in parsed.path:
                # YouTube Shorts
                video_id = parsed.path.split('/shorts/')[1].split('?')[0]
                return f'https://www.youtube.com/watch?v={video_id}'
            elif '/playlist' in parsed.path:
                # Return as is - yt-dlp handles playlists
                return url

        return url

    def _get_ydl_opts(self, format_id: Optional[str] = None) -> Dict:
        """Get yt-dlp options"""
        if format_id == 'audio':
            format_str = 'bestaudio[ext=m4a]/bestaudio/best'
        elif format_id and format_id != 'best':
            # For specific quality - prefer single file formats that don't need merging
            format_str = f'best[height<={format_id}][ext=mp4]/best[height<={format_id}]/best[ext=mp4]/best'
        else:
            # Best quality - prefer single file formats
            format_str = 'best[ext=mp4]/best'
        
        opts = {
            'format': format_str,
            'nooverwrites': True,
            'no_color': True,
            'no_warnings': True,
            'quiet': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            },
            'extractor_args': {
                'youtube': {
                    # Use tv client - doesn't require PO Token
                    'player_client': ['tv', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            'socket_timeout': 30,
            'retries': 3,
        }
        if self.cookie_file.exists():
            opts['cookiefile'] = str(self.cookie_file)
        return opts

    async def get_video_info(self, url: str) -> Dict:
        """Get video info including title, thumbnail, duration"""
        processed_url = self.preprocess_url(url)
        
        # Check cache
        if processed_url in self._video_info_cache:
            return self._video_info_cache[processed_url]
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        if self.cookie_file.exists():
            ydl_opts['cookiefile'] = str(self.cookie_file)
        
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
        
        return {}

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats for URL"""
        try:
            self.update_progress('status_getting_info', 0)
            processed_url = self.preprocess_url(url)
            logger.info(f"[YouTube] Getting formats for: {processed_url}")

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
                        formats.append({
                            'id': str(height),
                            'quality': quality,
                            'ext': 'mp4'
                        })
                        seen.add(quality)
                
                # Sort by quality descending
                formats = sorted(formats, key=lambda x: int(x['id']), reverse=True)
                
                # Limit to top qualities
                formats = formats[:4]  # 1080p, 720p, 480p, 360p max
                
                return formats

            raise DownloadError("Не удалось получить информацию о видео")

        except Exception as e:
            logger.error(f"[YouTube] Format extraction failed: {e}")
            if "Private video" in str(e):
                raise DownloadError("Это приватное видео")
            elif "Sign in" in str(e):
                raise DownloadError("Требуется авторизация")
            else:
                raise DownloadError(f"Ошибка при получении форматов: {str(e)}")

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video/audio from URL"""
        try:
            self.update_progress('status_downloading', 0)
            processed_url = self.preprocess_url(url)
            is_music = self._is_music_url(url)
            logger.info(f"[YouTube] Downloading from: {processed_url} (music={is_music}, format={format_id})")

            # Create download directory if not exists
            download_dir = Path(__file__).parent.parent.parent / "downloads"
            download_dir.mkdir(exist_ok=True)
            download_dir = download_dir.resolve()
            
            # For YouTube Music - download as audio with metadata
            if is_music:
                metadata, audio_path, thumbnail_url = await self._download_music(url, download_dir)
                # Store thumbnail URL in metadata for download_manager
                if thumbnail_url:
                    metadata = f"THUMB:{thumbnail_url}|{metadata}"
                return metadata, audio_path
            
            # For audio format
            if format_id == 'audio':
                return await self._download_audio(processed_url, download_dir)
            
            # === Download video with yt-dlp ===
            self.update_progress('status_downloading', 10)
            
            ydl_opts = self._get_ydl_opts(format_id)
            ydl_opts['outtmpl'] = str(download_dir / '%(id)s.%(ext)s')

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(
                    ydl.extract_info, str(processed_url), download=True
                )
                if info:
                    # Get downloaded file path and verify it exists
                    filename = ydl.prepare_filename(info)
                    file_path = Path(filename).resolve()
                    
                    # Handle merged files (may have different extension)
                    if not file_path.exists():
                        # Try mp4 extension
                        mp4_path = file_path.with_suffix('.mp4')
                        if mp4_path.exists():
                            file_path = mp4_path
                        else:
                            # Find any file with the video id
                            video_id = info.get('id', '')
                            for f in download_dir.glob(f"{video_id}.*"):
                                if f.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                                    file_path = f
                                    break
                    
                    if file_path.exists():
                        logger.info(f"[YouTube] Download completed: {file_path}")
                        return "", file_path

            raise DownloadError("Не удалось загрузить видео")

        except Exception as e:
            error_msg = str(e)
            if "Private video" in error_msg:
                raise DownloadError("Это приватное видео")
            elif "Sign in" in error_msg:
                raise DownloadError("Требуется авторизация")
            else:
                logger.error(f"[YouTube] Download failed: {error_msg}")
                raise DownloadError(f"Ошибка загрузки: {error_msg}")

    async def _download_audio(self, url: str, download_dir: Path) -> Tuple[str, Path]:
        """Download as audio only (M4A - no ffmpeg needed)"""
        try:
            self.update_progress('status_downloading', 10)
            
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
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
                # Find audio file (m4a or other)
                for ext in ['.m4a', '.mp3', '.webm', '.opus']:
                    audio_path = download_dir / f"{video_id}{ext}"
                    if audio_path.exists():
                        return "", audio_path
                
                # Try to find any file with the video id
                for f in download_dir.glob(f"{video_id}.*"):
                    if f.suffix.lower() in ['.m4a', '.mp3', '.webm', '.opus', '.ogg']:
                        return "", f
            
            raise DownloadError("Не удалось скачать аудио")
            
        except Exception as e:
            logger.error(f"[YouTube] Audio download failed: {e}")
            raise DownloadError(f"Ошибка загрузки аудио: {str(e)}")

    async def _download_music(self, url: str, download_dir: Path) -> Tuple[str, Path, Optional[str]]:
        """Download YouTube Music as audio. Returns (metadata, file_path, thumbnail_url)"""
        try:
            self.update_progress('status_downloading', 10)
            processed_url = self.preprocess_url(url)
            
            # Get info first with tv client - doesn't require PO Token
            info_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv', 'web'],
                    }
                },
            }
            if self.cookie_file.exists():
                info_opts['cookiefile'] = str(self.cookie_file)
            
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, processed_url, download=False)
            
            if not info:
                raise DownloadError("Не удалось получить информацию о треке")
            
            title = info.get('title', 'Unknown')
            artist = info.get('artist') or info.get('channel') or info.get('uploader', 'Unknown')
            duration = info.get('duration', 0)
            view_count = info.get('view_count', 0)
            video_id = info.get('id', 'audio')
            thumbnail_url = info.get('thumbnail')
            
            self.update_progress('status_downloading', 30)
            
            # Download as audio with tv client - doesn't require PO Token
            audio_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': str(download_dir / f'{video_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv', 'web'],
                    }
                },
            }
            if self.cookie_file.exists():
                audio_opts['cookiefile'] = str(self.cookie_file)
            
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                await asyncio.to_thread(ydl.extract_info, processed_url, download=True)
            
            self.update_progress('status_downloading', 90)
            
            # Find the downloaded audio file
            audio_path = None
            for ext in ['.m4a', '.mp3', '.webm', '.opus']:
                path = download_dir / f"{video_id}{ext}"
                if path.exists():
                    audio_path = path
                    break
            
            if not audio_path:
                for f in download_dir.glob(f"{video_id}.*"):
                    if f.suffix.lower() in ['.m4a', '.mp3', '.webm', '.opus', '.ogg']:
                        audio_path = f
                        break
            
            if audio_path and audio_path.exists():
                logger.info(f"[YouTube Music] Downloaded: {title} - {artist}")
                self.update_progress('status_downloading', 100)
                
                # Format metadata for caption
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
                return metadata, audio_path, thumbnail_url
            
            raise DownloadError("Не удалось найти скачанный файл")
            
        except Exception as e:
            logger.error(f"[YouTube Music] Download failed: {e}")
            raise DownloadError(f"Ошибка загрузки музыки: {str(e)}")

    def _prepare_metadata(self, info: Dict, url: str) -> str:
        """Prepare metadata string from info"""
        def format_number(num):
            if not num:
                return "0"
            if num >= 1000000:
                return f"{num/1000000:.1f}M"
            if num >= 1000:
                return f"{num/1000:.1f}K"
            return str(num)

        likes = format_number(info.get('like_count', 0))
        views = format_number(info.get('view_count', 0))
        channel = info.get('uploader', '')
        channel_url = info.get('uploader_url', url)

        return f"YouTube | {views} | {likes}\nby <a href=\"{channel_url}\">{channel}</a>"


