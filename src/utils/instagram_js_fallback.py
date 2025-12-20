"""
Instagram JS API Fallback Service
Used when Cobalt fails or times out
Uses local Node.js service from Instagram-Video-Downloader-API
"""

import asyncio
import logging
import aiohttp
import requests
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Configuration - Node.js service must be running on this port
JS_API_BASE_URL = "http://localhost:3000"
JS_API_TIMEOUT = 60  # seconds for API request
DOWNLOAD_TIMEOUT = 120  # seconds for downloading the actual video


class InstagramJSFallback:
    """Fallback service using Node.js Instagram API (snapsave-based)"""
    
    def __init__(self):
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def _is_instagram_url(self, url: str) -> bool:
        """Validate that URL is from Instagram"""
        return any(domain in url.lower() for domain in ['instagram.com', 'instagr.am'])
    
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
                    
                    data = await response.json()
                    video_url = data.get('url')
                    
                    if not video_url:
                        logger.error("[JS Fallback] No 'url' field in response")
                        return None
                    
                    logger.info("[JS Fallback] Got video URL successfully")
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
