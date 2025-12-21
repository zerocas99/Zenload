const express = require("express");
const app = express();
const snapsave = require("./snapsave-downloader/src/index");
const ytdl = require("ytdl-core-enhanced");
const port = 3000;

app.get("/", (req, res) => {
  res.json({ message: "Hello World!" });
});

app.get("/igdl", async (req, res) => {
  try {
    const url = req.query.url;

    if (!url) {
      return res.status(400).json({ error: "URL parameter is missing" });
    }

    const downloadedURL = await snapsave(url);
    res.json({ url: downloadedURL });
  } catch (err) {
    console.error("Error:", err.message);
    res.status(500).json({ error: "Internal Server Error" });
  }
});

// YouTube video info endpoint
app.get("/youtube/info", async (req, res) => {
  try {
    const url = req.query.url;
    if (!url) {
      return res.status(400).json({ error: "URL parameter is missing" });
    }

    const info = await ytdl.getInfo(url);
    const formats = info.formats.filter(f => f.hasVideo && f.hasAudio);
    
    res.json({
      success: true,
      title: info.videoDetails.title,
      duration: info.videoDetails.lengthSeconds,
      thumbnail: info.videoDetails.thumbnails?.pop()?.url,
      channel: info.videoDetails.author?.name,
      formats: formats.map(f => ({
        itag: f.itag,
        quality: f.qualityLabel,
        container: f.container,
        hasAudio: f.hasAudio,
        hasVideo: f.hasVideo,
        url: f.url
      }))
    });
  } catch (err) {
    console.error("YouTube info error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// YouTube video download - returns direct URL
app.get("/youtube/video", async (req, res) => {
  try {
    const url = req.query.url;
    const quality = req.query.quality || "highest";
    
    if (!url) {
      return res.status(400).json({ error: "URL parameter is missing" });
    }

    const info = await ytdl.getInfo(url);
    
    // Find best format with video+audio
    let format;
    if (quality === "highest") {
      format = ytdl.chooseFormat(info.formats, { quality: 'highestvideo', filter: 'audioandvideo' });
    } else {
      // Try to find specific quality
      const targetHeight = parseInt(quality);
      format = info.formats.find(f => 
        f.hasVideo && f.hasAudio && f.height <= targetHeight
      ) || ytdl.chooseFormat(info.formats, { quality: 'highestvideo', filter: 'audioandvideo' });
    }

    if (!format || !format.url) {
      return res.status(404).json({ error: "No suitable format found" });
    }

    res.json({
      success: true,
      title: info.videoDetails.title,
      url: format.url,
      quality: format.qualityLabel,
      container: format.container
    });
  } catch (err) {
    console.error("YouTube video error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// YouTube audio download - returns direct URL
app.get("/youtube/audio", async (req, res) => {
  try {
    const url = req.query.url;
    
    if (!url) {
      return res.status(400).json({ error: "URL parameter is missing" });
    }

    const info = await ytdl.getInfo(url);
    const format = ytdl.chooseFormat(info.formats, { quality: 'highestaudio', filter: 'audioonly' });

    if (!format || !format.url) {
      return res.status(404).json({ error: "No audio format found" });
    }

    res.json({
      success: true,
      title: info.videoDetails.title,
      url: format.url,
      container: format.container,
      audioBitrate: format.audioBitrate
    });
  } catch (err) {
    console.error("YouTube audio error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// YouTube stream proxy (for direct download)
app.get("/youtube/stream", async (req, res) => {
  try {
    const url = req.query.url;
    const type = req.query.type || "video"; // video or audio
    
    if (!url) {
      return res.status(400).json({ error: "URL parameter is missing" });
    }

    const info = await ytdl.getInfo(url);
    const title = info.videoDetails.title.replace(/[^\w\s-]/g, '').substring(0, 50);
    
    let format;
    let ext;
    
    if (type === "audio") {
      format = ytdl.chooseFormat(info.formats, { quality: 'highestaudio', filter: 'audioonly' });
      ext = format.container || 'm4a';
    } else {
      format = ytdl.chooseFormat(info.formats, { quality: 'highestvideo', filter: 'audioandvideo' });
      ext = format.container || 'mp4';
    }

    res.header('Content-Disposition', `attachment; filename="${title}.${ext}"`);
    res.header('Content-Type', type === 'audio' ? 'audio/mp4' : 'video/mp4');
    
    ytdl(url, { format }).pipe(res);
  } catch (err) {
    console.error("YouTube stream error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

app.listen(port, () => {
  console.log(`Server is running at http://localhost:${port}`);
});
