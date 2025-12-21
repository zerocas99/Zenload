import logging
import re
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Dict, List

from .base import BaseDownloader, DownloadError
from ..config import DOWNLOADS_DIR
from ..utils.soundcloud_service import SoundcloudService

logger = logging.getLogger(__name__)


class SoundcloudDownloader(BaseDownloader):
    """Downloader powered by soundcloud-v2 library with cover art embedding."""

    _url_pattern = re.compile(r"(soundcloud\.com|sndcdn\.com)", re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self.service = SoundcloudService.get_instance()

    def platform_id(self) -> str:
        return "soundcloud"

    def can_handle(self, url: str) -> bool:
        return bool(url and self._url_pattern.search(url))

    async def get_formats(self, url: str) -> List[Dict]:
        # SoundCloud public API only exposes a single mp3-ish stream
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

    def _get_hq_artwork_url(self, artwork_url: str) -> str:
        """Get high quality artwork URL (500x500)"""
        if not artwork_url:
            return None
        # SoundCloud artwork URLs have size in them like -large, -t500x500, etc.
        # Replace with t500x500 for high quality
        return artwork_url.replace('-large', '-t500x500').replace('-small', '-t500x500')

    async def _download_artwork(self, artwork_url: str) -> Path:
        """Download artwork to temp file"""
        if not artwork_url:
            return None
        
        try:
            session = await self.service._get_session()
            hq_url = self._get_hq_artwork_url(artwork_url)
            
            async with session.get(hq_url, timeout=10) as resp:
                if resp.status == 200:
                    # Create temp file for artwork
                    temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    temp_file.write(await resp.read())
                    temp_file.close()
                    return Path(temp_file.name)
        except Exception as e:
            logger.debug(f"Failed to download artwork: {e}")
        return None

    async def _embed_metadata(self, audio_path: Path, track_meta: Dict, artwork_path: Path = None) -> bool:
        """Embed metadata and cover art into MP3 file using ffmpeg"""
        try:
            title = track_meta.get("title") or "SoundCloud Track"
            user_info = track_meta.get("user") or {}
            artist = user_info.get("username") or user_info.get("full_name") or ""
            
            # Create output path
            output_path = audio_path.with_suffix('.tmp.mp3')
            
            # Build ffmpeg command
            cmd = ['ffmpeg', '-y', '-i', str(audio_path)]
            
            # Add artwork if available
            if artwork_path and artwork_path.exists():
                cmd.extend(['-i', str(artwork_path)])
                cmd.extend(['-map', '0:a', '-map', '1:0'])
                cmd.extend(['-c:v', 'mjpeg'])
                cmd.extend(['-disposition:v', 'attached_pic'])
            
            # Add metadata
            cmd.extend(['-c:a', 'copy'])
            cmd.extend(['-metadata', f'title={title}'])
            cmd.extend(['-metadata', f'artist={artist}'])
            cmd.extend(['-metadata', 'album=SoundCloud'])
            cmd.extend(['-id3v2_version', '3'])
            cmd.append(str(output_path))
            
            # Run ffmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()
            
            if process.returncode == 0 and output_path.exists():
                # Replace original with new file
                output_path.replace(audio_path)
                logger.info(f"[SoundCloud] Embedded metadata: {title} - {artist}")
                return True
            else:
                # Clean up failed output
                if output_path.exists():
                    output_path.unlink()
                    
        except Exception as e:
            logger.debug(f"Failed to embed metadata: {e}")
        
        return False

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
                            progress = min(80, max(10, int(downloaded / total_size * 70)))
                            self.update_progress("status_downloading", progress)

            self.update_progress("status_downloading", 85)
            
            # Download artwork and embed metadata
            artwork_url = track_meta.get("artwork_url")
            artwork_path = None
            
            try:
                if artwork_url:
                    artwork_path = await self._download_artwork(artwork_url)
                
                # Embed metadata and cover art
                await self._embed_metadata(file_path, track_meta, artwork_path)
                
            finally:
                # Clean up artwork temp file
                if artwork_path and artwork_path.exists():
                    try:
                        artwork_path.unlink()
                    except:
                        pass

            self.update_progress("status_downloading", 100)

            # Return metadata for caption
            metadata = self._format_metadata(track_meta, url)
            return metadata, file_path
        except Exception as e:
            logger.error(f"Error downloading from SoundCloud: {e}", exc_info=True)
            raise DownloadError(f"Download error: {e}")
