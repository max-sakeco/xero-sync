import os
import sys
import time
import argparse
import schedule
import threading
from datetime import datetime
from dotenv import load_dotenv
import logging

# Initialize logger
logger = logging.getLogger(__name__)

from sync_manager import SyncManager
from xero_client import XeroClient
from supabase_client import SupabaseClient
from health import app as health_app

def run_sync(force_full_sync: bool = False):
    """Run the sync process and handle results"""
    sync_manager = SyncManager()
    result = sync_manager.run_sync(force_full_sync)
    
    if result['success']:
        print(f"Sync completed successfully at {datetime.now().isoformat()}")
        print(f"Processed: {result['stats']['processed']}")
        print(f"Created: {result['stats']['created']}")
        print(f"Updated: {result['stats']['updated']}")
    else:
        print(f"Sync failed at {datetime.now().isoformat()}")
        print(f"Error: {result['error']}")

def init_auth(callback_url: str = None):
    """Initialize Xero OAuth2 authentication"""
    supabase = SupabaseClient()
    xero = XeroClient(supabase)
    
    if not callback_url:
        auth_url = xero.initialize_auth()
        print("\nPlease visit this URL to authorize the application:")
        print(auth_url)
        print("\nAfter authorization, run this command again with the callback URL:")
        print("python main.py --init-auth --callback-url 'YOUR_CALLBACK_URL'")
        return
    
    try:
        xero.handle_callback(callback_url)
        print("\nAuthorization completed successfully!")
    except Exception as e:
        print(f"\nError during authorization: {str(e)}")
        sys.exit(1)

def start_health_server():
    health_app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))

def main():
    # Load environment variables
    load_dotenv()

    # Verify required environment variables
    required_vars = [
        'XERO_CLIENT_ID',
        'XERO_CLIENT_SECRET',
        'XERO_REDIRECT_URI',
        'SUPABASE_URL',
        'SUPABASE_KEY'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Xero to Supabase Invoice Sync')
    parser.add_argument('--sync-now', action='store_true', 
                      help='Run sync immediately')
    parser.add_argument('--force-full', action='store_true',
                      help='Force full sync instead of incremental')
    parser.add_argument('--init-auth', action='store_true',
                      help='Initialize Xero OAuth2 authentication')
    parser.add_argument('--callback-url', type=str,
                      help='Callback URL from Xero authorization')
    args = parser.parse_args()

    # Start health check server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

    # Handle init-auth command
    if args.init_auth:
        init_auth(args.callback_url)
        return

    # Get sync interval from env or default to 24 hours
    sync_interval = int(os.getenv('SYNC_INTERVAL_HOURS', '24'))

    # Schedule regular sync
    schedule.every(sync_interval).hours.do(run_sync)
    
    # Run immediate sync if requested
    if args.sync_now:
        run_sync(args.force_full)
        if not args.force_full:
            return

    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == '__main__':
    main()
