"""
Instagram JS API Fallback Service
Used when Cobalt fails or times out
Uses local Node.js service from Instagram-Video-Downloader-API
"""

import asyncio
import logging
import os
import aiohttp
import requests
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Configuration - Node.js service URL (from env or default to localhost)
JS_API_BASE_URL = os.getenv("JS_API_URL", "http://localhost:3000")
JS_API_TIMEOUT = 60  # seconds for API request
DOWNLOAD_TIMEOUT = 120  # seconds for downloading the actual video


class InstagramJSFallback:
    """Fallback service using Node.js Instagram API (snapsave-based)"""
    
    def __init__(self):
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def _is_instagram_url(self, url: str) -> bool:
        """Validate that URL is from Instagram"""
        return any(domain in url.lower() for domain in ['instagram.com', 'instagr.am'])
    
    def _extract_url_from_response(self, data) -> Optional[str]:
        """
        Recursively extract video/media URL from API response.
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
                url = self._extract_url_from_response(item)
                if url:
                    return url
            return None
        
        if isinstance(data, dict):
            # First check 'data' wrapper (common in API responses)
            if 'data' in data:
                url = self._extract_url_from_response(data['data'])
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
                        url = self._extract_url_from_response(val)
                        if url:
                            return url
            
            # Check all values except thumbnails
            for key, val in data.items():
                if key in ['thumbnail', 'thumb', 'preview', 'cover']:
                    continue  # Skip thumbnail fields
                if isinstance(val, (dict, list)):
                    url = self._extract_url_from_response(val)
                    if url:
                        return url
        
        return None
    
    async def get_video_url(self, url: str) -> Optional[str]:
        """
        Get direct video URL from JS API
        Returns None if failed
        """
        if not self._is_instagram_url(url):
            logger.warning(f"[JS Fallback] Invalid domain: {url}")
            return None
        
        try:
            # URL encode the instagram URL
            encoded_url = quote(url, safe='')
            api_url = f"{JS_API_BASE_URL}/igdl?url={encoded_url}"
            logger.info(f"[JS Fallback] Requesting Node.js API...")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    timeout=aiohttp.ClientTimeout(total=JS_API_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        logger.error(f"[JS Fallback] API returned status {response.status}")
                        return None
                    
                    # Try to parse as JSON
                    try:
                        data = await response.json()
                    except:
                        # If JSON parsing fails, try to get text
                        text = await response.text()
                        logger.error(f"[JS Fallback] Failed to parse JSON: {text[:200]}")
                        return None
                    
                    # Log full response for debugging
                    logger.info(f"[JS Fallback] API response: {str(data)[:500]}")
                    
                    # Extract URL from various response formats
                    video_url = self._extract_url_from_response(data)
                    
                    if video_url:
                        logger.info(f"[JS Fallback] Extracted URL: {video_url[:100]}...")
                    
                    # Validate that video_url is actually a URL string
                    if not video_url:
                        logger.error(f"[JS Fallback] No video URL in response: {str(data)[:300]}")
                        return None
                    
                    if not isinstance(video_url, str):
                        logger.error(f"[JS Fallback] video_url is not a string: {type(video_url)}")
                        return None
                    
                    if not video_url.startswith('http'):
                        logger.error(f"[JS Fallback] video_url doesn't start with http: {video_url[:100]}")
                        return None
                    
                    logger.info(f"[JS Fallback] Got valid video URL: {video_url[:100]}...")
                    return video_url
                    
        except asyncio.TimeoutError:
            logger.error(f"[JS Fallback] API timeout after {JS_API_TIMEOUT}s")
            return None
        except aiohttp.ClientConnectorError:
            logger.error("[JS Fallback] Cannot connect to Node.js service. Is it running on port 3000?")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"[JS Fallback] HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"[JS Fallback] Unexpected error: {e}")
            return None
    
    async def download(
        self, 
        url: str, 
        download_dir: Path,
        progress_callback=None
    ) -> Tuple[Optional[str], Optional[Path]]:
        """
        Download Instagram video via JS API fallback
        Returns (filename, file_path) or (None, None) if failed
        """
        logger.info(f"[JS Fallback] Starting fallback download for: {url}")
        
        if progress_callback:
            progress_callback('status_downloading', 10)
        
        # Get direct video URL from JS API
        video_url = await self.get_video_url(url)
        if not video_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 30)
        
        try:
            # Download the video file
            headers = {
                'User-Agent': self._user_agent,
                'Referer': 'https://www.instagram.com/',
            }
            
            def fetch_video():
                return requests.get(
                    video_url,
                    headers=headers,
                    timeout=DOWNLOAD_TIMEOUT,
                    stream=True
                )
            
            response = await asyncio.to_thread(fetch_video)
            
            if response.status_code != 200:
                logger.error(f"[JS Fallback] Video download failed: HTTP {response.status_code}")
                return None, None
            
            if progress_callback:
                progress_callback('status_downloading', 60)
            
            # Generate filename
            import re
            shortcode_match = re.search(r'instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
            shortcode = shortcode_match.group(1) if shortcode_match else 'video'
            filename = f"instagram_js_{shortcode}.mp4"
            file_path = download_dir / filename
            
            download_dir.mkdir(exist_ok=True)
            
            # Write file
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            if progress_callback:
                progress_callback('status_downloading', 100)
            
            # Verify file
            if file_path.exists() and file_path.stat().st_size > 1000:
                logger.info(f"[JS Fallback] Download successful: {file_path}")
                return filename, file_path
            
            logger.error("[JS Fallback] Downloaded file is too small or missing")
            return None, None
            
        except requests.Timeout:
            logger.error(f"[JS Fallback] Video download timeout after {DOWNLOAD_TIMEOUT}s")
            return None, None
        except Exception as e:
            logger.error(f"[JS Fallback] Download error: {e}")
            return None, None


# Singleton instance
instagram_js_fallback = InstagramJSFallback()
