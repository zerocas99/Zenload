import logging
import threading
import os
from pathlib import Path
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple health check handler for container orchestrators"""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def log_message(self, format, *args):
        pass  # Suppress HTTP logs

def start_health_server():
    """Start health check server in background thread"""
    port = int(os.getenv('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

if __name__ == "__main__":
    try:
        # Load environment variables from .env file
        load_dotenv(Path(__file__).parent / '.env')
        
        # Start health check server for Choreo/K8s
        health_thread = threading.Thread(target=start_health_server, daemon=True)
        health_thread.start()
        logging.info(f"Health check server started on port {os.getenv('PORT', 8080)}")
        
        from src.bot import ZenloadBot
        # Initialize and run the bot
        bot = ZenloadBot()
        bot.run()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise


