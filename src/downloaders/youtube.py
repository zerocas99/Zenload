import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import yt_dlp

from ..config import DOWNLOADS_DIR, YOUTUBE_MAX_UPLOAD_MB, COOKIES_DIR
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)


class YouTubeDownloader(BaseDownloader):
    """YouTube downloader using yt-dlp with cookies support."""

    # Same format as working bot/bot.py
    VIDEO_FORMAT = "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best"
    AUDIO_FORMAT = "bestaudio/best"

    def __init__(self):
        super().__init__()
        self.download_dir = DOWNLOADS_DIR
        self.download_dir.mkdir(exist_ok=True)
        self.max_upload_mb = min(YOUTUBE_MAX_UPLOAD_MB, 2000)
        
        # Cookies file path
        self.cookies_file = COOKIES_DIR / "youtube.txt"
        if self.cookies_file.exists():
            logger.info(f"[YouTube] Using cookies from {self.cookies_file}")
        else:
            logger.warning("[YouTube] No cookies file found, downloads may fail with 403")

    def platform_id(self) -> str:
        return "youtube"

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return any(domain in host for domain in ("youtube.com", "youtu.be", "music.youtube.com"))

    def preprocess_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        # Normalize short and shorts links to standard watch URLs
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
        """Fetch basic metadata for preview/keyboard."""
        processed_url = self.preprocess_url(url)
        try:
            def _extract():
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                    return ydl.extract_info(processed_url, download=False)

            info = await asyncio.to_thread(_extract)
            if not info:
                raise ValueError("No info extracted")

            return {
                "title": info.get("title") or "YouTube Video",
                "thumbnail": self._extract_thumbnail(info),
                "duration": info.get("duration") or 0,
                "channel": info.get("uploader"),
                "view_count": info.get("view_count", 0),
                "id": info.get("id") or self._extract_video_id(processed_url),
                "formats": info.get("formats", []),
            }
        except Exception as e:
            logger.debug(f"[YouTube] Failed to fetch video info: {e}")
            video_id = self._extract_video_id(processed_url)
            return {
                "title": "YouTube Video",
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg" if video_id else None,
                "duration": 0,
                "channel": None,
                "view_count": 0,
                "id": video_id,
                "formats": [],
            }

    async def get_formats(self, url: str) -> List[Dict]:
        """Return user-visible quality options."""
        return [
            {"id": "1080", "quality": "1080p", "ext": "mp4"},
            {"id": "720", "quality": "720p", "ext": "mp4"},
            {"id": "480", "quality": "480p", "ext": "mp4"},
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download YouTube video or audio using yt-dlp."""
        processed_url = self.preprocess_url(url)
        mode = "audio" if format_id == "audio" else "video"

        logger.info(f"[YouTube] Downloading ({mode}) {processed_url}")
        self.update_progress("status_downloading", 5)

        try:
            file_path, info = await asyncio.to_thread(self._download_sync, processed_url, mode, format_id)
        except DownloadError:
            raise
        except Exception as e:
            logger.error(f"[YouTube] Download error: {e}", exc_info=True)
            raise DownloadError(f"Download error: {e}")

        if not file_path or not file_path.exists():
            raise DownloadError("File not found after download")

        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_upload_mb:
            try:
                file_path.unlink()
            except Exception:
                pass
            raise DownloadError(f"File too large: {size_mb:.1f} MB > {self.max_upload_mb} MB limit")

        metadata = self.format_metadata(info) if info else ""
        thumbnail = self._extract_thumbnail(info)
        if thumbnail:
            metadata = f"THUMB:{thumbnail}|{metadata or 'YouTube'}"

        self.update_progress("status_downloading", 100)
        return metadata, file_path

    def _download_sync(self, url: str, mode: str, format_id: Optional[str]) -> Tuple[Path, Dict]:
        """Blocking download helper - same logic as bot/bot.py."""
        opts = self._build_options(mode, format_id)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Get filepath same way as bot/bot.py
            if "requested_downloads" in info:
                file_path = Path(info["requested_downloads"][0]["filepath"])
            else:
                file_path = Path(ydl.prepare_filename(info))
            
            # For audio, change extension to mp3
            if mode == "audio":
                file_path = file_path.with_suffix(".mp3")
            
            if not file_path.exists():
                raise DownloadError("Downloaded file not found")
            
            return file_path, info

    def _build_options(self, mode: str, format_id: Optional[str]) -> Dict:
        """Build yt-dlp options - same as working bot/bot.py."""
        outtmpl = str(self.download_dir / "%(title).200s.%(ext)s")
        
        # Base options matching bot/bot.py
        opts: Dict = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        if mode == "audio":
            if not self._ffmpeg_ready():
                raise DownloadError("FFmpeg is required for MP3 conversion")
            opts.update({
                "format": self.AUDIO_FORMAT,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            # Same format as bot/bot.py
            opts.update({
                "format": self.VIDEO_FORMAT,
                "merge_output_format": "mp4",
            })

        return opts

    @staticmethod
    def _extract_thumbnail(info: Optional[Dict]) -> Optional[str]:
        if not info:
            return None
        if info.get("thumbnail"):
            return info["thumbnail"]
        thumbs = info.get("thumbnails") or []
        if thumbs:
            sorted_thumbs = sorted(thumbs, key=lambda t: t.get("height", 0), reverse=True)
            return sorted_thumbs[0].get("url")
        return None

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        parsed = urlparse(url)
        if "v=" in parsed.query:
            return parse_qs(parsed.query).get("v", [None])[0]
        parts = parsed.path.rstrip("/").split("/")
        if parts:
            return parts[-1]
        return None

    @staticmethod
    def _ffmpeg_ready() -> bool:
        return shutil.which("ffmpeg") is not None
