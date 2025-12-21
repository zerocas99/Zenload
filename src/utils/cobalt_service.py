"""
Cobalt API Service - Universal video downloader

Supports: Instagram, TikTok, Twitter/X, YouTube, Reddit, Pinterest, 
Snapchat, Twitch, Vimeo, SoundCloud, Facebook, and more.

Configuration:
- Set COBALT_API_TOKEN in .env to use official API (Recommended)
- Without token, it tries public instances
"""

import os
import json
import asyncio
import logging
import aiohttp
import random
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Instances API
INSTANCES_API = "https://instances.cobalt.best/api/instances.json"
INSTANCES_CACHE_TTL = 3600  # 1 hour

# Official API (requires token)
OFFICIAL_API = "https://api.cobalt.tools/"
OFFICIAL_TOKEN = os.getenv("COBALT_API_TOKEN", "")

# YOUR OWN COBALT INSTANCE (highest priority!)
SELF_HOSTED_COBALT = os.getenv("COBALT_SELF_HOSTED", "https://cobalt-production-c086.up.railway.app/")

# Fallback instances - ORDERED BY YOUTUBE SUPPORT (updated 22.12.2025)
YOUTUBE_INSTANCES = [
    "https://cobalt-backend.canine.tools/",
    "https://cobalt-api.meowing.de/",
    "https://capi.3kh0.net/",
]

OTHER_INSTANCES = [
    "https://kityune.imput.net/",
    "https://blossom.imput.net/",
    "https://nachos.imput.net/",
    "https://sunny.imput.net/",
]

FALLBACK_INSTANCES = YOUTUBE_INSTANCES + OTHER_INSTANCES

COBALT_SERVICES = {
    "instagram": ["instagram.com", "instagr.am", "www.instagram.com", "m.instagram.com"],
    "tiktok": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "www.tiktok.com", "m.tiktok.com"],
    "twitter": ["twitter.com", "x.com", "t.co", "mobile.twitter.com", "mobile.x.com"],
    "youtube": ["youtube.com", "youtu.be", "music.youtube.com", "www.youtube.com", "m.youtube.com"],
    "reddit": ["reddit.com", "redd.it", "www.reddit.com", "old.reddit.com", "new.reddit.com", "v.redd.it"],
    "pinterest": ["pinterest.com", "pin.it", "pinterest.ru", "pinterest.co.uk", "pinterest.de", "pinterest.fr"],
    "snapchat": ["snapchat.com", "story.snapchat.com", "www.snapchat.com", "t.snapchat.com"],
    "twitch": ["twitch.tv", "clips.twitch.tv", "m.twitch.tv", "www.twitch.tv"],
    "vimeo": ["vimeo.com", "player.vimeo.com", "www.vimeo.com"],
    "soundcloud": ["soundcloud.com", "m.soundcloud.com", "www.soundcloud.com"],
    "facebook": ["facebook.com", "fb.watch", "fb.com", "m.facebook.com", "www.facebook.com", "web.facebook.com"],
    "bilibili": ["bilibili.com", "b23.tv", "www.bilibili.com", "m.bilibili.com", "bilibili.tv"],
    "dailymotion": ["dailymotion.com", "dai.ly", "www.dailymotion.com"],
    "rutube": ["rutube.ru", "m.rutube.ru"],
    "ok": ["ok.ru", "odnoklassniki.ru", "m.ok.ru"],
    "vk": ["vk.com", "vkvideo.ru", "m.vk.com", "vk.ru"],
    "tumblr": ["tumblr.com", "www.tumblr.com"],
    "streamable": ["streamable.com"],
    "loom": ["loom.com", "www.loom.com"],
    "bluesky": ["bsky.app", "bsky.social"],
    "newgrounds": ["newgrounds.com", "www.newgrounds.com"],
    "xiaohongshu": ["xiaohongshu.com", "xhslink.com", "www.xiaohongshu.com"],
}


@dataclass
class CobaltResult:
    success: bool
    url: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    picker: Optional[list] = None


class CobaltService:
    def __init__(self):
        self._instances: List[str] = []
        self._instances_updated: float = 0
        self._failed_instances: set = set()
    
    def _get_user_agent(self) -> str:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

    async def _fetch_instances(self) -> List[str]:
        """Fetch public instances from API using aiohttp"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    INSTANCES_API,
                    headers={"User-Agent": self._get_user_agent()},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        instances = []
                        for item in data:
                            api = item.get('api') or item.get('api_url')
                            if api and item.get('trust', 0) >= 1:
                                if not api.startswith('http'):
                                    api = f"https://{api}"
                                if not api.endswith('/'):
                                    api += '/'
                                instances.append(api)
                        if instances:
                            return instances
        except Exception as e:
            logger.debug(f"[Cobalt] Failed to fetch instances: {e}")
        return FALLBACK_INSTANCES.copy()
    
    async def _get_instances(self, url: str = None) -> List[str]:
        now = time.time()
        if not self._instances or (now - self._instances_updated) > INSTANCES_CACHE_TTL:
            fetched = await self._fetch_instances()
            self._instances = list(set(fetched + FALLBACK_INSTANCES))
            self._instances_updated = now
            self._failed_instances.clear()
        
        available = [i for i in self._instances if i not in self._failed_instances]
        if not available:
            self._failed_instances.clear()
            available = self._instances.copy()
        
        is_youtube = url and any(d in url.lower() for d in ['youtube.com', 'youtu.be', 'music.youtube.com'])
        if is_youtube:
            youtube_first = [i for i in YOUTUBE_INSTANCES if i in available]
            others = [i for i in available if i not in YOUTUBE_INSTANCES]
            random.shuffle(others)
            return youtube_first + others
        else:
            random.shuffle(available)
            return available

    async def _make_request(self, api_url: str, payload: dict, use_token: bool = False) -> Optional[dict]:
        """Make request using aiohttp instead of curl"""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self._get_user_agent(),
        }
        
        if use_token and OFFICIAL_TOKEN:
            headers["Authorization"] = f"Bearer {OFFICIAL_TOKEN}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    ssl=False
                ) as resp:
                    text = await resp.text()
                    logger.debug(f"[Cobalt] Response from {api_url}: {text[:200]}")
                    if text.strip().startswith('<'):
                        return None  # HTML/Cloudflare page
                    return json.loads(text)
        except asyncio.TimeoutError:
            logger.debug(f"[Cobalt] Timeout for {api_url}")
        except Exception as e:
            logger.debug(f"[Cobalt] Request error for {api_url}: {e}")
        return None

    async def request(self, url: str, **kwargs) -> CobaltResult:
        # Cobalt API v11 format
        payload = {
            "url": url,
            "videoQuality": kwargs.get("video_quality", "1080"),
            "audioFormat": kwargs.get("audio_format", "mp3"),
            "downloadMode": kwargs.get("download_mode", "auto"),
            # Force proxy mode to avoid tunnel issues on Railway
            "filenameStyle": "pretty",
        }
        
        # Add optional fields only if needed
        if kwargs.get("tiktok_full_audio"):
            payload["tiktokFullAudio"] = True
        if kwargs.get("twitter_gif"):
            payload["twitterGif"] = True
        
        # 1. Try SELF-HOSTED Cobalt first (most reliable!)
        if SELF_HOSTED_COBALT:
            logger.info(f"[Cobalt] Using self-hosted instance: {SELF_HOSTED_COBALT}")
            data = await self._make_request(SELF_HOSTED_COBALT, payload)
            if data:
                status = data.get("status")
                if status in ("redirect", "tunnel"):
                    logger.info("[Cobalt] Self-hosted success!")
                    return CobaltResult(success=True, url=data.get("url"), filename=data.get("filename"))
                elif status == "picker":
                    return CobaltResult(success=True, picker=data.get("picker", []))
                elif status == "error":
                    error = data.get("error", {})
                    code = error.get("code") if isinstance(error, dict) else str(error)
                    logger.warning(f"[Cobalt] Self-hosted error: {code}")
                    # Don't return error, try other instances
        
        # 2. Try Official API if token exists
        if OFFICIAL_TOKEN:
            logger.info("[Cobalt] Using official API with token")
            data = await self._make_request(OFFICIAL_API, payload, use_token=True)
            if data:
                if data.get("status") in ("redirect", "tunnel"):
                    return CobaltResult(success=True, url=data.get("url"), filename=data.get("filename"))
                elif data.get("status") == "picker":
                    return CobaltResult(success=True, picker=data.get("picker", []))
                elif data.get("status") == "error":
                    error = data.get("error", {})
                    code = error.get("code") if isinstance(error, dict) else str(error)
                    return CobaltResult(success=False, error=code)

        # 3. Try Public Instances (fallback)
        instances = await self._get_instances(url)
        
        for attempt, instance in enumerate(instances[:5]):
            logger.info(f"[Cobalt] Trying instance {attempt+1}: {instance}")
            
            data = await self._make_request(instance, payload)
            
            if data:
                status = data.get("status")
                logger.info(f"[Cobalt] Instance {instance} status: {status}")
                
                if status in ("redirect", "tunnel"):
                    logger.info(f"[Cobalt] Success from {instance}")
                    return CobaltResult(success=True, url=data.get("url"), filename=data.get("filename"))
                elif status == "picker":
                    return CobaltResult(success=True, picker=data.get("picker", []))
                elif status == "error":
                    error = data.get("error", {})
                    code = error.get("code") if isinstance(error, dict) else str(error)
                    logger.warning(f"[Cobalt] Instance error: {code}")
                    if any(x in str(code) for x in ["content", "unavailable", "private", "youtube.login"]):
                        return CobaltResult(success=False, error=code)
            else:
                logger.warning(f"[Cobalt] Instance {instance} returned no data")
            
            self._failed_instances.add(instance)
        
        return CobaltResult(success=False, error="All instances failed")

    async def download(self, url: str, download_dir: Path, progress_callback=None, **kwargs) -> Tuple[Optional[str], Optional[Path]]:
        service = self.get_service_name(url) or "video"
        
        if progress_callback:
            progress_callback('status_downloading', 10)
        
        result = await self.request(url, **kwargs)
        
        if not result.success:
            logger.warning(f"[Cobalt] Failed: {result.error}")
            return None, None
            
        if result.picker:
            result.url = result.picker[0].get("url")
            
        if not result.url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 30)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    result.url,
                    headers={"User-Agent": self._get_user_agent()},
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as resp:
                    if resp.status != 200:
                        return None, None
                    
                    content = await resp.read()
                    
                    filename = result.filename or f"{service}_{hash(url) % 100000}.mp4"
                    download_dir.mkdir(exist_ok=True)
                    file_path = download_dir / filename
                    
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    if progress_callback:
                        progress_callback('status_downloading', 100)
                    return filename, file_path
        except Exception as e:
            logger.error(f"[Cobalt] Download error: {e}")
            return None, None

    @staticmethod
    def can_handle(url: str) -> bool:
        return any(d in url.lower() for domains in COBALT_SERVICES.values() for d in domains)
    
    @staticmethod
    def get_service_name(url: str) -> Optional[str]:
        for service, domains in COBALT_SERVICES.items():
            if any(d in url.lower() for d in domains):
                return service
        return None

cobalt = CobaltService()
