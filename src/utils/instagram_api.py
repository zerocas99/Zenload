"""
Alternative Instagram download services
Fallback when Cobalt fails and before yt-dlp

Updated January 2025 - Added new working methods:
- RapidAPI scrapers (when key provided)
- Instaloader no-login grabber with proxy rotation
- SaveIG-style services (best-effort) with better error handling
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import random
import requests
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

try:
    from instaloader import Instaloader, Post  # type: ignore
    INSTALOADER_AVAILABLE = True
except Exception:  # noqa: BLE001
    INSTALOADER_AVAILABLE = False

from .proxy_provider import proxy_provider

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
    """Alternative Instagram download services - Updated Dec 2024"""
    
    # Updated services list - prioritized by reliability
    SERVICES = [
        # New working services (Dec 2024)
        ("rapidsave", "https://rapidsave.com/api/ajaxSearch"),
        ("snapsave", "https://snapsave.app/api/ajaxSearch"),
        ("inflact", "https://inflact.com/api/public/post"),
        # Existing services (may work intermittently)
        ("igram", "https://igram.world/api/convert"),
        ("saveig", "https://v3.saveig.app/api/ajaxSearch"),
        ("snapinsta", "https://snapinsta.app/api/ajaxSearch"),
        ("fastdl", "https://fastdl.app/api/ajaxSearch"),
        ("sssinstagram", "https://sssinstagram.com/api/ajaxSearch"),
    ]
    
    # RapidAPI key for premium Instagram scrapers (optional)
    RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        ]
        self._allow_public_proxy = os.getenv("INSTAGRAM_USE_PUBLIC_PROXIES", "1") not in ("0", "false", "False")
    
    def _get_user_agent(self) -> str:
        return random.choice(self._user_agents)

    def _get_proxy(self) -> Optional[Dict[str, str]]:
        if not self._allow_public_proxy:
            return None
        return proxy_provider.get_proxy()

    def _request_with_fallbacks(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        data=None,
        json_data=None,
        timeout: int = 20,
    ) -> Optional[requests.Response]:
        """Make a request with a proxy fallback."""
        attempts = []
        proxy = self._get_proxy()
        if proxy:
            attempts.append(proxy)
        attempts.append(None)  # direct attempt

        for prox in attempts:
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    json=json_data,
                    timeout=timeout,
                    proxies=prox,
                )
                if resp.status_code in (200, 400, 404, 429):
                    return resp
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[Instagram] request failed ({url}) with proxy {prox}: {e}")
                continue
        return None
    
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

    async def _try_instaloader(self, url: str) -> InstagramResult:
        """Try instaloader without login (better for /p/ posts)."""
        if not INSTALOADER_AVAILABLE:
            return InstagramResult(success=False, error="instaloader not installed")

        shortcode = self._extract_shortcode(url)
        if not shortcode:
            return InstagramResult(success=False, error="Invalid URL")

        try:
            proxy = self._get_proxy()

            def load():
                loader = Instaloader(
                    download_video_thumbnails=False,
                    download_comments=False,
                    save_metadata=False,
                    quiet=True,
                )
                if proxy:
                    loader.context._session.proxies = proxy
                post = Post.from_shortcode(loader.context, shortcode)
                if post.is_video:
                    return InstagramResult(success=True, video_url=post.video_url, is_video=True)
                else:
                    return InstagramResult(success=True, image_urls=[post.url], is_video=False)

            return await asyncio.to_thread(load)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[instaloader] Error: {e}")
            return InstagramResult(success=False, error=str(e))

    async def _try_rapidapi(self, url: str) -> InstagramResult:
        """Try RapidAPI-backed scrapers when key provided."""
        api_key = os.getenv("RAPIDAPI_INSTAGRAM_KEY") or self.RAPIDAPI_KEY
        if not api_key:
            return InstagramResult(success=False, error="No RapidAPI key")

        endpoints = [
            (
                os.getenv(
                    "RAPIDAPI_INSTAGRAM_HOST",
                    "instagram-downloader-download-instagram-videos-stories1.p.rapidapi.com",
                ),
                "/index",
            ),
            (
                os.getenv(
                    "RAPIDAPI_INSTAGRAM_HOST_ALT",
                    "instagram-downloader-download-instagram-stories-videos4.p.rapidapi.com",
                ),
                "/index",
            ),
            (
                os.getenv("RAPIDAPI_INSTAGRAM_REELS_HOST", "instagram-reels-downloader6.p.rapidapi.com"),
                "/index",
            ),
        ]

        for host, path in endpoints:
            if not host:
                continue
            api_url = f"https://{host}{path}"
            headers = {
                "User-Agent": self._get_user_agent(),
                "X-RapidAPI-Key": api_key,
                "X-RapidAPI-Host": host,
            }
            try:
                response = await asyncio.to_thread(
                    requests.get, api_url, headers=headers, params={"url": url}, timeout=25
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[RapidAPI] {host} error: {e}")
                continue

            if response.status_code != 200:
                logger.debug(f"[RapidAPI] {host} status {response.status_code}")
                continue

            try:
                data = response.json()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[RapidAPI] {host} invalid JSON: {e}")
                continue

            # Common response shapes
            video_url = (
                data.get("download_url")
                or data.get("download_link")
                or data.get("link")
                or data.get("media")
                or (data.get("result") or {}).get("link")
            )
            if not video_url and isinstance(data.get("links"), list):
                video_url = next((item for item in data["links"] if isinstance(item, str)), None)
            if not video_url and isinstance(data.get("medias"), list):
                for media in data["medias"]:
                    if isinstance(media, dict) and media.get("url"):
                        video_url = media["url"]
                        break

            if video_url:
                logger.info(f"[Instagram API] RapidAPI success via {host}")
                return InstagramResult(success=True, video_url=video_url, is_video=True)

        return InstagramResult(success=False, error="RapidAPI hosts failed")

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
                self._request_with_fallbacks,
                "POST",
                api_url,
                headers=headers,
                json_data=payload,
                timeout=20,
            )
            
            if response and response.status_code == 200:
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
                self._request_with_fallbacks,
                "GET",
                dd_url,
                headers=headers,
                timeout=15,
            )
            
            if response and response.status_code == 200:
                html = response.text or ""
                
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
                self._request_with_fallbacks,
                "GET",
                graphql_url,
                headers=headers,
                timeout=15,
            )
            
            if response and response.status_code == 200:
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
                self._request_with_fallbacks,
                "GET",
                api_url,
                headers=headers,
                timeout=15,
            )
            
            if response and response.status_code == 200:
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
                self._request_with_fallbacks,
                "GET",
                oembed_url,
                headers=headers,
                timeout=10,
            )
            
            if response and response.status_code == 200:
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

    async def _try_instagram_post_page(self, url: str) -> InstagramResult:
        """Try to get media from Instagram post page directly"""
        try:
            shortcode = self._extract_shortcode(url)
            if not shortcode:
                return InstagramResult(success=False, error="Invalid URL")
            
            # Try to get the post page with different approaches
            post_url = f"https://www.instagram.com/p/{shortcode}/"
            
            headers = {
                'User-Agent': self._get_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = await asyncio.to_thread(
                self._request_with_fallbacks,
                "GET",
                post_url,
                headers=headers,
                timeout=15,
            )
            
            if response and response.status_code == 200:
                html = response.text or ""
                
                # Try to find video URL in page source
                video_patterns = [
                    r'"video_url":"([^"]+)"',
                    r'"contentUrl":"([^"]+)"',
                    r'property="og:video"[^>]+content="([^"]+)"',
                    r'<meta[^>]+property="og:video:secure_url"[^>]+content="([^"]+)"',
                ]
                
                for pattern in video_patterns:
                    match = re.search(pattern, html)
                    if match:
                        video_url = match.group(1)
                        video_url = video_url.replace('\\u0026', '&').replace('\\/', '/')
                        if video_url.startswith('http'):
                            return InstagramResult(success=True, video_url=video_url, is_video=True)
                
                # Try to find image URL
                image_patterns = [
                    r'"display_url":"([^"]+)"',
                    r'property="og:image"[^>]+content="([^"]+)"',
                    r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                ]
                
                for pattern in image_patterns:
                    match = re.search(pattern, html)
                    if match:
                        image_url = match.group(1)
                        image_url = image_url.replace('\\u0026', '&').replace('\\/', '/')
                        if image_url.startswith('http'):
                            return InstagramResult(success=True, image_urls=[image_url], is_video=False)
            
            return InstagramResult(success=False, error="Could not extract media from page")
            
        except Exception as e:
            logger.debug(f"[post_page] Error: {e}")
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

        # 0. Premium RapidAPI scrapers (when key present)
        logger.info("[Instagram API] Trying RapidAPI scrapers...")
        result = await self._try_rapidapi(url)
        if result.success:
            return result

        # 1. Try instaloader (no-login, with optional proxy)
        logger.info("[Instagram API] Trying instaloader...")
        result = await self._try_instaloader(url)
        if result.success:
            return result
        
        # 2. Try igram.world
        logger.info("[Instagram API] Trying igram.world...")
        result = await self._try_igram(url)
        if result.success:
            logger.info("[Instagram API] Success with igram")
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
        
        # 6. Try ddinstagram proxy (often flaky)
        logger.info("[Instagram API] Trying ddinstagram...")
        result = await self._try_ddinstagram(url)
        if result.success:
            logger.info("[Instagram API] Success with ddinstagram")
            return result
        
        # 7. Try direct post page scraping
        logger.info("[Instagram API] Trying post page scraping...")
        result = await self._try_instagram_post_page(url)
        if result.success:
            logger.info("[Instagram API] Success with post page")
            return result
        
        # 8. Try embed scraping
        logger.info("[Instagram API] Trying embed scraping...")
        result = await self._try_rapi_style(url)
        if result.success:
            logger.info("[Instagram API] Success with embed")
            return result
        
        # 9. Try oEmbed as last resort (at least get image)
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
            
            def fetch_media():
                proxies = []
                prox = self._get_proxy()
                if prox:
                    proxies.append(prox)
                proxies.append(None)
                for p in proxies:
                    try:
                        r = requests.get(media_url, headers=headers, timeout=120, stream=True, proxies=p)
                        if r.status_code == 200:
                            return r
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"[Instagram API] media download failed with proxy {p}: {e}")
                return None

            response = await asyncio.to_thread(fetch_media)
            
            if not response or response.status_code != 200:
                logger.error(
                    f"[Instagram API] Download failed: HTTP {response.status_code if response else 'no response'}"
                )
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
