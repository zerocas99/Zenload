import logging
from pathlib import Path
from dotenv import load_dotenv

if __name__ == "__main__":
    try:
        # Load environment variables from .env file
        load_dotenv(Path(__file__).parent / '.env')
        from src.bot import ZenloadBot
        # Initialize and run the bot
        bot = ZenloadBot()
        bot.run()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise


