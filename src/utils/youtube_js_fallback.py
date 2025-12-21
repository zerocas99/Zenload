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
    content: Optional[bytes] = None  # Контент файла (если стриминг)


class YouTubeJSFallback:
    """Fallback для YouTube через Node.js сервис с ytdl-core-enhanced"""
    
    def __init__(self):
        # URL Node.js сервиса (можно настроить через env)
        self.base_url = os.getenv("YOUTUBE_JS_SERVICE_URL", "http://localhost:3000")
        self.timeout = aiohttp.ClientTimeout(total=60)
    
    async def get_video_url(self, url: str, quality: str = "highest") -> YouTubeJSResult:
        """Получить видео через Node.js сервис (стриминг)"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                params = {"url": url, "type": "video"}
                async with session.get(f"{self.base_url}/youtube/stream", params=params) as resp:
                    if resp.status == 200:
                        # Читаем весь контент
                        content = await resp.read()
                        if len(content) > 10000:  # Минимум 10KB
                            # Получаем имя файла из заголовка
                            content_disp = resp.headers.get('Content-Disposition', '')
                            filename = None
                            if 'filename=' in content_disp:
                                filename = content_disp.split('filename=')[1].strip('"')
                            
                            return YouTubeJSResult(
                                success=True,
                                url=None,  # URL не нужен, у нас есть контент
                                title=filename,
                                container='mp4',
                                content=content  # Добавляем контент
                            )
                        else:
                            return YouTubeJSResult(
                                success=False,
                                error=f"File too small: {len(content)} bytes"
                            )
                    
                    # Ошибка
                    try:
                        data = await resp.json()
                        error = data.get("error", f"HTTP {resp.status}")
                    except:
                        error = f"HTTP {resp.status}"
                    return YouTubeJSResult(success=False, error=error)
                    
        except aiohttp.ClientError as e:
            logger.error(f"[YouTubeJS] Connection error: {e}")
            return YouTubeJSResult(success=False, error=f"Connection error: {e}")
        except Exception as e:
            logger.error(f"[YouTubeJS] Error: {e}")
            return YouTubeJSResult(success=False, error=str(e))
    
    async def get_audio_url(self, url: str) -> YouTubeJSResult:
        """Получить аудио через Node.js сервис (стриминг)"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                params = {"url": url, "type": "audio"}
                async with session.get(f"{self.base_url}/youtube/stream", params=params) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        if len(content) > 5000:  # Минимум 5KB для аудио
                            content_disp = resp.headers.get('Content-Disposition', '')
                            filename = None
                            if 'filename=' in content_disp:
                                filename = content_disp.split('filename=')[1].strip('"')
                            
                            return YouTubeJSResult(
                                success=True,
                                url=None,
                                title=filename,
                                container='m4a',
                                content=content
                            )
                        else:
                            return YouTubeJSResult(
                                success=False,
                                error=f"File too small: {len(content)} bytes"
                            )
                    
                    try:
                        data = await resp.json()
                        error = data.get("error", f"HTTP {resp.status}")
                    except:
                        error = f"HTTP {resp.status}"
                    return YouTubeJSResult(success=False, error=error)
                    
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
