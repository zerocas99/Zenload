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

    async def _try_storiesig(self, username: str, story_id: str = None) -> Optional[List[Dict]]:
        """Try storiesig.info API"""
        try:
            # First get user info
            api_url = f"https://storiesig.info/api/ig/userInfoByUsername/{username}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    headers={'User-Agent': self._user_agent},
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[StoriesIG] User info failed: {response.status}")
                        return None
                    
                    user_data = await response.json()
                    user_id = user_data.get('result', {}).get('user', {}).get('pk')
                    
                    if not user_id:
                        logger.debug("[StoriesIG] Could not get user ID")
                        return None
                
                # Get stories
                stories_url = f"https://storiesig.info/api/ig/stories/{user_id}"
                async with session.get(
                    stories_url,
                    headers={'User-Agent': self._user_agent},
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.debug(f"[StoriesIG] Stories fetch failed: {response.status}")
                        return None
                    
                    stories_data = await response.json()
                    items = stories_data.get('result', [])
                    
                    if not items:
                        logger.debug("[StoriesIG] No stories found")
                        return None
                    
                    stories = []
                    for item in items:
                        item_id = str(item.get('pk', ''))
                        
                        # If specific story_id requested, filter
                        if story_id and item_id != story_id:
                            continue
                        
                        media_type = item.get('media_type')  # 1 = photo, 2 = video
                        
                        if media_type == 2:  # Video
                            video_versions = item.get('video_versions', [])
                            if video_versions:
                                stories.append({
                                    'type': 'video',
                                    'url': video_versions[0].get('url'),
                                    'id': item_id
                                })
                        else:  # Photo
                            image_versions = item.get('image_versions2', {}).get('candidates', [])
                            if image_versions:
                                stories.append({
                                    'type': 'photo',
                                    'url': image_versions[0].get('url'),
                                    'id': item_id
                                })
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[StoriesIG] Error: {e}")
            return None

    async def _try_anonyig(self, username: str, story_id: str = None) -> Optional[List[Dict]]:
        """Try AnonyIG API as fallback"""
        try:
            api_url = f"https://anonyig.com/api/ig/story?url=https://www.instagram.com/stories/{username}/"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    headers={'User-Agent': self._user_agent},
                    timeout=aiohttp.ClientTimeout(total=STORIES_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json()
                    items = data.get('result', [])
                    
                    if not items:
                        return None
                    
                    stories = []
                    for item in items:
                        item_id = str(item.get('pk', ''))
                        
                        if story_id and item_id != story_id:
                            continue
                        
                        if item.get('video_url'):
                            stories.append({
                                'type': 'video',
                                'url': item['video_url'],
                                'id': item_id
                            })
                        elif item.get('image_url'):
                            stories.append({
                                'type': 'photo',
                                'url': item['image_url'],
                                'id': item_id
                            })
                    
                    return stories if stories else None
                    
        except Exception as e:
            logger.debug(f"[AnonyIG] Error: {e}")
            return None

    async def get_stories(self, url: str) -> Optional[List[Dict]]:
        """Get stories from Instagram URL"""
        username = self._extract_username_from_story_url(url)
        if not username:
            logger.warning(f"[Stories] Could not extract username from: {url}")
            return None
        
        story_id = self._extract_story_id(url)
        logger.info(f"[Stories] Getting stories for @{username}, story_id={story_id}")
        
        # Try StoriesIG first
        stories = await self._try_storiesig(username, story_id)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from StoriesIG")
            return stories
        
        # Try AnonyIG as fallback
        stories = await self._try_anonyig(username, story_id)
        if stories:
            logger.info(f"[Stories] Got {len(stories)} stories from AnonyIG")
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
