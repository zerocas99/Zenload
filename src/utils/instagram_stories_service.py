"""
Instagram Stories Download Service
Downloads public Instagram stories without login
"""

import asyncio
import logging
import aiohttp
import re
from typing import Optional, Tuple, List, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

STORIES_TIMEOUT = 30


class InstagramStoriesService:
    """Service for downloading Instagram stories from public accounts"""
    
    def __init__(self):
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def _extract_username_from_story_url(self, url: str) -> Optional[str]:
        """Extract username from Instagram story URL"""
        # Pattern: instagram.com/stories/username/story_id
        match = re.search(r'instagram\.com/stories/([^/]+)', url)
        if match:
            return match.group(1)
        return None
    
    def _extract_story_id(self, url: str) -> Optional[str]:
        """Extract story ID from URL"""
        match = re.search(r'instagram\.com/stories/[^/]+/(\d+)', url)
        if match:
            return match.group(1)
        return None

    async def _try_igram(self, url: str) -> Optional[List[Dict]]:
        """Try igram.world API"""
        try:
            api_url = "https://api.igram.world/api/convert"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    json={"url": url},
                    headers={
                        'User-Agent': self._user_agent,
                        'Content-Type': 'application/json',
                        'Origin': 'https://igram.world',
                        'Referer': 'https://igram.world/'
                    },
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[iGram] API failed: {response.status}")
                        return None
                    
                    data = await response.json()
                    items = data.get('result', [])
                    
                    if not items:
                        logger.debug("[iGram] No results")
                        return None
                    
                    stories = []
                    for item in items:
                        media_url = item.get('url')
                        if not media_url:
                            continue
                        
                        # Determine type by URL
                        is_video = '.mp4' in media_url or 'video' in media_url
                        stories.append({
                            'type': 'video' if is_video else 'photo',
                            'url': media_url
                        })
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[iGram] Error: {e}")
            return None

    async def _try_savegram(self, url: str) -> Optional[List[Dict]]:
        """Try savegram.app API"""
        try:
            api_url = "https://savegram.app/api/instagram"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    data={"url": url},
                    headers={
                        'User-Agent': self._user_agent,
                        'Origin': 'https://savegram.app',
                        'Referer': 'https://savegram.app/'
                    },
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[SaveGram] API failed: {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    # Check for media URL in response
                    media_url = data.get('url') or data.get('video') or data.get('image')
                    if media_url:
                        is_video = '.mp4' in media_url or 'video' in str(data.get('type', ''))
                        return [{
                            'type': 'video' if is_video else 'photo',
                            'url': media_url
                        }]
                    
                    return None
                    
        except Exception as e:
            logger.debug(f"[SaveGram] Error: {e}")
            return None

    async def _try_saveig(self, url: str) -> Optional[List[Dict]]:
        """Try saveig.net API"""
        try:
            api_url = "https://saveig.net/api/ajaxSearch"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    data={
                        "q": url,
                        "t": "media",
                        "lang": "en"
                    },
                    headers={
                        'User-Agent': self._user_agent,
                        'Origin': 'https://saveig.net',
                        'Referer': 'https://saveig.net/',
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[SaveIG] API failed: {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get('status') != 'ok':
                        logger.debug(f"[SaveIG] Status not ok: {data.get('status')}")
                        return None
                    
                    # Parse HTML response to extract URLs
                    html = data.get('data', '')
                    
                    # Find download URLs in HTML
                    import re
                    video_urls = re.findall(r'href="([^"]+\.mp4[^"]*)"', html)
                    image_urls = re.findall(r'href="([^"]+\.jpg[^"]*)"', html)
                    
                    stories = []
                    for vurl in video_urls:
                        stories.append({'type': 'video', 'url': vurl})
                    for iurl in image_urls:
                        if iurl not in [s['url'] for s in stories]:
                            stories.append({'type': 'photo', 'url': iurl})
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[SaveIG] Error: {e}")
            return None

    async def get_stories(self, url: str) -> Optional[List[Dict]]:
        """Get stories from Instagram URL"""
        username = self._extract_username_from_story_url(url)
        story_id = self._extract_story_id(url)
        logger.info(f"[Stories] Getting stories for @{username}, story_id={story_id}")
        
        # Try iGram first
        stories = await self._try_igram(url)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from iGram")
            return stories
        
        # Try SaveIG
        stories = await self._try_saveig(url)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from SaveIG")
            return stories
        
        # Try SaveGram
        stories = await self._try_savegram(url)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from SaveGram")
            return stories
        
        logger.warning("[Stories] All services failed")
        return None

    async def download(
        self, 
        url: str, 
        download_dir: Path,
        progress_callback=None
    ) -> Tuple[Optional[str], Optional[Path]]:
        """Download Instagram story"""
        if progress_callback:
            progress_callback('status_downloading', 10)
        
        stories = await self.get_stories(url)
        if not stories:
            return None, None
        
        # Get the first (or specific) story
        story = stories[0]
        media_url = story.get('url')
        media_type = story.get('type')
        
        if not media_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 40)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    media_url,
                    headers={'User-Agent': self._user_agent},
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status != 200:
                        logger.error(f"[Stories] Download failed: HTTP {response.status}")
                        return None, None
                    
                    if progress_callback:
                        progress_callback('status_downloading', 70)
                    
                    # Generate filename
                    import os
                    ext = 'mp4' if media_type == 'video' else 'jpg'
                    filename = f"instagram_story_{os.urandom(4).hex()}.{ext}"
                    file_path = download_dir / filename
                    
                    download_dir.mkdir(exist_ok=True)
                    
                    content = await response.read()
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    if progress_callback:
                        progress_callback('status_downloading', 100)
                    
                    if file_path.exists() and file_path.stat().st_size > 1000:
                        logger.info(f"[Stories] Download successful: {file_path}")
                        return filename, file_path
                    
                    return None, None
                    
        except Exception as e:
            logger.error(f"[Stories] Download error: {e}")
            return None, None


# Singleton instance
instagram_stories_service = InstagramStoriesService()
