"""
YouTube Download API Service
Simple HTTP API for downloading YouTube videos/audio using yt-dlp
"""

import os
import asyncio
import logging
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, send_file
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("yt-api")

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

def _ffmpeg_ok():
    return shutil.which("ffmpeg") is not None

def _download_sync(url: str, mode: str):
    """Download video/audio and return filepath"""
    outtmpl = str(DOWNLOAD_DIR / "%(title).200s.%(ext)s")
    
    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    
    if mode == "audio":
        if not _ffmpeg_ok():
            return None, None, "ffmpeg is required for MP3"
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        ydl_opts.update({
            "format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "video"
            
            if "requested_downloads" in info:
                filepath = Path(info["requested_downloads"][0]["filepath"])
            else:
                filepath = Path(ydl.prepare_filename(info))
            
            if mode == "audio":
                filepath = filepath.with_suffix(".mp3")
            
            if not filepath.exists():
                return None, None, "File not found after download"
            
            return filepath, title, None
            
    except Exception as e:
        log.error(f"Download error: {e}")
        return None, None, str(e)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route("/download", methods=["POST"])
def download():
    """
    Download YouTube video/audio
    
    POST JSON:
    {
        "url": "https://youtube.com/watch?v=...",
        "mode": "video" or "audio"
    }
    
    Returns: file download
    """
    data = request.get_json()
    
    if not data or "url" not in data:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    url = data["url"]
    mode = data.get("mode", "video")
    
    if mode not in ["video", "audio"]:
        return jsonify({"error": "Mode must be 'video' or 'audio'"}), 400
    
    log.info(f"Download request: {url} ({mode})")
    
    filepath, title, error = _download_sync(url, mode)
    
    if error:
        return jsonify({"error": error}), 500
    
    if not filepath or not filepath.exists():
        return jsonify({"error": "Download failed"}), 500
    
    # Send file and delete after
    try:
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filepath.name
        )
    finally:
        # Clean up file after sending
        try:
            filepath.unlink(missing_ok=True)
        except:
            pass


@app.route("/info", methods=["POST"])
def get_info():
    """
    Get video info without downloading
    
    POST JSON:
    {
        "url": "https://youtube.com/watch?v=..."
    }
    
    Returns: JSON with title, thumbnail, duration
    """
    data = request.get_json()
    
    if not data or "url" not in data:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    url = data["url"]
    
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    log.info(f"Starting YouTube API on port {port}")
    app.run(host="0.0.0.0", port=port)
