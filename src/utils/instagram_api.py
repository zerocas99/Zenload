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
import requests
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class InstagramResult:
    success: bool
    video_url: Optional[str] = None
    image_urls: Optional[List[str]] = None
    thumbnail: Optional[str] = None
    is_video: bool = True
    error: Optional[str] = None


class InstagramAPIService:
    """Alternative Instagram download services"""
    
    # More services for better success rate
    SERVICES = [
        ("igram", "https://igram.world/api/convert"),
        ("saveig", "https://v3.saveig.app/api/ajaxSearch"),
        ("snapinsta", "https://snapinsta.app/api/ajaxSearch"),
        ("fastdl", "https://fastdl.app/api/ajaxSearch"),
        ("igdownloader", "https://igdownloader.app/api/ajaxSearch"),
        ("sssinstagram", "https://sssinstagram.com/api/ajaxSearch"),
        ("instavideosave", "https://instavideosave.net/api/ajaxSearch"),
        ("saveinsta", "https://saveinsta.io/api/ajaxSearch"),
    ]
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
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

    async def _try_igram(self, url: str) -> InstagramResult:
        """Try igram.world API"""
        try:
            api_url = "https://api.igram.world/api/convert"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Origin': 'https://igram.world',
                'Referer': 'https://igram.world/',
            }
            
            payload = {"url": url}
            
            response = await asyncio.to_thread(
                requests.post, api_url, json=payload, headers=headers, timeout=20
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                
                if items:
                    for item in items:
                        video_url = item.get('url')
                        if video_url and '.mp4' in video_url:
                            return InstagramResult(success=True, video_url=video_url, is_video=True)
                        elif video_url:
                            return InstagramResult(success=True, image_urls=[video_url], is_video=False)
            
            return InstagramResult(success=False, error="igram failed")
            
        except Exception as e:
            logger.debug(f"[igram] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def _try_ddinstagram(self, url: str) -> InstagramResult:
        """Try ddinstagram proxy (like ddg for TikTok)"""
        try:
            shortcode = self._extract_shortcode(url)
            if not shortcode:
                return InstagramResult(success=False, error="Invalid URL")
            
            # ddinstagram mirrors Instagram content
            dd_url = f"https://ddinstagram.com/p/{shortcode}/"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'text/html',
            }
            
            response = await asyncio.to_thread(
                requests.get, dd_url, headers=headers, timeout=15, allow_redirects=True
            )
            
            if response.status_code == 200:
                html = response.text
                
                # Find video URL
                video_match = re.search(r'<source[^>]+src="([^"]+\.mp4[^"]*)"', html)
                if video_match:
                    return InstagramResult(success=True, video_url=video_match.group(1), is_video=True)
                
                # Find image URL
                img_match = re.search(r'<img[^>]+class="[^"]*post[^"]*"[^>]+src="([^"]+)"', html)
                if img_match:
                    return InstagramResult(success=True, image_urls=[img_match.group(1)], is_video=False)
            
            return InstagramResult(success=False, error="ddinstagram failed")
            
        except Exception as e:
            logger.debug(f"[ddinstagram] Error: {e}")
            return InstagramResult(success=False, error=str(e))

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

    async def _try_graphql_api(self, url: str) -> InstagramResult:
        """Try Instagram GraphQL API (works for public posts)"""
        try:
            shortcode = self._extract_shortcode(url)
            if not shortcode:
                return InstagramResult(success=False, error="Invalid URL")
            
            # GraphQL query for media
            query_hash = "b3055c01b4b222b8a47dc12b090e4e64"  # Media query hash
            variables = json.dumps({"shortcode": shortcode})
            
            graphql_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={variables}"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'X-IG-App-ID': '936619743392459',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': url,
            }
            
            response = await asyncio.to_thread(
                requests.get, graphql_url, headers=headers, timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                media = data.get('data', {}).get('shortcode_media', {})
                
                if media:
                    is_video = media.get('is_video', False)
                    
                    if is_video:
                        video_url = media.get('video_url')
                        if video_url:
                            return InstagramResult(success=True, video_url=video_url, is_video=True)
                    else:
                        # It's an image or carousel
                        display_url = media.get('display_url')
                        if display_url:
                            return InstagramResult(success=True, image_urls=[display_url], is_video=False)
            
            return InstagramResult(success=False, error=f"GraphQL failed: {response.status_code}")
            
        except Exception as e:
            logger.debug(f"[GraphQL] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def _try_instagram_api_v1(self, url: str) -> InstagramResult:
        """Try Instagram API v1 endpoint"""
        try:
            shortcode = self._extract_shortcode(url)
            if not shortcode:
                return InstagramResult(success=False, error="Invalid URL")
            
            # Try media info endpoint
            api_url = f"https://www.instagram.com/api/v1/media/{shortcode}/info/"
            
            headers = {
                'User-Agent': 'Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100)',
                'Accept': '*/*',
                'Accept-Language': 'en-US',
                'X-IG-App-ID': '936619743392459',
            }
            
            response = await asyncio.to_thread(
                requests.get, api_url, headers=headers, timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                
                if items:
                    item = items[0]
                    
                    # Check for video
                    video_versions = item.get('video_versions', [])
                    if video_versions:
                        video_url = video_versions[0].get('url')
                        if video_url:
                            return InstagramResult(success=True, video_url=video_url, is_video=True)
                    
                    # Check for image
                    image_versions = item.get('image_versions2', {}).get('candidates', [])
                    if image_versions:
                        image_url = image_versions[0].get('url')
                        if image_url:
                            return InstagramResult(success=True, image_urls=[image_url], is_video=False)
            
            return InstagramResult(success=False, error=f"API v1 failed: {response.status_code}")
            
        except Exception as e:
            logger.debug(f"[API v1] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def _try_instagram_oembed(self, url: str) -> InstagramResult:
        """Try Instagram oEmbed to get thumbnail (then try to get full media)"""
        try:
            oembed_url = f"https://api.instagram.com/oembed/?url={url}"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'application/json',
            }
            
            response = await asyncio.to_thread(
                requests.get, oembed_url, headers=headers, timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                thumbnail = data.get('thumbnail_url')
                
                if thumbnail:
                    # Try to get higher resolution by modifying URL
                    # Instagram thumbnails often have size in URL
                    high_res = re.sub(r'/s\d+x\d+/', '/s1080x1080/', thumbnail)
                    return InstagramResult(success=True, image_urls=[high_res, thumbnail], is_video=False)
            
            return InstagramResult(success=False, error="oEmbed failed")
            
        except Exception as e:
            logger.debug(f"[oEmbed] Error: {e}")
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
        
        # 1. Try igram.world first (often works well)
        logger.info("[Instagram API] Trying igram.world...")
        result = await self._try_igram(url)
        if result.success:
            logger.info("[Instagram API] Success with igram")
            return result
        
        # 2. Try ddinstagram proxy
        logger.info("[Instagram API] Trying ddinstagram...")
        result = await self._try_ddinstagram(url)
        if result.success:
            logger.info("[Instagram API] Success with ddinstagram")
            return result
        
        # 3. Try GraphQL API
        logger.info("[Instagram API] Trying GraphQL API...")
        result = await self._try_graphql_api(url)
        if result.success:
            logger.info("[Instagram API] Success with GraphQL")
            return result
        
        # 4. Try Instagram API v1 (mobile API)
        logger.info("[Instagram API] Trying API v1...")
        result = await self._try_instagram_api_v1(url)
        if result.success:
            logger.info("[Instagram API] Success with API v1")
            return result
        
        # 5. Shuffle and try SaveIG-style services
        services = self.SERVICES.copy()
        random.shuffle(services)
        
        for name, api_url in services[:4]:  # Try max 4
            logger.info(f"[Instagram API] Trying {name}...")
            result = await self._try_saveig_style(name, api_url, url)
            if result.success:
                logger.info(f"[Instagram API] Success with {name}")
                return result
        
        # 6. Try embed scraping
        logger.info("[Instagram API] Trying embed scraping...")
        result = await self._try_rapi_style(url)
        if result.success:
            logger.info("[Instagram API] Success with embed")
            return result
        
        # 7. Try oEmbed as last resort (at least get image)
        logger.info("[Instagram API] Trying oEmbed...")
        result = await self._try_instagram_oembed(url)
        if result.success:
            logger.info("[Instagram API] Success with oEmbed (image only)")
            return result
        
        return InstagramResult(success=False, error="All services failed")

    async def download(self, url: str, download_dir: Path, progress_callback=None) -> Tuple[Optional[str], Optional[Path]]:
        """Download video using alternative services"""
        
        if progress_callback:
            progress_callback('status_downloading', 15)
        
        result = await self.get_video_url(url)
        
        if not result.success:
            return None, None
        
        # Get the URL to download
        media_url = result.video_url
        is_video = result.is_video
        
        if not media_url and result.image_urls:
            media_url = result.image_urls[0]
            is_video = False
        
        if not media_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 40)
        
        try:
            # Download the media
            headers = {
                'User-Agent': self._get_user_agent(),
                'Referer': 'https://www.instagram.com/',
            }
            
            response = await asyncio.to_thread(
                requests.get, 
                media_url, 
                headers=headers, 
                timeout=120,
                stream=True
            )
            
            if response.status_code != 200:
                logger.error(f"[Instagram API] Download failed: HTTP {response.status_code}")
                return None, None
            
            # Generate filename
            shortcode = self._extract_shortcode(url) or 'media'
            ext = 'mp4' if is_video else 'jpg'
            filename = f"instagram_{shortcode}.{ext}"
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
