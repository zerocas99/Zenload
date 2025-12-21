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
import base64
import json
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
        """
        Recursively extract video/media URL from nested response.
        Prioritizes 'url' field over 'thumbnail' to get video not image.
        """
        if isinstance(data, str):
            if data.startswith('http'):
                return data
            return None
        
        if isinstance(data, list):
            # For list of items, extract URL from first item that has 'url' key
            for item in data:
                if isinstance(item, dict) and 'url' in item:
                    val = item['url']
                    if isinstance(val, str) and val.startswith('http'):
                        return val
            # Fallback: recurse into list items
            for item in data:
                url = self._extract_url_from_data(item)
                if url:
                    return url
            return None
        
        if isinstance(data, dict):
            # First check 'data' wrapper (common in API responses)
            if 'data' in data:
                url = self._extract_url_from_data(data['data'])
                if url:
                    return url
            
            # Priority keys for video URL (NOT thumbnail)
            video_keys = ['url', 'video', 'video_url', 'download_url', 'media_url', 'src']
            for key in video_keys:
                if key in data:
                    val = data[key]
                    if isinstance(val, str) and val.startswith('http'):
                        return val
                    elif isinstance(val, (dict, list)):
                        url = self._extract_url_from_data(val)
                        if url:
                            return url
            
            # Check all values except thumbnails
            for key, val in data.items():
                if key in ['thumbnail', 'thumb', 'preview', 'cover']:
                    continue  # Skip thumbnail fields
                if isinstance(val, (dict, list)):
                    url = self._extract_url_from_data(val)
                    if url:
                        return url
        
        return None

    async def _try_js_api(self, url: str, story_id: str = None) -> Optional[List[Dict]]:
        """Try local Node.js API (snapsave-based) - most reliable"""
        try:
            encoded_url = quote(url, safe='')
            api_url = f"{JS_API_BASE_URL}/igdl?url={encoded_url}"
            logger.info(f"[Stories JS API] Requesting... (story_id={story_id})")
            
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
                    
                    # Try to find all media items from response
                    all_items = self._extract_all_media_from_data(data, story_id)
                    
                    if all_items:
                        logger.info(f"[Stories JS API] Found {len(all_items)} media items")
                        return all_items
                    
                    # Fallback: extract single URL
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
    
    def _decode_jwt_url(self, token_url: str) -> Optional[str]:
        """Try to decode JWT token from rapidcdn URL to get original Instagram URL"""
        try:
            # Extract token from URL like https://d.rapidcdn.app/v2?token=...
            if 'token=' not in token_url:
                return None
            
            token = token_url.split('token=')[1].split('&')[0]
            
            # JWT has 3 parts: header.payload.signature
            parts = token.split('.')
            if len(parts) < 2:
                return None
            
            # Decode payload (second part)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)
            
            # The payload should contain 'url' with original Instagram URL
            return data.get('url')
        except Exception as e:
            logger.debug(f"[Stories] JWT decode failed: {e}")
            return None
    
    def _extract_story_id_from_instagram_url(self, url: str) -> Optional[str]:
        """Extract story ID from Instagram CDN URL (ig_cache_key parameter)"""
        # Instagram URLs contain ig_cache_key which is the story ID
        # Example: ig_cache_key=Mzc5MTM4NDQzMDI1MDc0MDcyMQ%3D%3D
        match = re.search(r'ig_cache_key=([A-Za-z0-9%=]+)', url)
        if match:
            try:
                encoded = match.group(1)
                # URL decode
                from urllib.parse import unquote
                encoded = unquote(encoded)
                # Base64 decode
                decoded = base64.b64decode(encoded).decode('utf-8')
                return decoded
            except:
                pass
        return None

    def _extract_all_media_from_data(self, data, story_id: str = None) -> Optional[List[Dict]]:
        """Extract all media items from API response, optionally filtering by story_id"""
        items = []
        
        # Navigate to data array
        if isinstance(data, dict):
            if 'url' in data and isinstance(data['url'], dict):
                data = data['url']
            if 'data' in data and isinstance(data['data'], list):
                data = data['data']
        
        if not isinstance(data, list):
            return None
        
        logger.info(f"[Stories] Processing {len(data)} items, looking for story_id={story_id}")
        
        # First pass: collect all items with their decoded URLs
        all_items_data = []
        for idx, item in enumerate(data):
            if isinstance(item, dict) and 'url' in item:
                url = item['url']
                thumb = item.get('thumbnail', '')
                
                if isinstance(url, str) and url.startswith('http'):
                    # Decode main URL to get original Instagram URL
                    original_url = self._decode_jwt_url(url)
                    thumb_original = self._decode_jwt_url(thumb) if thumb else None
                    
                    # Extract story IDs from both URLs
                    url_story_id = None
                    thumb_story_id = None
                    
                    if original_url:
                        url_story_id = self._extract_story_id_from_instagram_url(original_url)
                    if thumb_original:
                        thumb_story_id = self._extract_story_id_from_instagram_url(thumb_original)
                    
                    all_items_data.append({
                        'idx': idx,
                        'url': url,
                        'original_url': original_url,
                        'thumb': thumb,
                        'thumb_original': thumb_original,
                        'url_story_id': url_story_id,
                        'thumb_story_id': thumb_story_id
                    })
                    
                    # Log for debugging
                    if story_id:
                        logger.info(f"[Stories] Item {idx}: url_story_id={url_story_id}, thumb_story_id={thumb_story_id}")
        
        # Second pass: find matching story by ID
        if story_id:
            # Priority 1: Match by main URL story ID (most reliable)
            for item_data in all_items_data:
                if item_data['url_story_id'] == story_id:
                    logger.info(f"[Stories] Found story_id via main URL JWT at index {item_data['idx']}")
                    original_url = item_data['original_url']
                    is_video = original_url and ('.mp4' in original_url.lower() or '/video/' in original_url.lower())
                    return [{
                        'type': 'video' if is_video else 'photo',
                        'url': item_data['url'],
                        'index': item_data['idx'],
                        'matched': True
                    }]
            
            # Priority 2: Match by story_id in original URL string
            for item_data in all_items_data:
                if item_data['original_url'] and story_id in item_data['original_url']:
                    logger.info(f"[Stories] Found story_id in original URL string at index {item_data['idx']}")
                    original_url = item_data['original_url']
                    is_video = original_url and ('.mp4' in original_url.lower() or '/video/' in original_url.lower())
                    return [{
                        'type': 'video' if is_video else 'photo',
                        'url': item_data['url'],
                        'index': item_data['idx'],
                        'matched': True
                    }]
            
            # Priority 3: Match by thumbnail story ID ONLY if thumbnail and main URL have same story ID
            # This prevents the bug where thumbnail points to different story than main URL
            for item_data in all_items_data:
                if item_data['thumb_story_id'] == story_id:
                    # Verify that main URL also belongs to this story (or has no ID)
                    if item_data['url_story_id'] is None or item_data['url_story_id'] == story_id:
                        logger.info(f"[Stories] Found story_id via thumbnail JWT at index {item_data['idx']} (verified)")
                        original_url = item_data['original_url'] or item_data['thumb_original']
                        is_video = original_url and ('.mp4' in original_url.lower() or '/video/' in original_url.lower())
                        return [{
                            'type': 'video' if is_video else 'photo',
                            'url': item_data['url'],
                            'index': item_data['idx'],
                            'matched': True
                        }]
                    else:
                        logger.warning(f"[Stories] Thumbnail story_id matches but main URL has different ID: {item_data['url_story_id']}")
            
            # Priority 4: Direct string search in raw item
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    item_str = str(item)
                    if story_id in item_str:
                        url = item.get('url', '')
                        if url:
                            logger.info(f"[Stories] Found story_id in item string at index {idx}")
                            is_video = '.mp4' in url.lower() or 'video' in url.lower()
                            return [{
                                'type': 'video' if is_video else 'photo',
                                'url': url,
                                'index': idx,
                                'matched': True
                            }]
            
            logger.warning(f"[Stories] Could not find story_id {story_id} in {len(all_items_data)} items")
        
        # Build items list for return (when no specific story_id or not found)
        for item_data in all_items_data:
            original_url = item_data['original_url']
            is_video = False
            if original_url:
                is_video = '.mp4' in original_url.lower() or '/video/' in original_url.lower()
            if not is_video:
                is_video = '.mp4' in item_data['url'].lower() or 'video' in item_data['url'].lower()
            
            items.append({
                'type': 'video' if is_video else 'photo',
                'url': item_data['url'],
                'index': item_data['idx'],
                'matched': False
            })
        
        return items if items else None

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
        stories = await self._try_js_api(url, story_id)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from JS API")
            return stories
        
        # Try StoriesIG
        stories = await self._try_storiesig(username, story_id)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from StoriesIG")
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
        
        # Try Instafinsta
        stories = await self._try_instafinsta(url)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from Instafinsta")
            return stories
        
        logger.warning("[Stories] All services failed")
        return None
    
    async def _try_storiesig(self, username: str, story_id: str = None) -> Optional[List[Dict]]:
        """Try storiesig.info API"""
        if not username:
            return None
        
        try:
            api_url = f"https://storiesig.info/api/ig/story?url=https://www.instagram.com/stories/{username}/"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    headers={
                        'User-Agent': self._user_agent,
                        'Accept': 'application/json',
                    },
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[StoriesIG] API failed: {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    if not data.get('result'):
                        logger.debug("[StoriesIG] No result in response")
                        return None
                    
                    stories = []
                    for item in data.get('result', []):
                        media_url = item.get('url') or item.get('video_url') or item.get('image_url')
                        if media_url:
                            is_video = item.get('is_video', False) or '.mp4' in media_url
                            item_id = str(item.get('pk', ''))
                            
                            story_item = {
                                'type': 'video' if is_video else 'photo',
                                'url': media_url,
                                'id': item_id
                            }
                            
                            # If looking for specific story
                            if story_id and item_id == story_id:
                                logger.info(f"[StoriesIG] Found specific story by ID: {story_id}")
                                return [story_item]
                            
                            stories.append(story_item)
                    
                    # If we were looking for specific story but didn't find it
                    if story_id and stories:
                        logger.warning(f"[StoriesIG] Specific story {story_id} not found in {len(stories)} stories")
                        # Return None to try next service instead of returning wrong story
                        return None
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[StoriesIG] Error: {e}")
            return None
    
    async def _try_instafinsta(self, url: str) -> Optional[List[Dict]]:
        """Try instafinsta.com API"""
        try:
            api_url = "https://instafinsta.com/api/media"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    data={"url": url},
                    headers={
                        'User-Agent': self._user_agent,
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Origin': 'https://instafinsta.com',
                        'Referer': 'https://instafinsta.com/'
                    },
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[Instafinsta] API failed: {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    media_url = self._extract_url_from_data(data)
                    if media_url:
                        is_video = '.mp4' in media_url.lower() or 'video' in media_url.lower()
                        return [{
                            'type': 'video' if is_video else 'photo',
                            'url': media_url
                        }]
                    
                    return None
                    
        except Exception as e:
            logger.debug(f"[Instafinsta] Error: {e}")
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
                    
                    # Determine type by content-type header (more reliable than URL)
                    content_type = response.headers.get('Content-Type', '').lower()
                    logger.info(f"[Stories] Content-Type: {content_type}")
                    
                    # Check if it's video
                    is_video = 'video' in content_type or 'mp4' in content_type
                    
                    # If content-type is octet-stream, check first bytes for video signature
                    content = await response.read()
                    
                    if 'octet-stream' in content_type or not content_type:
                        # Check for MP4 signature (ftyp)
                        if len(content) > 8:
                            # MP4 files have 'ftyp' at offset 4
                            if content[4:8] == b'ftyp':
                                is_video = True
                                logger.info("[Stories] Detected MP4 by file signature")
                    
                    ext = 'mp4' if is_video else 'jpg'
                    filename = f"instagram_story_{os.urandom(4).hex()}.{ext}"
                    file_path = download_dir / filename
                    
                    download_dir.mkdir(exist_ok=True)
                    
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    if progress_callback:
                        progress_callback('status_downloading', 100)
                    
                    if file_path.exists() and file_path.stat().st_size > 1000:
                        logger.info(f"[Stories] Download successful: {file_path} (video={is_video})")
                        return filename, file_path
                    
                    return None, None
                    
        except Exception as e:
            logger.error(f"[Stories] Download error: {e}")
            return None, None


# Singleton instance
instagram_stories_service = InstagramStoriesService()
