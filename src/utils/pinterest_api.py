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
    
    SERVICES = [
        ("pinterestdownloader", "https://pinterestdownloader.io/api/download"),
        ("pindown", "https://pindown.io/api/download"),
        ("pinterestvideodownloader", "https://pinterestvideodownloader.com/api/download"),
    ]
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            cmd = [
                'curl', '-s', '-I', '-L', url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '--max-time', '10'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=15
            )
            
            if result.returncode == 0:
                # Find final Location header
                for line in result.stdout.split('\n'):
                    if line.lower().startswith('location:'):
                        resolved = line.split(':', 1)[1].strip()
                        if 'pinterest' in resolved:
                            return resolved
        except:
            pass
        
        return url

    async def _try_direct_scrape(self, url: str) -> PinterestResult:
        """Try to scrape Pinterest page directly"""
        try:
            resolved_url = await self._resolve_short_url(url)
            
            cmd = [
                'curl', '-s', '-L', resolved_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Accept: text/html',
                '--max-time', '15'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=20
            )
            
            if result.returncode != 0 or not result.stdout:
                return PinterestResult(success=False, error="Request failed")
            
            html = result.stdout
            
            # Try to find video URL
            video_patterns = [
                r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"',
                r'"video_url"\s*:\s*"([^"]+)"',
                r'<video[^>]+src="([^"]+)"',
                r'"url"\s*:\s*"(https://v[^"]+\.mp4[^"]*)"',
            ]
            
            for pattern in video_patterns:
                match = re.search(pattern, html)
                if match:
                    video_url = match.group(1)
                    video_url = video_url.replace('\\u002F', '/').replace('\\/', '/')
                    if video_url.startswith('http'):
                        return PinterestResult(success=True, video_url=video_url, is_video=True)
            
            # Try to find image URL
            image_patterns = [
                r'"url"\s*:\s*"(https://i\.pinimg\.com/originals/[^"]+)"',
                r'"url"\s*:\s*"(https://i\.pinimg\.com/736x/[^"]+)"',
                r'<img[^>]+src="(https://i\.pinimg\.com/[^"]+)"',
            ]
            
            for pattern in image_patterns:
                match = re.search(pattern, html)
                if match:
                    image_url = match.group(1)
                    image_url = image_url.replace('\\u002F', '/').replace('\\/', '/')
                    return PinterestResult(success=True, image_url=image_url, is_video=False)
            
            return PinterestResult(success=False, error="No media found")
            
        except Exception as e:
            logger.debug(f"[Pinterest scrape] Error: {e}")
            return PinterestResult(success=False, error=str(e))

    async def _try_api_service(self, name: str, api_url: str, url: str) -> PinterestResult:
        """Try a Pinterest download API service"""
        try:
            cmd = [
                'curl', '-s', api_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Content-Type: application/json',
                '-H', 'Accept: application/json',
                '-H', f'Origin: https://{name}.io',
                '-H', f'Referer: https://{name}.io/',
                '--data', json.dumps({"url": url}),
                '--max-time', '20'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=25
            )
            
            if result.returncode != 0 or not result.stdout:
                return PinterestResult(success=False, error="Request failed")
            
            try:
                data = json.loads(result.stdout)
                
                video_url = data.get('video_url') or data.get('videoUrl') or data.get('video')
                image_url = data.get('image_url') or data.get('imageUrl') or data.get('image')
                
                if video_url:
                    return PinterestResult(success=True, video_url=video_url, is_video=True)
                elif image_url:
                    return PinterestResult(success=True, image_url=image_url, is_video=False)
                    
            except json.JSONDecodeError:
                pass
            
            return PinterestResult(success=False, error="Invalid response")
            
        except Exception as e:
            logger.debug(f"[{name}] Error: {e}")
            return PinterestResult(success=False, error=str(e))

    async def get_media_url(self, url: str) -> PinterestResult:
        """Try all services to get media URL"""
        
        # Try direct scraping first (most reliable)
        logger.info("[Pinterest API] Trying direct scrape...")
        result = await self._try_direct_scrape(url)
        if result.success:
            logger.info("[Pinterest API] Success with direct scrape")
            return result
        
        # Try API services
        services = self.SERVICES.copy()
        random.shuffle(services)
        
        for name, api_url in services[:2]:
            logger.info(f"[Pinterest API] Trying {name}...")
            result = await self._try_api_service(name, api_url, url)
            if result.success:
                logger.info(f"[Pinterest API] Success with {name}")
                return result
        
        return PinterestResult(success=False, error="All services failed")

    async def download(self, url: str, download_dir: Path, progress_callback=None) -> Tuple[Optional[str], Optional[Path]]:
        """Download media using alternative services"""
        import requests
        
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
            
            pin_id = self._extract_pin_id(url) or 'pin'
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
