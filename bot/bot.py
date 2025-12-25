import os, re, asyncio, logging, shutil
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("ytbot")

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "48"))

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

YOUTUBE_URL_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+", re.IGNORECASE)

def _ffmpeg_ok(): return shutil.which("ffmpeg") is not None

def _download_sync(url, mode):
    import yt_dlp
    outtmpl = str(DOWNLOAD_DIR / "%(title).200s.%(ext)s")
    ydl_opts = {"outtmpl": outtmpl, "noplaylist": True, "quiet": True, "no_warnings": True}
    if mode == "audio":
        if not _ffmpeg_ok(): return None, None, "ffmpeg is required for MP3"
        ydl_opts.update({"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio","preferredcodec": "mp3","preferredquality": "192"}]})
    else:
        ydl_opts.update({"format": "bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/best[ext=mp4]/best","merge_output_format": "mp4"})
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "video"
            filepath = Path(info["requested_downloads"][0]["filepath"]) if "requested_downloads" in info else Path(ydl.prepare_filename(info))
            if mode == "audio": filepath = filepath.with_suffix(".mp3")
            return filepath, title, None
    except Exception as e:
        return None, None, f"Error: {e!s}"

async def download(url, mode): return await asyncio.to_thread(_download_sync, url, mode)

WELCOME = "👋 Hi! Send me a YouTube link and choose: video or audio."

async def start(update, context): await update.message.reply_text(WELCOME)
async def help_cmd(update, context): await update.message.reply_text("Send me a YouTube link. I’ll let you choose video or audio.")

def _make_choice_kb(url): return InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Video MP4", callback_data=f"video|{url}")],[InlineKeyboardButton("🎵 Audio MP3", callback_data=f"audio|{url}")]])

async def on_text(update, context):
    text = update.message.text.strip()
    if not YOUTUBE_URL_RE.search(text): return
    url = YOUTUBE_URL_RE.search(text).group(0)
    await update.message.reply_text("Choose format:", reply_markup=_make_choice_kb(url))

async def on_choice(update, context):
    query = update.callback_query; await query.answer()
    mode, url = query.data.split("|", 1)
    msg = await query.edit_message_text("⏳ Downloading...")
    filepath, title, err = await download(url, mode)
    if err: return await msg.edit_text(f"❌ {err}")
    if not filepath or not filepath.exists(): return await msg.edit_text("❌ File not found.")
    size_mb = filepath.stat().st_size / (1024*1024)
    if size_mb > MAX_UPLOAD_MB: return await msg.edit_text(f"⚠️ File too big: {size_mb:.1f} MB > {MAX_UPLOAD_MB} MB")
    if mode == "audio":
        await context.bot.send_audio(chat_id=query.message.chat.id, audio=filepath.open("rb"), title=title, caption=f"🎵 {title}")
    else:
        await context.bot.send_document(chat_id=query.message.chat.id, document=filepath.open("rb"), filename=filepath.name, caption=f"🎬 {title}")
    await msg.delete(); filepath.unlink(missing_ok=True)


def main():
    if not BOT_TOKEN: raise SystemExit("BOT_TOKEN missing in .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))
    app.add_handler(CallbackQueryHandler(on_choice))
    log.info("Bot started. Ctrl+C to stop."); app.run_polling(close_loop=False)

if __name__ == "__main__": main()
