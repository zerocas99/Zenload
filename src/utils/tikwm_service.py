"""
TikWm API Service for TikTok downloads
Fast and reliable API for downloading TikTok videos without watermark
"""

import asyncio
import logging
import aiohttp
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

TIKWM_API_URL = "https://www.tikwm.com/api/"
TIKWM_TIMEOUT = 30


class TikWmService:
    """TikWm API service for TikTok downloads"""
    
    def __init__(self):
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    async def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get video info from TikWm API
        Returns dict with video_url, music_url, cover, author, etc.
        """
        try:
            api_url = f"{TIKWM_API_URL}?url={quote(url, safe='')}&hd=1"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    headers={'User-Agent': self._user_agent},
                    timeout=aiohttp.ClientTimeout(total=TIKWM_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.error(f"[TikWm] API returned status {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get('code') != 0:
                        logger.error(f"[TikWm] API error: {data.get('msg')}")
                        return None
                    
                    video_data = data.get('data', {})
                    if not video_data:
                        logger.error("[TikWm] No data in response")
                        return None
                    
                    return {
                        'video_url': video_data.get('hdplay') or video_data.get('play'),
                        'music_url': video_data.get('music'),
                        'cover': video_data.get('cover'),
                        'author': video_data.get('author', {}).get('nickname', ''),
                        'author_id': video_data.get('author', {}).get('unique_id', ''),
                        'title': video_data.get('title', ''),
                        'play_count': video_data.get('play_count', 0),
                        'like_count': video_data.get('digg_count', 0),
                        'comment_count': video_data.get('comment_count', 0),
                        'duration': video_data.get('duration', 0),
                        'is_images': video_data.get('images') is not None,
                        'images': video_data.get('images', []),
                    }
                    
        except asyncio.TimeoutError:
            logger.error(f"[TikWm] API timeout after {TIKWM_TIMEOUT}s")
            return None
        except Exception as e:
            logger.error(f"[TikWm] Error: {e}")
            return None
    
    async def get_direct_url(self, url: str) -> Tuple[Optional[str], Optional[str], bool, Optional[str], bool, Optional[list]]:
        """
        Get direct video/image URL for fast sending
        Returns: (direct_url, metadata, is_audio, audio_url, is_photo, all_images)
        """
        info = await self.get_video_info(url)
        if not info:
            return None, None, False, None, False, None
        
        # Format metadata
        def format_number(num):
            if not num:
                return "0"
            if num >= 1000000:
                return f"{num/1000000:.1f}M"
            if num >= 1000:
                return f"{num/1000:.1f}K"
            return str(num)
        
        plays = format_number(info.get('play_count', 0))
        likes = format_number(info.get('like_count', 0))
        author = info.get('author', '') or info.get('author_id', '')
        
        metadata = f"TikTok | {plays} ▶️ | {likes} ❤️\nby @{author}"
        
        # Check if it's a photo slideshow
        if info.get('is_images') and info.get('images'):
            images = info['images']
            if images and len(images) > 0:
                logger.info(f"[TikWm] Photo slideshow detected, {len(images)} images")
                # Return first image as direct_url, but also return all images
                # Include audio_url for slideshows too!
                audio_url = info.get('music_url')
                return images[0], metadata, False, audio_url, True, images
        
        # Regular video
        if not info.get('video_url'):
            return None, None, False, None, False, None
        
        audio_url = info.get('music_url')
        return info['video_url'], metadata, False, audio_url, False, None
    
    async def download(
        self, 
        url: str, 
        download_dir: Path,
        progress_callback=None
    ) -> Tuple[Optional[str], Optional[Path], Optional[str]]:
        """
        Download TikTok video via TikWm API
        Returns: (filename, file_path, metadata)
        """
        logger.info(f"[TikWm] Starting download for: {url}")
        
        if progress_callback:
            await progress_callback('status_downloading', 10)
        
        info = await self.get_video_info(url)
        if not info:
            return None, None, None
        
        # Check if it's images (slideshow)
        if info.get('is_images') and info.get('images'):
            logger.info("[TikWm] This is an image slideshow, not supported yet")
            return None, None, None
        
        video_url = info.get('video_url')
        if not video_url:
            logger.error("[TikWm] No video URL in response")
            return None, None, None
        
        if progress_callback:
            await progress_callback('status_downloading', 30)
        
        try:
            # Download video
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    video_url,
                    headers={
                        'User-Agent': self._user_agent,
                        'Referer': 'https://www.tiktok.com/',
                    },
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status != 200:
                        logger.error(f"[TikWm] Video download failed: HTTP {response.status}")
                        return None, None, None
                    
                    if progress_callback:
                        await progress_callback('status_downloading', 50)
                    
                    # Generate filename
                    import os
                    filename = f"tiktok_tikwm_{os.urandom(4).hex()}.mp4"
                    file_path = download_dir / filename
                    
                    download_dir.mkdir(exist_ok=True)
                    
                    # Write file
                    content = await response.read()
                    with open(file_path, 'wb') as f:
                        f.write(content)
                    
                    if progress_callback:
                        await progress_callback('status_downloading', 90)
                    
                    # Verify file
                    if file_path.exists() and file_path.stat().st_size > 1000:
                        # Format metadata
                        def format_number(num):
                            if not num:
                                return "0"
                            if num >= 1000000:
                                return f"{num/1000000:.1f}M"
                            if num >= 1000:
                                return f"{num/1000:.1f}K"
                            return str(num)
                        
                        plays = format_number(info.get('play_count', 0))
                        likes = format_number(info.get('like_count', 0))
                        author = info.get('author', '') or info.get('author_id', '')
                        
                        metadata = f"TikTok | {plays} ▶️ | {likes} ❤️\nby @{author}"
                        
                        logger.info(f"[TikWm] Download successful: {file_path}")
                        return filename, file_path, metadata
                    
                    logger.error("[TikWm] Downloaded file is too small or missing")
                    return None, None, None
                    
        except Exception as e:
            logger.error(f"[TikWm] Download error: {e}")
            return None, None, None


# Singleton instance
tikwm_service = TikWmService()
