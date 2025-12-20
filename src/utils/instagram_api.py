"""
Alternative Instagram download services
Fallback when Cobalt fails and before yt-dlp
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
class InstagramResult:
    success: bool
    video_url: Optional[str] = None
    thumbnail: Optional[str] = None
    error: Optional[str] = None


class InstagramAPIService:
    """Alternative Instagram download services"""
    
    SERVICES = [
        ("saveig", "https://v3.saveig.app/api/ajaxSearch"),
        ("snapinsta", "https://snapinsta.app/api/ajaxSearch"),
        ("fastdl", "https://fastdl.app/api/ajaxSearch"),
        ("igdownloader", "https://igdownloader.app/api/ajaxSearch"),
    ]
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    
    def _get_user_agent(self) -> str:
        return random.choice(self._user_agents)
    
    def _extract_shortcode(self, url: str) -> Optional[str]:
        patterns = [
            r'instagram\.com/p/([A-Za-z0-9_-]+)',
            r'instagram\.com/reel/([A-Za-z0-9_-]+)',
            r'instagram\.com/reels/([A-Za-z0-9_-]+)',
            r'instagram\.com/tv/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _try_saveig_style(self, name: str, api_url: str, url: str) -> InstagramResult:
        """Try SaveIG-style API (used by multiple services)"""
        try:
            # These services use form data
            cmd = [
                'curl', '-s', api_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Content-Type: application/x-www-form-urlencoded',
                '-H', 'Accept: */*',
                '-H', f'Origin: https://{name}.app',
                '-H', f'Referer: https://{name}.app/',
                '--data-urlencode', f'q={url}',
                '--data-urlencode', 't=media',
                '--data-urlencode', 'lang=en',
                '--max-time', '20'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=25
            )
            
            if result.returncode != 0 or not result.stdout:
                return InstagramResult(success=False, error="Request failed")
            
            data = json.loads(result.stdout)
            
            # Parse response - these services return HTML in 'data' field
            if data.get('status') == 'ok' and data.get('data'):
                html = data['data']
                # Extract video URL from HTML
                video_match = re.search(r'href="(https://[^"]+\.mp4[^"]*)"', html)
                if not video_match:
                    video_match = re.search(r'href="(https://[^"]+download[^"]*)"', html)
                
                if video_match:
                    video_url = video_match.group(1)
                    # Clean URL
                    video_url = video_url.replace('&amp;', '&')
                    return InstagramResult(success=True, video_url=video_url)
            
            return InstagramResult(success=False, error="No video found in response")
            
        except json.JSONDecodeError:
            return InstagramResult(success=False, error="Invalid JSON response")
        except Exception as e:
            logger.debug(f"[{name}] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def _try_rapi_style(self, url: str) -> InstagramResult:
        """Try direct scraping approach"""
        try:
            shortcode = self._extract_shortcode(url)
            if not shortcode:
                return InstagramResult(success=False, error="Invalid URL")
            
            # Try to get embed page
            embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
            
            cmd = [
                'curl', '-s', '-L', embed_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Accept: text/html',
                '--max-time', '15'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=20
            )
            
            if result.returncode != 0 or not result.stdout:
                return InstagramResult(success=False, error="Embed request failed")
            
            html = result.stdout
            
            # Try to find video URL in embed page
            video_patterns = [
                r'"video_url":"([^"]+)"',
                r'video_url\\?":\\?"([^"\\]+)',
                r'"contentUrl":"([^"]+\.mp4[^"]*)"',
            ]
            
            for pattern in video_patterns:
                match = re.search(pattern, html)
                if match:
                    video_url = match.group(1)
                    video_url = video_url.replace('\\u0026', '&').replace('\\/', '/')
                    return InstagramResult(success=True, video_url=video_url)
            
            return InstagramResult(success=False, error="No video in embed")
            
        except Exception as e:
            logger.debug(f"[embed] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def get_video_url(self, url: str) -> InstagramResult:
        """Try all services to get video URL"""
        
        # Shuffle services for load balancing
        services = self.SERVICES.copy()
        random.shuffle(services)
        
        # Try SaveIG-style services
        for name, api_url in services[:3]:  # Try max 3
            logger.info(f"[Instagram API] Trying {name}...")
            result = await self._try_saveig_style(name, api_url, url)
            if result.success:
                logger.info(f"[Instagram API] Success with {name}")
                return result
        
        # Try embed scraping as last resort
        logger.info("[Instagram API] Trying embed scraping...")
        result = await self._try_rapi_style(url)
        if result.success:
            logger.info("[Instagram API] Success with embed")
            return result
        
        return InstagramResult(success=False, error="All services failed")

    async def download(self, url: str, download_dir: Path, progress_callback=None) -> Tuple[Optional[str], Optional[Path]]:
        """Download video using alternative services"""
        import requests
        
        if progress_callback:
            progress_callback('status_downloading', 15)
        
        result = await self.get_video_url(url)
        
        if not result.success or not result.video_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 40)
        
        try:
            # Download the video
            headers = {
                'User-Agent': self._get_user_agent(),
                'Referer': 'https://www.instagram.com/',
            }
            
            response = await asyncio.to_thread(
                requests.get, 
                result.video_url, 
                headers=headers, 
                timeout=120,
                stream=True
            )
            
            if response.status_code != 200:
                logger.error(f"[Instagram API] Download failed: HTTP {response.status_code}")
                return None, None
            
            # Generate filename
            shortcode = self._extract_shortcode(url) or 'video'
            filename = f"instagram_{shortcode}.mp4"
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
            logger.error(f"[Instagram API] Download error: {e}")
            return None, None


instagram_api = InstagramAPIService()
