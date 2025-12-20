# Zenload
# Database Migrations

The bot now includes automatic database migrations. When updating to a new version:

1. Pull the latest code from GitHub
2. Restart the bot

The UserSettingsManager will automatically:
- Check for missing columns in the database
- Add any new columns safely without affecting existing data
- Log any migration activities

No manual migration steps are required. The bot will handle all database updates automatically on startup.

High-performance Telegram bot for downloading videos from social media platforms.

## Features

- Fast and efficient video downloads
- Support for Instagram, TikTok, Pinterest, YouTube
- Automatic format optimization
- Clean and intuitive interface
- Robust error handling

## Installation

### Windows

1. Download and run `deploy.bat`
2. The script will:
   - Clone the repository
   - Set up Python environment
   - Install dependencies
   - Create necessary files
3. Edit `.env` file with your tokens:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token
YANDEX_MUSIC_TOKEN=your_yandex_token  # Optional
```
4. Run `run.bat` to start the bot

### Linux (VPS)

1. Download the deployment script:
```bash
wget https://raw.githubusercontent.com/RoninReilly/Zenload/main/deploy.sh
chmod +x deploy.sh
```

2. Run the script:
```bash
./deploy.sh
```

The script will:
- Install required packages (python3, python3-venv, git)
- Create installation directory (/opt/zenload)
- Clone the repository
- Set up Python environment
- Install dependencies
- Create systemd service
- Prompt for your tokens
- Start the bot automatically

The bot will be installed in `/opt/zenload` with proper permissions and systemd service configuration.

Optional: Add cookies/instagram.txt for enhanced Instagram functionality

## Updates

To update the bot to the latest version:

- Windows: Run `deploy.bat` again
- Linux: Run `./deploy.sh` again

The scripts will automatically pull the latest changes and update everything.

## Usage

1. Find @Zenload_bot on Telegram
2. Send a video URL from supported platforms
3. Receive the downloaded video

## Project Structure

```
zenload/
├── src/
│   ├── bot.py          # Bot core
│   ├── config.py       # Configuration
│   ├── downloaders/    # Platform-specific downloaders
│   ├── handlers/       # Telegram handlers
│   └── utils/         # Utility functions
├── downloads/         # Temporary downloads
├── cookies/          # Platform cookies
└── main.py          # Entry point
```

## Supported Platforms

- Instagram (Reels, Posts)
- TikTok
- Pinterest
- YouTube
- Yandex Music

## Technical Details

- Asynchronous download processing
- Memory-efficient file handling
- Automatic cleanup of temporary files
- Rate limiting and spam protection
- Comprehensive error handling

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


