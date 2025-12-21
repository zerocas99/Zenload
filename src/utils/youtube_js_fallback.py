"""
YouTube JS Fallback - использует Node.js сервис с ytdl-core-enhanced
для обхода защиты YouTube "Sign in to confirm you're not a bot"
"""

import aiohttp
import logging
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class YouTubeJSResult:
    success: bool
    url: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    quality: Optional[str] = None
    container: Optional[str] = None


class YouTubeJSFallback:
    """Fallback для YouTube через Node.js сервис с ytdl-core-enhanced"""
    
    def __init__(self):
        # URL Node.js сервиса (можно настроить через env)
        self.base_url = os.getenv("YOUTUBE_JS_SERVICE_URL", "http://localhost:3000")
        self.timeout = aiohttp.ClientTimeout(total=60)
    
    async def get_video_url(self, url: str, quality: str = "highest") -> YouTubeJSResult:
        """Получить прямую ссылку на видео"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                params = {"url": url, "quality": quality}
                async with session.get(f"{self.base_url}/youtube/video", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            return YouTubeJSResult(
                                success=True,
                                url=data.get("url"),
                                title=data.get("title"),
                                quality=data.get("quality"),
                                container=data.get("container")
                            )
                    
                    # Ошибка
                    data = await resp.json() if resp.content_type == 'application/json' else {}
                    return YouTubeJSResult(
                        success=False,
                        error=data.get("error", f"HTTP {resp.status}")
                    )
        except aiohttp.ClientError as e:
            logger.error(f"[YouTubeJS] Connection error: {e}")
            return YouTubeJSResult(success=False, error=f"Connection error: {e}")
        except Exception as e:
            logger.error(f"[YouTubeJS] Error: {e}")
            return YouTubeJSResult(success=False, error=str(e))
    
    async def get_audio_url(self, url: str) -> YouTubeJSResult:
        """Получить прямую ссылку на аудио"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                params = {"url": url}
                async with session.get(f"{self.base_url}/youtube/audio", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            return YouTubeJSResult(
                                success=True,
                                url=data.get("url"),
                                title=data.get("title"),
                                container=data.get("container")
                            )
                    
                    data = await resp.json() if resp.content_type == 'application/json' else {}
                    return YouTubeJSResult(
                        success=False,
                        error=data.get("error", f"HTTP {resp.status}")
                    )
        except aiohttp.ClientError as e:
            logger.error(f"[YouTubeJS] Connection error: {e}")
            return YouTubeJSResult(success=False, error=f"Connection error: {e}")
        except Exception as e:
            logger.error(f"[YouTubeJS] Error: {e}")
            return YouTubeJSResult(success=False, error=str(e))
    
    async def get_info(self, url: str) -> Dict[str, Any]:
        """Получить информацию о видео"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                params = {"url": url}
                async with session.get(f"{self.base_url}/youtube/info", params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            logger.error(f"[YouTubeJS] Info error: {e}")
            return {"error": str(e)}
    
    async def is_available(self) -> bool:
        """Проверить доступность сервиса"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.base_url}/") as resp:
                    return resp.status == 200
        except:
            return False


# Singleton instance
youtube_js = YouTubeJSFallback()
