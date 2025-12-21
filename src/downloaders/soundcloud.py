import logging
import re
from pathlib import Path
from typing import Tuple, Dict, List

from .base import BaseDownloader, DownloadError
from ..config import DOWNLOADS_DIR
from ..utils.soundcloud_service import SoundcloudService

logger = logging.getLogger(__name__)


class SoundcloudDownloader(BaseDownloader):
    """Downloader for SoundCloud tracks."""

    _url_pattern = re.compile(r"(soundcloud\.com|sndcdn\.com)", re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self.service = SoundcloudService.get_instance()

    def platform_id(self) -> str:
        return "soundcloud"

    def can_handle(self, url: str) -> bool:
        return bool(url and self._url_pattern.search(url))

    async def get_formats(self, url: str) -> List[Dict]:
        return [
            {
                "id": "mp3",
                "quality": "MP3 128-160 kbps",
                "ext": "mp3",
            }
        ]

    async def _get_track_info(self, url: str) -> Tuple[Dict, Path, str]:
        """Resolve URL, select stream URL, and compute target path."""
        track_meta = await self.service.resolve_track(url)
        if not track_meta or track_meta.get("kind") != "track":
            raise DownloadError("Track not found or unsupported")

        stream_url = await self.service.get_stream_url(track_meta)
        if not stream_url:
            raise DownloadError("No downloadable stream found for this track")

        ext = "mp3"
        title = track_meta.get("title") or "SoundCloud Track"
        artist = ""
        user_info = track_meta.get("user") or {}
        if isinstance(user_info, dict):
            artist = user_info.get("username") or user_info.get("full_name") or ""

        filename = f"{artist + ' - ' if artist else ''}{title}.{ext}"
        safe_name = self._prepare_filename(filename)
        file_path = DOWNLOADS_DIR / safe_name
        return track_meta, file_path, stream_url

    def _format_metadata(self, track_meta: Dict, url: str) -> str:
        """Format metadata for audio caption"""
        title = track_meta.get("title") or "Unknown"
        
        user_info = track_meta.get("user") or {}
        artist = user_info.get("username") or user_info.get("full_name") or "Unknown"
        
        # Duration
        duration_ms = track_meta.get("duration") or track_meta.get("full_duration") or 0
        minutes = int(duration_ms) // 60000
        seconds = int(duration_ms) % 60000 // 1000
        length = f"{minutes}:{seconds:02d}"
        
        # Play count
        play_count = track_meta.get("playback_count") or 0
        if play_count >= 1_000_000:
            plays = f"{play_count/1_000_000:.1f}M"
        elif play_count >= 1_000:
            plays = f"{play_count/1_000:.1f}K"
        else:
            plays = str(play_count)
        
        permalink = track_meta.get("permalink_url") or url
        
        return f"{title} | By: {artist} | Length: {length} | Plays: {plays} | <a href=\"{permalink}\">Ссылка</a>"

    def _get_hq_artwork_url(self, artwork_url: str) -> str:
        """Get high quality artwork URL (500x500)"""
        if not artwork_url:
            return None
        # SoundCloud artwork URLs have size in them like -large, -t500x500, etc.
        return artwork_url.replace('-large', '-t500x500').replace('-small', '-t500x500')

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        try:
            self.update_progress("status_downloading", 5)
            track_meta, file_path, stream_url = await self._get_track_info(url)

            # Download audio
            downloaded = 0
            total_size = 0

            session = await self.service._get_session()
            async with session.get(stream_url) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length") or 0)
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            progress = min(90, max(10, int(downloaded / total_size * 80)))
                            self.update_progress("status_downloading", progress)

            self.update_progress("status_downloading", 100)

            # Get thumbnail URL
            artwork_url = track_meta.get("artwork_url")
            thumbnail_url = self._get_hq_artwork_url(artwork_url) if artwork_url else None

            # Return metadata for caption with thumbnail
            metadata = self._format_metadata(track_meta, url)
            if thumbnail_url:
                metadata = f"THUMB:{thumbnail_url}|{metadata}"
            
            return metadata, file_path
        except Exception as e:
            logger.error(f"Error downloading from SoundCloud: {e}", exc_info=True)
            raise DownloadError(f"Download error: {
