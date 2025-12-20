"""
Instagram Stories Download Service
Downloads public Instagram stories without login
Uses multiple fallback services including JS API
"""

import asyncio
import logging
import aiohttp
import re
import os
from typing import Optional, Tuple, List, Dict
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

STORIES_TIMEOUT = 30

# JS API URL (same as instagram_js_fallback uses)
JS_API_BASE_URL = os.getenv("JS_API_URL", "http://localhost:3000")


class InstagramStoriesService:
    """Service for downloading Instagram stories from public accounts"""
    
    def __init__(self):
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def _extract_username_from_story_url(self, url: str) -> Optional[str]:
        """Extract username from Instagram story URL"""
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
    
    def _extract_url_from_data(self, data) -> Optional[str]:
        """Recursively extract URL from nested response"""
        if isinstance(data, str):
            if data.startswith('http'):
                return data
            return None
        
        if isinstance(data, list):
            for item in data:
                url = self._extract_url_from_data(item)
                if url:
                    return url
            return None
        
        if isinstance(data, dict):
            # Priority keys
            for key in ['url', 'video', 'video_url', 'download_url', 'media_url', 'src']:
                if key in data:
                    val = data[key]
                    if isinstance(val, str) and val.startswith('http'):
                        return val
                    elif isinstance(val, (dict, list)):
                        url = self._extract_url_from_data(val)
                        if url:
                            return url
            
            # Check 'data' wrapper
            if 'data' in data:
                url = self._extract_url_from_data(data['data'])
                if url:
                    return url
            
            # Check all values
            for key, val in data.items():
                if key in ['thumbnail', 'thumb', 'preview']:
                    continue
                if isinstance(val, (dict, list)):
                    url = self._extract_url_from_data(val)
                    if url:
                        return url
        
        return None

    async def _try_js_api(self, url: str) -> Optional[List[Dict]]:
        """Try local Node.js API (snapsave-based) - most reliable"""
        try:
            encoded_url = quote(url, safe='')
            api_url = f"{JS_API_BASE_URL}/igdl?url={encoded_url}"
            logger.info(f"[Stories JS API] Requesting...")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[Stories JS API] Failed: {response.status}")
                        return None
                    
                    try:
                        data = await response.json()
                    except:
                        logger.debug("[Stories JS API] Failed to parse JSON")
                        return None
                    
                    logger.info(f"[Stories JS API] Response: {str(data)[:500]}")
                    
                    # Extract URL using recursive helper
                    media_url = self._extract_url_from_data(data)
                    
                    if media_url:
                        is_video = '.mp4' in media_url.lower() or 'video' in media_url.lower()
                        logger.info(f"[Stories JS API] Found URL: {media_url[:100]}...")
                        return [{
                            'type': 'video' if is_video else 'photo',
                            'url': media_url
                        }]
                    
                    logger.debug("[Stories JS API] No URL found in response")
                    return None
                    
        except aiohttp.ClientConnectorError:
            logger.debug("[Stories JS API] Cannot connect to Node.js service")
            return None
        except Exception as e:
            logger.debug(f"[Stories JS API] Error: {e}")
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
                    
                    # Check for media array
                    media = data.get('media') or data.get('items') or []
                    if not media and data.get('url'):
                        media = [{'url': data['url'], 'type': data.get('type', 'video')}]
                    
                    stories = []
                    for item in media:
                        if isinstance(item, dict) and item.get('url'):
                            stories.append({
                                'type': item.get('type', 'video'),
                                'url': item['url']
                            })
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[iGram] Error: {e}")
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

    async def _try_savegram(self, url: str) -> Optional[List[Dict]]:
        """Try savegram.app API"""
        try:
            api_url = "https://savegram.app/api/instagram"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    json={"url": url},
                    headers={
                        'User-Agent': self._user_agent,
                        'Content-Type': 'application/json',
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

    async def get_stories(self, url: str) -> Optional[List[Dict]]:
        """Get stories from Instagram URL"""
        username = self._extract_username_from_story_url(url)
        story_id = self._extract_story_id(url)
        logger.info(f"[Stories] Getting stories for @{username}, story_id={story_id}")
        
        # Try JS API first (most reliable - uses snapsave)
        stories = await self._try_js_api(url)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from JS API")
            return stories
        
        # Try iGram
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
