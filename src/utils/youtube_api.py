"""
Alternative YouTube download services
Fallback when yt-dlp fails
"""

import asyncio
import json
import logging
import re
import subprocess
import random
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class YouTubeResult:
    success: bool
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    title: Optional[str] = None
    formats: Optional[List[Dict]] = None
    error: Optional[str] = None


class YouTubeAPIService:
    """Alternative YouTube download services"""
    
    def __init__(self):
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
    
    def _get_user_agent(self) -> str:
        return random.choice(self._user_agents)
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})',
            r'youtube\.com/embed/([A-Za-z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _try_y2mate(self, url: str, quality: str = "720") -> YouTubeResult:
        """Try Y2mate API"""
        try:
            video_id = self._extract_video_id(url)
            if not video_id:
                return YouTubeResult(success=False, error="Invalid URL")
            
            # Step 1: Analyze video
            analyze_url = "https://www.y2mate.com/mates/analyzeV2/ajax"
            
            cmd = [
                'curl', '-s', analyze_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Content-Type: application/x-www-form-urlencoded',
                '-H', 'Accept: application/json',
                '-H', 'Origin: https://www.y2mate.com',
                '-H', 'Referer: https://www.y2mate.com/',
                '--data-urlencode', f'k_query=https://www.youtube.com/watch?v={video_id}',
                '--data-urlencode', 'k_page=home',
                '--data-urlencode', 'hl=en',
                '--data-urlencode', 'q_auto=1',
                '--max-time', '20'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=25
            )
            
            if result.returncode != 0 or not result.stdout:
                return YouTubeResult(success=False, error="Analyze request failed")
            
            data = json.loads(result.stdout)
            
            if data.get('status') != 'ok':
                return YouTubeResult(success=False, error="Analyze failed")
            
            # Get available formats
            links = data.get('links', {})
            mp4_links = links.get('mp4', {})
            
            if not mp4_links:
                return YouTubeResult(success=False, error="No MP4 formats")
            
            # Find best quality
            best_key = None
            best_quality = 0
            
            for key, info in mp4_links.items():
                q = info.get('q', '')
                if 'p' in q:
                    try:
                        q_num = int(q.replace('p', ''))
                        if q_num <= int(quality) and q_num > best_quality:
                            best_quality = q_num
                            best_key = key
                    except:
                        pass
            
            if not best_key:
                best_key = list(mp4_links.keys())[0]
            
            # Step 2: Convert
            convert_url = "https://www.y2mate.com/mates/convertV2/index"
            k = mp4_links[best_key].get('k', '')
            
            cmd = [
                'curl', '-s', convert_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Content-Type: application/x-www-form-urlencoded',
                '-H', 'Accept: application/json',
                '-H', 'Origin: https://www.y2mate.com',
                '--data-urlencode', f'vid={video_id}',
                '--data-urlencode', f'k={k}',
                '--max-time', '30'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=35
            )
            
            if result.returncode != 0 or not result.stdout:
                return YouTubeResult(success=False, error="Convert request failed")
            
            convert_data = json.loads(result.stdout)
            
            if convert_data.get('status') == 'ok':
                download_url = convert_data.get('dlink')
                title = convert_data.get('title', video_id)
                if download_url:
                    return YouTubeResult(success=True, video_url=download_url, title=title)
            
            return YouTubeResult(success=False, error="Convert failed")
            
        except Exception as e:
            logger.debug(f"[Y2mate] Error: {e}")
            return YouTubeResult(success=False, error=str(e))

    async def _try_ssyoutube(self, url: str) -> YouTubeResult:
        """Try SSYouTube/SaveFrom style API"""
        try:
            video_id = self._extract_video_id(url)
            if not video_id:
                return YouTubeResult(success=False, error="Invalid URL")
            
            api_url = f"https://api.ssyoutube.com/api/convert"
            
            cmd = [
                'curl', '-s', api_url,
                '-H', f'User-Agent: {self._get_user_agent()}',
                '-H', 'Content-Type: application/json',
                '-H', 'Accept: application/json',
                '--data', json.dumps({"url": f"https://www.youtube.com/watch?v={video_id}"}),
                '--max-time', '20'
            ]
            
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=25
            )
            
            if result.returncode == 0 and result.stdout:
                try:
                    data = json.loads(result.stdout)
                    if data.get('url'):
                        return YouTubeResult(
                            success=True, 
                            video_url=data['url'],
                            title=data.get('title', video_id)
                        )
                except:
                    pass
            
            return YouTubeResult(success=False, error="SSYouTube failed")
            
        except Exception as e:
            logger.debug(f"[SSYouTube] Error: {e}")
            return YouTubeResult(success=False, error=str(e))

    async def get_video_url(self, url: str, quality: str = "720") -> YouTubeResult:
        """Try all services to get video URL"""
        
        # Try Y2mate
        logger.info("[YouTube API] Trying Y2mate...")
        result = await self._try_y2mate(url, quality)
        if result.success:
            logger.info("[YouTube API] Success with Y2mate")
            return result
        
        # Try SSYouTube
        logger.info("[YouTube API] Trying SSYouTube...")
        result = await self._try_ssyoutube(url)
        if result.success:
            logger.info("[YouTube API] Success with SSYouTube")
            return result
        
        return YouTubeResult(success=False, error="All services failed")

    async def download(self, url: str, download_dir: Path, quality: str = "720", progress_callback=None) -> Tuple[Optional[str], Optional[Path]]:
        """Download video using alternative services"""
        import requests
        
        if progress_callback:
            progress_callback('status_downloading', 15)
        
        result = await self.get_video_url(url, quality)
        
        if not result.success or not result.video_url:
            return None, None
        
        if progress_callback:
            progress_callback('status_downloading', 40)
        
        try:
            headers = {
                'User-Agent': self._get_user_agent(),
                'Referer': 'https://www.youtube.com/',
            }
            
            response = await asyncio.to_thread(
                requests.get, 
                result.video_url, 
                headers=headers, 
                timeout=180,
                stream=True
            )
            
            if response.status_code != 200:
                logger.error(f"[YouTube API] Download failed: HTTP {response.status_code}")
                return None, None
            
            video_id = self._extract_video_id(url) or 'video'
            filename = f"youtube_{video_id}.mp4"
            file_path = download_dir / filename
            
            download_dir.mkdir(exist_ok=True)
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress = int((downloaded / total_size) * 50) + 40
                        progress_callback('status_downloading', min(progress, 90))
            
            if progress_callback:
                progress_callback('status_downloading', 100)
            
            if file_path.exists() and file_path.stat().st_size > 10000:
                return result.title or filename, file_path
            
            return None, None
            
        except Exception as e:
            logger.error(f"[YouTube API] Download error: {e}")
            return None, None


youtube_api = YouTubeAPIService()
