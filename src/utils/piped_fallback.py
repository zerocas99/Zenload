"""
Piped API Fallback - использует публичные инстансы Piped для YouTube
"""

import aiohttp
import logging
import random
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Список рабочих Piped инстансов (декабрь 2025)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://pipedapi.syncpundit.io",
    "https://api-piped.mha.fi",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.rivo.lol",
    "https://pipedapi.leptons.xyz",
    "https://piped-api.lunar.icu",
    "https://ytapi.dc09.ru",
    "https://pipedapi.colinslegacy.com",
    "https://pipedapi.r4fo.com",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
]

@dataclass
class PipedResult:
    success: bool
    url: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    quality: Optional[str] = None


class PipedFallback:
    """Fallback для YouTube через Piped API"""
    
    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=30)
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Извлечь video ID из URL"""
        import re
        patterns = [
            r'(?:v=|/)([0-9A-Za-z_-]{11}).*',
            r'(?:youtu\.be/)([0-9A-Za-z_-]{11})',
            r'(?:embed/)([0-9A-Za-z_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def get_video_url(self, url: str, quality: str = "720") -> PipedResult:
        """Получить прямую ссылку на видео через Piped"""
        video_id = self._extract_video_id(url)
        if not video_id:
            return PipedResult(success=False, error="Invalid YouTube URL")
        
        # Перемешиваем инстансы для балансировки
        instances = PIPED_INSTANCES.copy()
        random.shuffle(instances)
        
        for instance in instances[:5]:  # Пробуем первые 5
            try:
                logger.info(f"[Piped] Trying instance: {instance}")
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(f"{instance}/streams/{video_id}") as resp:
                        if resp.status != 200:
                            logger.warning(f"[Piped] {instance} returned {resp.status}")
                            continue
                        
                        data = await resp.json()
                        
                        if "error" in data:
                            logger.warning(f"[Piped] {instance} error: {data['error']}")
                            continue
                        
                        title = data.get("title", "YouTube Video")
                        video_streams = data.get("videoStreams", [])
                        
                        # Ищем прогрессивный поток (видео+аудио)
                        target_height = int(quality) if quality.isdigit() else 720
                        
                        suitable = [s for s in video_streams if not s.get("videoOnly", True) and s.get("height", 0) <= target_height]
                        suitable.sort(key=lambda x: x.get("height", 0), reverse=True)
                        
                        if suitable:
                            best = suitable[0]
                            logger.info(f"[Piped] Found stream: {best.get('height')}p")
                            return PipedResult(success=True, url=best.get("url"), title=title, quality=f"{best.get('height')}p")
                        
                        # Если нет прогрессивных, берём любой
                        for stream in video_streams:
                            if stream.get("url"):
                                return PipedResult(success=True, url=stream.get("url"), title=title, quality=stream.get("quality", "unknown"))
                        
            except Exception as e:
                logger.warning(f"[Piped] {instance} error: {e}")
        
        return PipedResult(success=False, error="All Piped instances failed")

    async def get_audio_url(self, url: str) -> PipedResult:
        """Получить прямую ссылку на аудио через Piped"""
        video_id = self._extract_video_id(url)
        if not video_id:
            return PipedResult(success=False, error="Invalid YouTube URL")
        
        instances = PIPED_INSTANCES.copy()
        random.shuffle(instances)
        
        for instance in instances[:5]:
            try:
                logger.info(f"[Piped] Trying audio from: {instance}")
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(f"{instance}/streams/{video_id}") as resp:
                        if resp.status != 200:
                            continue
                        
                        data = await resp.json()
                        if "error" in data:
                            continue
                        
                        title = data.get("title", "YouTube Audio")
                        audio_streams = data.get("audioStreams", [])
                        audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
                        
                        if audio_streams:
                            best = audio_streams[0]
                            logger.info(f"[Piped] Found audio: {best.get('bitrate')}kbps")
                            return PipedResult(success=True, url=best.get("url"), title=title, quality=f"{best.get('bitrate')}kbps")
                        
            except Exception as e:
                logger.warning(f"[Piped] {instance} audio error: {e}")
        
        return PipedResult(success=False, error="All Piped instances failed for audio")


# Singleton instance
piped = PipedFallback()
