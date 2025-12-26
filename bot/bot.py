"""
YouTube Download API Service
Simple HTTP API for downloading YouTube videos/audio using yt-dlp
"""

import os
import logging
import shutil
import json
from pathlib import Path
from urllib.parse import quote  # <--- Добавлено для исправления ошибки
from flask import Flask, request, jsonify, send_file, Response
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("yt-api")

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

def _ffmpeg_ok():
    return shutil.which("ffmpeg") is not None

def _download_sync(url: str, mode: str, quality: str = "720"):
    """Download video/audio and return filepath with metadata"""
    # Ограничиваем имя файла, чтобы избежать проблем с файловой системой,
    # но оригинальное название сохраним в метаданных
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
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                },
                {
                    "key": "EmbedThumbnail",
                },
            ],
            "writethumbnail": True,
        })
    else:
        # Video quality selection
        if quality == "1080":
            format_str = "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]/best[ext=mp4]/best"
        else:  # Default 720p
            format_str = "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best"
        
        ydl_opts.update({
            "format": format_str,
            "merge_output_format": "mp4",
        })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "video"
            artist = info.get("artist") or info.get("uploader") or info.get("channel") or ""
            thumbnail = info.get("thumbnail") or ""
            duration = info.get("duration") or 0
            
            if "requested_downloads" in info:
                filepath = Path(info["requested_downloads"][0]["filepath"])
            else:
                filepath = Path(ydl.prepare_filename(info))
            
            # Корректировка расширения для аудио, если yt-dlp еще не обновил имя
            if mode == "audio" and filepath.suffix != ".mp3":
                filepath = filepath.with_suffix(".mp3")
            
            if not filepath.exists():
                return None, None, "File not found after download"
            
            metadata = {
                "title": title,
                "artist": artist,
                "thumbnail": thumbnail,
                "duration": duration,
            }
            
            return filepath, metadata, None
            
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
    
    Returns: file with X-Metadata header containing JSON metadata
    """
    data = request.get_json()
    
    if not data or "url" not in data:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    url = data["url"]
    mode = data.get("mode", "video")
    quality = data.get("quality", "720")  # 720 or 1080
    
    if mode not in ["video", "audio"]:
        return jsonify({"error": "Mode must be 'video' or 'audio'"}), 400
    
    log.info(f"Download request: {url} ({mode}, {quality}p)")
    
    filepath, metadata, error = _download_sync(url, mode, quality)
    
    if error:
        return jsonify({"error": error}), 500
    
    if not filepath or not filepath.exists():
        return jsonify({"error": "Download failed"}), 500
    
    # Get file size for Content-Length header
    file_size = filepath.stat().st_size
    
    # Кодируем имя файла для использования в HTTP заголовке (RFC 5987)
    encoded_filename = quote(filepath.name)
    
    def generate():
        """Stream file in chunks to avoid memory issues"""
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(1024 * 64)  # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
        finally:
            # Cleanup after streaming
            try:
                filepath.unlink(missing_ok=True)
                for thumb in DOWNLOAD_DIR.glob("*.jpg"):
                    thumb.unlink(missing_ok=True)
                for thumb in DOWNLOAD_DIR.glob("*.webp"):
                    thumb.unlink(missing_ok=True)
            except:
                pass
    
    # Stream response instead of loading into memory
    response = Response(generate(), mimetype="application/octet-stream")
    response.headers["Content-Length"] = str(file_size)
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
    response.headers["X-Metadata"] = json.dumps(metadata)
    
    return response


@app.route("/info", methods=["POST"])
def get_info():
    """
    Get video info without downloading
    
    POST JSON:
    {
        "url": "https://youtube.com/watch?v=..."
    }
    
    Returns: JSON with title, thumbnail, duration, artist
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
                "artist": info.get("artist") or info.get("uploader") or info.get("channel"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    log.info(f"Starting YouTube API on port {port}")
    app.run(host="0.0.0.0", port=port)