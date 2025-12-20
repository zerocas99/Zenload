"""
Alternative Pinterest download services
Fallback when Cobalt fails
"""

import asyncio
import json
import logging
import re
import subprocess
import random
import requests
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PinterestResult:
    success: bool
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    is_video: bool = False
    title: Optional[str] = None
    error: Optional[str] = None


class PinterestAPIService:
    """Alternative Pinterest download services"""
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        ]
    
    def _get_user_agent(self) -> str:
        return random.choice(self._user_agents)
    
    def _extract_pin_id(self, url: str) -> Optional[str]:
        """Extract pin ID from Pinterest URL"""
        patterns = [
            r'pinterest\.[a-z]+/pin/(\d+)',
            r'pin\.it/([A-Za-z0-9]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _resolve_short_url(self, url: str) -> str:
        """Resolve pin.it short URLs"""
        if 'pin.it' not in url:
            return url
        
        try:
            headers = {'User-Agent': self._get_user_agent()}
            response = await asyncio.to_thread(
                requests.head, url, headers=headers, allow_redirects=True, timeout=10
            )
            if response.url and 'pinterest' in response.url:
                return response.url
        except:
            pass
        
        return url

    async def _try_pinterest_v3_api(self, pin_id: str) -> PinterestResult:
        """Try Pinterest v3 API (widget endpoint)"""
        try:
            # Widget API endpoint - doesn't require auth
            api_url = f"https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'application/json',
                'Referer': 'https://www.pinterest.com/',
            }
            
            response = await asyncio.to_thread(
                requests.get, api_url, headers=headers, timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                pins = data.get('data', [])
                
                if pins:
                    pin = pins[0].get('pin', {})
                    
                    # Check for video
                    videos = pin.get('videos', {})
                    if videos:
                        video_list = videos.get('video_list', {})
                        # Get highest quality video
                        for quality in ['V_720P', 'V_480P', 'V_360P', 'V_HLSV4', 'V_HLSV3_MOBILE']:
                            if quality in video_list:
                                video_url = video_list[quality].get('url')
                                if video_url:
                                    logger.info(f"[Pinterest v3] Found video: {quality}")
                                    return PinterestResult(success=True, video_url=video_url, is_video=True)
                    
                    # Check for image
                    images = pin.get('images', {})
                    if images:
                        # Get highest quality image
                        for quality in ['orig', '736x', '564x', '474x', '236x']:
                            if quality in images:
                                image_url = images[quality].get('url')
                                if image_url:
                                    logger.info(f"[Pinterest v3] Found image: {quality}")
                                    return PinterestResult(success=True, image_url=image_url, is_video=False)
            
            logger.info(f"[Pinterest v3] API failed: {response.status_code}")
            return PinterestResult(success=False, error=f"v3 API failed: {response.status_code}")
            
        except Exception as e:
            logger.debug(f"[Pinterest v3] Error: {e}")
            return PinterestResult(success=False, error=str(e))

    async def _try_pinterest_resource_api(self, pin_id: str) -> PinterestResult:
        """Try Pinterest Resource API"""
        try:
            api_url = "https://www.pinterest.com/resource/PinResource/get/"
            
            options = {
                "id": pin_id,
                "field_set_key": "detailed",
            }
            
            params = {
                'source_url': f'/pin/{pin_id}/',
                'data': json.dumps({"options": options, "context": {}}),
            }
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'https://www.pinterest.com/pin/{pin_id}/',
            }
            
            response = await asyncio.to_thread(
                requests.get, api_url, params=params, headers=headers, timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                pin_data = data.get('resource_response', {}).get('data', {})
                
                if pin_data:
                    # Check for video
                    videos = pin_data.get('videos', {})
                    if videos:
                        video_list = videos.get('video_list', {})
                        for quality in ['V_720P', 'V_480P', 'V_360P']:
                            if quality in video_list:
                                video_url = video_list[quality].get('url')
                                if video_url:
                                    return PinterestResult(success=True, video_url=video_url, is_video=True)
                    
                    # Check for image
                    images = pin_data.get('images', {})
                    if images:
                        for quality in ['orig', '736x', '564x']:
                            if quality in images:
                                image_url = images[quality].get('url')
                                if image_url:
                                    return PinterestResult(success=True, image_url=image_url, is_video=False)
            
            return PinterestResult(success=False, error="Resource API failed")
            
        except Exception as e:
            logger.debug(f"[Pinterest Resource] Error: {e}")
            return PinterestResult(success=False, error=str(e))

    async def _try_direct_scrape(self, url: str) -> PinterestResult:
        """Try to scrape Pinterest page directly"""
        try:
            resolved_url = await self._resolve_short_url(url)
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            response = await asyncio.to_thread(
                requests.get, resolved_url, headers=headers, timeout=15
            )
            
            if response.status_code != 200:
                return PinterestResult(success=False, error="Request failed")
            
            html = response.text
            
            # Try to find JSON data in page
            json_patterns = [
                r'<script[^>]*id="__PWS_DATA__"[^>]*>(\{.+?\})</script>',
                r'<script[^>]*type="application/json"[^>]*>(\{.+?\})</script>',
            ]
            
            for pattern in json_patterns:
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        # Navigate through the data structure
                        props = data.get('props', {})
                        initial_data = props.get('initialReduxState', {}) or data.get('initialReduxState', {})
                        pins = initial_data.get('pins', {})
                        
                        for pin_id, pin_data in pins.items():
                            # Check for video
                            videos = pin_data.get('videos', {})
                            if videos:
                                video_list = videos.get('video_list', {})
                                for quality in ['V_720P', 'V_480P', 'V_360P']:
                                    if quality in video_list:
                                        video_url = video_list[quality].get('url')
                                        if video_url:
                                            return PinterestResult(success=True, video_url=video_url, is_video=True)
                            
                            # Check for image
                            images = pin_data.get('images', {})
                            if images:
                                for quality in ['orig', '736x', '564x']:
                                    if quality in images:
                                        image_url = images[quality].get('url')
                                        if image_url:
                                            return PinterestResult(success=True, image_url=image_url, is_video=False)
                    except json.JSONDecodeError:
                        continue
            
            # Fallback: regex patterns
            video_patterns = [
                r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
                r'"url"\s*:\s*"(https://v[^"]+\.mp4[^"]*)"',
                r'V_720P[^}]+?"url"\s*:\s*"([^"]+)"',
            ]
            
            for pattern in video_patterns:
                match = re.search(pattern, html)
                if match:
                    video_url = match.group(1).replace('\\u002F', '/').replace('\\/', '/')
                    if video_url.startswith('http'):
                        return PinterestResult(success=True, video_url=video_url, is_video=True)
            
            # Try to find image URL
            image_patterns = [
                r'"url"\s*:\s*"(https://i\.pinimg\.com/originals/[^"]+)"',
                r'"url"\s*:\s*"(https://i\.pinimg\.com/736x/[^"]+)"',
                r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            ]
            
            for pattern in image_patterns:
                match = re.search(pattern, html)
                if match:
                    image_url = match.group(1).replace('\\u002F', '/').replace('\\/', '/')
                    # Try to get original size
                    image_url = re.sub(r'/\d+x/', '/originals/', image_url)
                    return PinterestResult(success=True, image_url=image_url, is_video=False)
            
            return PinterestResult(success=False, error="No media found")
            
        except Exception as e:
            logger.debug(f"[Pinterest scrape] Error: {e}")
            return PinterestResult(success=False, error=str(e))

    async def get_media_url(self, url: str) -> PinterestResult:
        """Try all services to get media URL"""
        
        # Resolve short URL first
        resolved_url = await self._resolve_short_url(url)
        
        # Extract pin ID
        pin_id = self._extract_pin_id(resolved_url)
        
        if pin_id and pin_id.isdigit():
            # 1. Try v3 widget API (most reliable)
            logger.info("[Pinterest API] Trying v3 widget API...")
            result = await self._try_pinterest_v3_api(pin_id)
            if result.success:
                logger.info("[Pinterest API] Success with v3 API")
                return result
            
            # 2. Try Resource API
            logger.info("[Pinterest API] Trying Resource API...")
            result = await self._try_pinterest_resource_api(pin_id)
            if result.success:
                logger.info("[Pinterest API] Success with Resource API")
                return result
        
        # 3. Try direct scraping
        logger.info("[Pinterest API] Trying direct scrape...")
        result = await self._try_direct_scrape(resolved_url)
        if result.success:
            logger.info("[Pinterest API] Success with direct scrape")
            return result
        
        return PinterestResult(success=False, error="All services failed")

    async def download(self, url: str, download_dir: Path, progress_callback=None) -> Tuple[Optional[str], Optional[Path]]:
        """Download media using alternative services"""
        
        if progress_callback:
            progress_callback('status_downloading', 15)
        
        result = await self.get_media_url(url)
        
        if not result.success:
            return None, None
        
        media_url = result.video_url or result.image_url
        if not media_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 40)
        
        try:
            headers = {
                'User-Agent': self._get_user_agent(),
                'Referer': 'https://www.pinterest.com/',
            }
            
            response = await asyncio.to_thread(
                requests.get, 
                media_url, 
                headers=headers, 
                timeout=120,
                stream=True
            )
            
            if response.status_code != 200:
                logger.error(f"[Pinterest API] Download failed: HTTP {response.status_code}")
                return None, None
            
            # Resolve URL to get pin ID
            resolved_url = await self._resolve_short_url(url)
            pin_id = self._extract_pin_id(resolved_url) or 'pin'
            ext = 'mp4' if result.is_video else 'jpg'
            filename = f"pinterest_{pin_id}.{ext}"
            file_path = download_dir / filename
            
            download_dir.mkdir(exist_ok=True)
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            if progress_callback:
                progress_callback('status_downloading', 100)
            
            if file_path.exists() and file_path.stat().st_size > 1000:
                return filename, file_path
            
            return None, None
            
        except Exception as e:
            logger.error(f"[Pinterest API] Download error: {e}")
            return None, None


pinterest_api = PinterestAPIService()
