from flask import Flask, request, redirect
import os
from sync_manager import SyncManager
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
sync_manager = None

@app.route('/')
def index():
    """Initialize OAuth flow"""
    global sync_manager
    try:
        sync_manager = SyncManager()
        auth_url = sync_manager.initialize_xero_auth()
        logger.info(f"Generated auth URL: {auth_url}")
        return redirect(auth_url)
    except Exception as e:
        logger.error(f"Error initializing auth: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/callback')
def callback():
    """Handle OAuth callback"""
    if 'code' in request.args:
        try:
            sync_manager.handle_xero_callback(request.url)
            return "Authentication successful! You can close this window."
        except Exception as e:
            logger.error(f"Callback error: {str(e)}")
            return f"Authentication failed: {str(e)}", 500
    return "No authorization code received", 400

if __name__ == '__main__':
    try:
        load_dotenv()
        logger.info("Starting authentication server...")
        app.run(host='localhost', port=8000, debug=True)
    except Exception as e:
        logger.error(f"Server startup error: {str(e)}")
