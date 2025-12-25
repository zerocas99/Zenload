import asyncio
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import yt_dlp

from ..config import DOWNLOADS_DIR, YOUTUBE_MAX_UPLOAD_MB
from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)


class YouTubeDownloader(BaseDownloader):
    """YouTube downloader that mirrors the lightweight bot in /bot."""

    VIDEO_FORMAT = "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best"
    AUDIO_FORMAT = "bestaudio/best"

    def __init__(self):
        super().__init__()
        self.download_dir = DOWNLOADS_DIR
        self.max_upload_mb = min(YOUTUBE_MAX_UPLOAD_MB, 2000)

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
        """Blocking download helper used inside a thread."""
        opts = self._build_options(mode, format_id)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = self._resolve_filepath(info, mode)
            return file_path, info

    def _build_options(self, mode: str, format_id: Optional[str]) -> Dict:
        """Build yt-dlp options based on requested mode and selected quality."""
        outtmpl = str(self.download_dir / "%(title).200s.%(ext)s")
        opts: Dict = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "concurrent_fragment_downloads": 4,
            "retries": 2,
            "fragment_retries": 2,
            "socket_timeout": 20,
        }

        if mode == "audio":
            if not self._ffmpeg_ready():
                raise DownloadError("FFmpeg is required for MP3 conversion")
            opts.update(
                {
                    "format": self.AUDIO_FORMAT,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
        else:
            video_format = self._video_format_for_quality(format_id)
            opts.update(
                {
                    "format": video_format,
                    "merge_output_format": "mp4",
                }
            )

        return opts

    def _video_format_for_quality(self, quality: Optional[str]) -> str:
        """Map requested quality to yt-dlp format selector."""
        try:
            q_int = int(quality) if quality else None
        except Exception:
            q_int = None

        if q_int and q_int >= 1080:
            return "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]/best[ext=mp4]/best"
        if q_int and q_int >= 720:
            return "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best"
        if q_int and q_int >= 480:
            return "bv*[ext=mp4][height<=480]+ba[ext=m4a]/b[ext=mp4][height<=480]/best[ext=mp4]/best"
        return self.VIDEO_FORMAT

    def _resolve_filepath(self, info: Dict, mode: str) -> Path:
        """Figure out the final file path produced by yt-dlp."""
        file_path: Optional[Path] = None

        if info.get("requested_downloads"):
            req = info["requested_downloads"][0]
            path_str = req.get("filepath") or req.get("_filename")
            if path_str:
                file_path = Path(path_str)

        if not file_path and info.get("_filename"):
            file_path = Path(info["_filename"])

        if not file_path:
            video_id = info.get("id", "video")
            for candidate in self.download_dir.glob(f"{video_id}.*"):
                file_path = candidate
                break

        if file_path and mode == "audio" and file_path.suffix.lower() != ".mp3":
            mp3_candidate = file_path.with_suffix(".mp3")
            if mp3_candidate.exists():
                file_path = mp3_candidate

        if file_path and file_path.exists():
            return file_path.resolve()

        raise DownloadError("Downloaded file not found on disk")

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
