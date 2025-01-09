import traceback
from datetime import datetime
from typing import Dict, Optional
import logging
from datetime import timezone

from xero_client import XeroClient
from supabase_client import SupabaseClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SyncManager:
    def __init__(self):
        self.supabase = SupabaseClient()
        self.xero = XeroClient(self.supabase)

    def run_sync(self, force_full_sync: bool = False) -> Dict:
        """Run the sync process"""
        start_time = datetime.now(timezone.utc)
        error_message = None
        records_processed = 0
        records_created = 0
        records_updated = 0
        items_processed = 0
        items_created = 0
        items_updated = 0

        try:
            # Check Xero authentication
            logger.info("Checking Xero authentication...")
            if not self.xero.ensure_authenticated():
                raise Exception("Not authenticated with Xero")
            logger.info("Successfully authenticated with Xero")

            # Get last sync time
            if not force_full_sync:
                last_sync = self.supabase.get_last_sync_time()
                if last_sync:
                    logger.info(f"Performing incremental sync from {last_sync}")
                else:
                    logger.info("No previous sync found, performing full sync")
            else:
                last_sync = None
                logger.info("Performing full sync")

            # Fetch invoices from Xero
            logger.info("Fetching invoices from Xero...")
            invoices = self.xero.get_invoices(modified_since=last_sync)
            records_processed = len(invoices)
            logger.info(f"Fetched {records_processed} invoices")

            # Sync invoices to Supabase
            if invoices:
                logger.info("Syncing invoices to Supabase...")
                stats = self.supabase.upsert_invoices(invoices)
                records_created = stats['created']
                records_updated = stats['updated']
                items_created = stats['items_created']
                items_updated = stats['items_updated']
                items_processed = items_created + items_updated
                logger.info(f"Sync complete. Created: {records_created}, Updated: {records_updated}, "
                          f"Items Created: {items_created}, Items Updated: {items_updated}")

            success = True
        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(f"Sync error: {error_message}")
            logger.error(f"Traceback: {traceback.format_exc()}")

        # Log sync results
        end_time = datetime.now(timezone.utc)
        try:
            self.supabase.log_sync(
                start_time=start_time,
                end_time=end_time,
                status='success' if success else 'error',
                error_message=error_message,
                records_processed=records_processed,
                records_created=records_created,
                records_updated=records_updated,
                items_processed=items_processed,
                items_created=items_created,
                items_updated=items_updated
            )
        except Exception as e:
            logger.error(f"Error logging sync: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

        return {
            'success': success,
            'error': error_message,
            'stats': {
                'processed': records_processed,
                'created': records_created,
                'updated': records_updated,
                'items_processed': items_processed,
                'items_created': items_created,
                'items_updated': items_updated
            }
        }

    def initialize_xero_auth(self) -> str:
        """Initialize Xero OAuth flow"""
        return self.xero.initialize_auth()

    def handle_xero_callback(self, auth_response: str) -> None:
        """Handle Xero OAuth callback"""
        self.xero.handle_callback(auth_response)
