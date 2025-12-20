import os
import re
import logging
import asyncio
from pathlib import Path
from typing import Tuple, Dict, List, Optional
import requests
import yt_dlp

from .base import BaseDownloader, DownloadError
from ..config import DOWNLOADS_DIR
from ..utils.proxy_provider import proxy_provider

logger = logging.getLogger(__name__)

class YandexMusicDownloader(BaseDownloader):
    """Downloader for Yandex Music"""

    def __init__(self):
        super().__init__()
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize Yandex Music client"""
        try:
            from yandex_music import Client
            token = os.getenv('YANDEX_MUSIC_TOKEN')
            if not token:
                logger.info("YANDEX_MUSIC_TOKEN not found, will use YouTube fallback")
                return
            
            try:
                self.client = Client(token).init()
                logger.info("Yandex Music client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Yandex Music client: {e}")
                self.client = None
        except ImportError:
            logger.warning("yandex_music library not installed, will use YouTube fallback")

    def _ru_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Request helper that rotates RU proxies to avoid 451."""
        proxies_to_try = []

        manual_proxy = os.getenv("YANDEX_PROXY")
        if manual_proxy:
            if not manual_proxy.startswith("http"):
                manual_proxy = f"http://{manual_proxy}"
            proxies_to_try.append({"http": manual_proxy, "https": manual_proxy})

        allow_public = os.getenv("YANDEX_USE_PUBLIC_PROXIES", "1") not in ("0", "false", "False")
        if allow_public:
            prox = proxy_provider.get_proxy(country="ru")
            if prox:
                proxies_to_try.append(prox)

        proxies_to_try.append(None)  # final direct attempt

        last_response: Optional[requests.Response] = None
        for prox in proxies_to_try:
            try:
                resp = requests.request(method, url, proxies=prox, **kwargs)
                last_response = resp
                # Accept anything except hard geo block codes
                if resp.status_code not in (451, 403):
                    return resp
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[Yandex] request failed via proxy {prox}: {e}")
                continue
        return last_response

    def platform_id(self) -> str:
        return "yandex_music"

    def can_handle(self, url: str) -> bool:
        """Check if URL is from Yandex Music"""
        patterns = [
            r'music\.yandex\.[a-z]+/album/(\d+)/track/(\d+)',
            r'music\.yandex\.[a-z]+/track/(\d+)',
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def _extract_track_id(self, url: str) -> str:
        """Extract track ID from URL"""
        # Try album/track pattern first
        match = re.search(r'album/(\d+)/track/(\d+)', url)
        if match:
            return f"{match.group(2)}:{match.group(1)}"
        
        # Try direct track pattern
        match = re.search(r'track/(\d+)', url)
        if match:
            return match.group(1)
        
        raise DownloadError("Could not extract track ID from URL")

    async def _get_track_info_via_oembed(self, url: str) -> Optional[Dict]:
        """Get track info using Yandex Music oEmbed API"""
        logger.info(f"[Yandex] Trying oEmbed API for: {url}")
        
        try:
            # oEmbed endpoint
            oembed_url = f"https://music.yandex.ru/oembed/?url={url}&format=json"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                'Accept': 'application/json',
            }
            
            response = await asyncio.to_thread(
                self._ru_request, "GET", oembed_url, headers=headers, timeout=10
            )
            
            if response and response.status_code == 200:
                data = response.json()
                title = data.get('title', '')
                author = data.get('author_name', '')
                
                if title:
                    if author and author not in title:
                        query = f"{author} - {title}"
                    else:
                        query = title
                    logger.info(f"[Yandex] Got from oEmbed: {query}")
                    return {'search_query': query, 'title': title, 'artist': author}
            
            logger.info(f"[Yandex] oEmbed failed: {response.status_code}")
        except Exception as e:
            logger.info(f"[Yandex] oEmbed error: {e}")
        
        return None

    async def _get_track_info_via_mobile(self, track_id: str, album_id: str = None) -> Optional[Dict]:
        """Get track info via mobile API"""
        logger.info(f"[Yandex] Trying mobile API for track: {track_id}")
        
        try:
            headers = {
                'User-Agent': 'YandexMusic/5.0 (iPhone; iOS 16.0)',
                'Accept': 'application/json',
                'X-Yandex-Music-Client': 'YandexMusicAndroid/24123456',
            }
            
            api_url = f"https://api.music.yandex.net/tracks/{track_id}"
            
            response = await asyncio.to_thread(
                self._ru_request, "GET", api_url, headers=headers, timeout=10
            )
            
            if response and response.status_code == 200:
                data = response.json()
                if data.get('result') and len(data['result']) > 0:
                    track = data['result'][0]
                    title = track.get('title', '')
                    artists = [a.get('name', '') for a in track.get('artists', [])]
                    artist_str = ', '.join(filter(None, artists))
                    
                    if title:
                        query = f"{artist_str} - {title}" if artist_str else title
                        logger.info(f"[Yandex] Got from mobile API: {query}")
                        return {'search_query': query, 'title': title, 'artist': artist_str}
            
            logger.info(f"[Yandex] Mobile API failed: {response.status_code}")
        except Exception as e:
            logger.info(f"[Yandex] Mobile API error: {e}")
        
        return None

    async def _get_track_info_via_ytdlp(self, url: str) -> Optional[Dict]:
        """Get track info using yt-dlp extract_info without downloading"""
        logger.info(f"[Yandex] Extracting track info via yt-dlp: {url}")
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                
                if info:
                    title = info.get('title', '')
                    artist = info.get('artist', '') or info.get('uploader', '') or info.get('creator', '')
                    album = info.get('album', '')
                    
                    # Clean up title - remove "слушать онлайн" etc
                    title = re.sub(r'\s*[-—]\s*(слушать|listen).*$', '', title, flags=re.IGNORECASE)
                    
                    if title and artist:
                        query = f"{artist} - {title}"
                        logger.info(f"[Yandex] Got from yt-dlp: {query}")
                        return {'search_query': query, 'title': title, 'artist': artist, 'album': album}
                    elif title:
                        logger.info(f"[Yandex] Got title from yt-dlp: {title}")
                        return {'search_query': title, 'title': title}
                        
        except Exception as e:
            logger.info(f"[Yandex] yt-dlp extract failed: {e}")
        
        return None

    async def _get_track_info_from_page(self, url: str, track_id: str = None, album_id: str = None) -> Optional[Dict]:
        """Get track info using multiple methods"""
        
        # 1. Try oEmbed first (often works without geo restrictions)
        oembed_result = await self._get_track_info_via_oembed(url)
        if oembed_result:
            return oembed_result
        
        # 2. Try mobile API
        if track_id:
            mobile_result = await self._get_track_info_via_mobile(track_id, album_id)
            if mobile_result:
                return mobile_result
        
        # 3. Try yt-dlp
        ytdlp_result = await self._get_track_info_via_ytdlp(url)
        if ytdlp_result:
            return ytdlp_result
        
        # 4. Try parsing HTML page
        logger.info(f"[Yandex] Fetching track info from page: {url}")
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            
            response = await asyncio.to_thread(self._ru_request, "GET", url, headers=headers, timeout=15)
            
            if not response or response.status_code != 200:
                status = response.status_code if response else "no response"
                logger.info(f"[Yandex] Page request failed: {status}")
                return None
            
            html = response.text
            
            # Extract both title and description
            title = None
            artist = None
            
            # Try to find JSON data in page (Yandex embeds track data)
            json_match = re.search(r'"track":\s*(\{[^}]+\})', html)
            if json_match:
                try:
                    import json
                    track_data = json.loads(json_match.group(1))
                    title = track_data.get('title')
                    if title:
                        logger.info(f"[Yandex] Found title in JSON: {title}")
                except:
                    pass
            
            # Get og:title (track name)
            og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og_title and not title:
                potential_title = og_title.group(1)
                # Skip default Yandex titles
                if 'собираем музыку' not in potential_title.lower() and 'яндекс музыка' not in potential_title.lower():
                    title = potential_title
                    logger.info(f"[Yandex] Found og:title: {title}")
            
            # Get og:description (format: "Artist • Трек • Year" or "Artist • Альбом • Year")
            og_desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html)
            if og_desc:
                desc = og_desc.group(1)
                logger.info(f"[Yandex] Found og:description: {desc}")
                # Extract artist (first part before •)
                parts = desc.split('•')
                if parts:
                    artist = parts[0].strip()
            
            # Build search query with artist + title
            if title and artist:
                query = f"{artist} - {title}"
                logger.info(f"[Yandex] Search query: {query}")
                return {'search_query': query}
            elif title:
                logger.info(f"[Yandex] Using title only: {title}")
                return {'search_query': title}
            
            # Fallback: title tag (but skip default titles)
            title_tag = re.search(r'<title>([^<]+)</title>', html)
            if title_tag:
                title = title_tag.group(1)
                # Skip default Yandex Music titles
                if 'собираем музыку' in title.lower() or title.lower().startswith('яндекс музыка'):
                    logger.info(f"[Yandex] Skipping default title: {title}")
                    return None
                title = re.sub(r'\s*[-—|]\s*(слушать|listen).*$', '', title, flags=re.IGNORECASE)
                logger.info(f"[Yandex] Found title tag: {title}")
                return {'search_query': title}
            
            logger.info("[Yandex] Could not extract track info from page")
            return None
            
        except Exception as e:
            logger.error(f"[Yandex] Failed to fetch page: {e}")
            return None

    async def _get_track_info_from_api(self, track_id: str) -> Optional[Dict]:
        """Get track info from Yandex Music API (requires token)"""
        if not self.client:
            return None
        
        try:
            track = self.client.tracks([track_id])[0]
            if track:
                return {
                    'title': track.title,
                    'artists': [artist.name for artist in track.artists],
                    'album': track.albums[0].title if track.albums else None,
                    'duration_ms': track.duration_ms,
                    'track': track
                }
        except Exception as e:
            logger.error(f"Failed to get track info from API: {e}")
        return None

    async def _download_from_youtube(self, query: str) -> Optional[Tuple[str, Path]]:
        """Download audio from YouTube search"""
        logger.info(f"[Yandex] Downloading from YouTube: {query}")
        
        # Prepare filename from query
        safe_filename = self._prepare_filename(query)
        
        # Download best audio without conversion (no ffmpeg needed)
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
            'outtmpl': str(DOWNLOADS_DIR / f"{safe_filename}.%(ext)s"),
            'nooverwrites': True,
            'no_color': True,
            'quiet': False,
            'progress_hooks': [self._progress_hook],
            'default_search': 'ytsearch1',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_progress('status_downloading', 40)
                info = await asyncio.to_thread(
                    ydl.extract_info, f"ytsearch1:{query}", download=True
                )
                
                if info:
                    entry = info
                    if 'entries' in info and len(info['entries']) > 0:
                        entry = info['entries'][0]
                    
                    title = entry.get('title', query)
                    channel = entry.get('uploader', 'Unknown')
                    duration_secs = entry.get('duration', 0)
                    duration_mins = duration_secs // 60
                    duration_rem = duration_secs % 60
                    
                    metadata = f"{title}\nBy: {channel}\nLength: {duration_mins}:{duration_rem:02d}\n(via YouTube)"
                    
                    # Find the downloaded file
                    actual_filename = ydl.prepare_filename(entry)
                    actual_path = Path(actual_filename)
                    if actual_path.exists():
                        return metadata, actual_path
                    
                    # Try common extensions
                    base_path = Path(actual_filename).with_suffix('')
                    for ext in ['.m4a', '.webm', '.opus', '.mp3', '.ogg']:
                        check_path = base_path.with_suffix(ext)
                        if check_path.exists():
                            return metadata, check_path
                    
                    # Search in downloads dir
                    for f in DOWNLOADS_DIR.glob(f"{safe_filename}.*"):
                        return metadata, f
                    
        except Exception as e:
            logger.error(f"[Yandex] YouTube download failed: {e}")
        return None

    async def get_formats(self, url: str) -> List[Dict]:
        """Get available formats - for Yandex Music it's just MP3"""
        return [{
            'id': 'mp3',
            'quality': 'MP3 320kbps',
            'ext': 'mp3'
        }]

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        """Download track from Yandex Music or YouTube fallback"""
        try:
            self.update_progress('status_downloading', 0)
            track_id = self._extract_track_id(url)
            logger.info(f"[Yandex] Track ID: {track_id}")

            # Try Yandex Music API first if client is available
            if self.client:
                try:
                    track_info = await self._get_track_info_from_api(track_id)
                    if track_info and track_info.get('track'):
                        track = track_info['track']
                        
                        self.update_progress('status_downloading', 20)
                        download_info = track.get_download_info()
                        if download_info:
                            best_info = max(download_info, key=lambda x: x.bitrate_in_kbps)
                            
                            title = self._prepare_filename(track.title)
                            artists = ", ".join(artist.name for artist in track.artists)
                            filename = f"{artists} - {title}.mp3"
                            file_path = DOWNLOADS_DIR / filename

                            self.update_progress('status_downloading', 60)
                            track.download(file_path)
                            self.update_progress('status_downloading', 100)

                            metadata = []
                            metadata.append(f"{track.title}")
                            if artists:
                                metadata.append(f"By: {artists}")
                            if track.albums and track.albums[0].title:
                                metadata.append(f"Album: {track.albums[0].title}")
                            duration_mins = track.duration_ms // 60000
                            duration_secs = (track.duration_ms % 60000) // 1000
                            metadata.append(f"Length: {duration_mins}:{duration_secs:02d}")

                            return " | ".join(metadata), file_path
                except Exception as e:
                    logger.info(f"[Yandex] API download failed: {e}, trying YouTube fallback")

            # YouTube fallback - first try to get track info from page/API
            self.update_progress('status_downloading', 20)
            
            # Clean URL for fetching
            clean_url = url.split('?')[0]  # Remove query params
            
            # Extract track_id and album_id for API call
            track_only_id = track_id.split(':')[0] if ':' in track_id else track_id
            album_only_id = track_id.split(':')[1] if ':' in track_id else None
            
            # Try to get track info from page/API
            page_info = await self._get_track_info_from_page(clean_url, track_only_id, album_only_id)
            search_query = None
            
            if page_info and page_info.get('search_query'):
                search_query = page_info['search_query']
                logger.info(f"[Yandex] Using search query from page: {search_query}")
            elif self.client:
                # Try API as fallback for search query
                track_info = await self._get_track_info_from_api(track_id)
                if track_info:
                    artists = ", ".join(track_info['artists'])
                    search_query = f"{artists} - {track_info['title']}"
            
            if not search_query:
                raise DownloadError(
                    "Unable to build a search query from Yandex Music metadata; try another link or configure a RU proxy."
                )

            # Download from YouTube
            self.update_progress('status_downloading', 30)
            result = await self._download_from_youtube(search_query)
            
            if result:
                metadata, file_path = result
                self.update_progress('status_downloading', 100)
                return metadata, file_path

            raise DownloadError("Unable to download the track via YouTube fallback.")

        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"[Yandex] Error downloading: {str(e)}", exc_info=True)
            raise DownloadError(f"Download failed: {str(e)}")

    def _progress_hook(self, d: Dict):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    progress = int((downloaded / total) * 60) + 30
                    self.update_progress('status_downloading', progress)
            except Exception:
                pass
