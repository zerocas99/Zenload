"""
YouTube downloader that uses external YouTube API service
"""

import asyncio
import json
import logging
import os
import aiohttp
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from ..config import DOWNLOADS_DIR
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

# YouTube API service URL (the bot/ service running on Railway)
YOUTUBE_API_URL = os.getenv("YOUTUBE_API_URL", "")


class YouTubeDownloader(BaseDownloader):
    """YouTube downloader using external API service."""

    def __init__(self):
        super().__init__()
        self.download_dir = DOWNLOADS_DIR
        self.download_dir.mkdir(exist_ok=True)
        self.api_url = YOUTUBE_API_URL
        
        if self.api_url:
            logger.info(f"[YouTube] Using API service: {self.api_url}")
        else:
            logger.warning("[YouTube] YOUTUBE_API_URL not set, downloads will fail")

    def platform_id(self) -> str:
        return "youtube"

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return any(domain in host for domain in ("youtube.com", "youtu.be", "music.youtube.com"))

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        if "youtu.be" in host:
            video_id = parsed.path.lstrip("/")
            return f"https://www.youtube.com/watch?v={video_id}"

        if "shorts" in parsed.path:
            video_id = parsed.path.split("/")[-1]
            return f"https://www.youtube.com/watch?v={video_id}"

        if "music.youtube.com" in host and "/watch" in parsed.path:
            query = parse_qs(parsed.query)
            video_id = query.get("v", [None])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

        return url

    async def get_video_info(self, url: str) -> Dict:
        """Fetch video info from API."""
        processed_url = self.preprocess_url(url)
        video_id = self._extract_video_id(processed_url)
        
        if not self.api_url:
            return {
                "title": "YouTube Video",
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else None,
                "duration": 0,
                "channel": None,
                "id": video_id,
            }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/info",
                    json={"url": processed_url},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "title": data.get("title") or "YouTube Video",
                            "thumbnail": data.get("thumbnail"),
                            "duration": data.get("duration") or 0,
                            "channel": data.get("uploader"),
                            "id": video_id,
                        }
        except Exception as e:
            logger.debug(f"[YouTube] Failed to fetch video info: {e}")
        
        return {
            "title": "YouTube Video",
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else None,
            "duration": 0,
            "channel": None,
            "id": video_id,
        }

    async def get_formats(self, url: str) -> List[Dict]:
        """Return available formats."""
        return [
            {"id": "video_1080", "quality": "🎬 Video 1080p", "ext": "mp4"},
            {"id": "video", "quality": "🎬 Video 720p", "ext": "mp4"},
            {"id": "audio", "quality": "🎵 Audio MP3", "ext": "mp3"},
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download via YouTube API service with detailed progress."""
        if not self.api_url:
            raise DownloadError("YouTube API service not configured (YOUTUBE_API_URL)")
        
        processed_url = self.preprocess_url(url)
        
        # Determine mode and quality from format_id
        if format_id == "audio":
            mode = "audio"
            quality = "720"
        elif format_id == "video_1080":
            mode = "video"
            quality = "1080"
        else:  # video or default
            mode = "video"
            quality = "720"
        
        logger.info(f"[YouTube] Downloading ({mode}, {quality}p) via API: {processed_url}")
        self.update_progress("status_downloading", 1)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/download",
                    json={"url": processed_url, "mode": mode, "quality": quality},
                    timeout=aiohttp.ClientTimeout(total=600)  # 10 min timeout
                ) as response:
                    if response.status != 200:
                        try:
                            error_data = await response.json()
                            error_msg = error_data.get("error", "Unknown error")
                        except:
                            error_msg = f"HTTP {response.status}"
                        raise DownloadError(f"API error: {error_msg}")
                    
                    # Get metadata from header
                    metadata_json = response.headers.get("X-Metadata", "{}")
                    try:
                        metadata = json.loads(metadata_json)
                    except:
                        metadata = {}
                    
                    title = metadata.get("title", "")
                    artist = metadata.get("artist", "")
                    thumbnail = metadata.get("thumbnail", "")
                    duration = metadata.get("duration", 0)
                    
                    # Get filename from Content-Disposition header
                    content_disp = response.headers.get("Content-Disposition", "")
                    if "filename*=" in content_disp:
                        # RFC 5987 encoded filename
                        from urllib.parse import unquote
                        filename = content_disp.split("filename*=UTF-8''")[-1].strip()
                        filename = unquote(filename)
                    elif "filename=" in content_disp:
                        filename = content_disp.split("filename=")[-1].strip('"')
                    else:
                        ext = "mp3" if mode == "audio" else "mp4"
                        video_id = self._extract_video_id(processed_url) or "video"
                        filename = f"{video_id}.{ext}"
                    
                    # Get content length for progress
                    content_length = response.headers.get("Content-Length")
                    total_size = int(content_length) if content_length else 0
                    
                    # Download file with progress
                    file_path = self.download_dir / filename
                    downloaded = 0
                    
                    with open(file_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(1024 * 64):  # 64KB chunks
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Update progress (10-90% range for download)
                            if total_size > 0:
                                progress = int((downloaded / total_size) * 80) + 10
                                self.update_progress("status_downloading", min(progress, 90))
                    
                    if not file_path.exists() or file_path.stat().st_size < 1000:
                        raise DownloadError("Downloaded file is too small or missing")
                    
                    self.update_progress("status_downloading", 100)
                    logger.info(f"[YouTube] Downloaded: {file_path} ({downloaded / (1024*1024):.1f}MB)")
                    
                    # Build metadata string
                    meta_parts = []
                    if thumbnail:
                        meta_parts.append(f"THUMB:{thumbnail}")
                    if duration:
                        meta_parts.append(f"DURATION:{duration}")
                    if mode == "audio" and (title or artist):
                        if artist and title:
                            meta_parts.append(f"{artist} - {title}")
                        elif title:
                            meta_parts.append(title)
                    
                    metadata_str = "|".join(meta_parts) if meta_parts else ""
                    
                    return metadata_str, file_path
                    
        except aiohttp.ClientError as e:
            logger.error(f"[YouTube] API connection error: {e}")
            raise DownloadError(f"Cannot connect to YouTube API: {e}")
        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"[YouTube] Download error: {e}")
            raise DownloadError(f"Download failed: {e}")

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        parsed = urlparse(url)
        if "v=" in parsed.query:
            return parse_qs(parsed.query).get("v", [None])[0]
        parts = parsed.path.rstrip("/").split("/")
        if parts:
            return parts[-1]
        return None
