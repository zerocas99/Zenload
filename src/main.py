import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
import signal
import sys
import platform

# Load environment variables before importing other modules
load_dotenv()

from .bot import ZenloadBot

def handle_exception(loop, context):
    """Handle exceptions in the event loop."""
    msg = context.get("exception", context["message"])
    logging.error(f"Caught exception: {msg}")

def main():
    """Main entry point for the bot"""
    try:
        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Set up exception handler
        loop.set_exception_handler(handle_exception)
        
        # Initialize bot
        bot = ZenloadBot()
        
        # Set up signal handling based on platform
        if platform.system() != 'Windows':
            # Unix-like systems can use asyncio signal handlers
            signals = (signal.SIGTERM, signal.SIGINT)
            for s in signals:
                loop.add_signal_handler(
                    s,
                    lambda s=s: asyncio.create_task(bot.stop())
                )
        else:
            # Windows needs a different approach
            def signal_handler(signum, frame):
                loop.create_task(bot.stop())
                sys.exit(0)
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        
        # Start the bot
        logging.info("Starting Zenload bot...")
        bot.run()
        
    except Exception as e:
        logging.error(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)
    finally:
        loop.close()

if __name__ == "__main__":
    main()



