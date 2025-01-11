import logging
from datetime import datetime, timezone
import traceback
from typing import Dict, List, Optional

from xero_client import XeroClient
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

class SyncManager:
    def __init__(self):
        self.supabase = SupabaseClient()
        self.xero = XeroClient(self.supabase)

    def run_sync(self, force_full_sync: bool = False) -> Dict:
        """Run the sync process"""
        sync_id = None
        stats = {
            'processed': 0,
            'created': 0,
            'updated': 0,
            'items_processed': 0,
            'items_created': 0,
            'items_updated': 0
        }
        
        try:
            # Start sync log
            sync_id = self._create_sync_log()

            # Get last successful sync time unless force_full_sync is True
            modified_since = None if force_full_sync else self.get_last_successful_sync()
            if modified_since:
                logger.info(f"Incremental sync from: {modified_since}")
            else:
                logger.info("Full sync initiated")

            # Fetch invoices from Xero
            invoices = self.xero.get_invoices(modified_since)
            stats['processed'] = len(invoices)
            
            # Process each invoice
            for invoice in invoices:
                try:
                    created = self._upsert_invoice(invoice)
                    if created:
                        stats['created'] += 1
                    else:
                        stats['updated'] += 1
                except Exception as e:
                    logger.error(f"Error processing invoice {invoice.get('InvoiceID')}: {str(e)}")

            # Update sync log with results
            self._update_sync_log(sync_id, 'success', stats)
            
            return {
                'success': True,
                'error': None,
                'stats': stats
            }

        except Exception as e:
            logger.error(f"Sync failed: {str(e)}")
            if sync_id:
                self._update_sync_log(sync_id, 'error', stats, str(e))
            return {
                'success': False,
                'error': str(e),
                'stats': stats
            }

    def _parse_xero_date(self, date_str: str) -> str:
        """Convert Xero date format to ISO format"""
        if not date_str or not isinstance(date_str, str):
            return None
        
        try:
            # Extract timestamp from /Date(1234567890000+0000)/
            timestamp_str = date_str.replace('/Date(', '').replace('+0000)/', '')
            # Convert milliseconds to seconds
            timestamp = int(timestamp_str) / 1000
            # Convert to datetime
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            # Return date only for DATE fields, full ISO for TIMESTAMP fields
            return dt.date().isoformat()
        except Exception as e:
            logger.error(f"Error parsing date {date_str}: {e}")
            return None

    def _parse_xero_datetime(self, date_str: str) -> str:
        """Convert Xero datetime format to ISO format"""
        if not date_str or not isinstance(date_str, str):
            return None
        
        try:
            # Extract timestamp from /Date(1234567890000+0000)/
            timestamp_str = date_str.replace('/Date(', '').replace('+0000)/', '')
            # Convert milliseconds to seconds
            timestamp = int(timestamp_str) / 1000
            # Convert to datetime
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            # Return full ISO format
            return dt.isoformat()
        except Exception as e:
            logger.error(f"Error parsing datetime {date_str}: {e}")
            return None

    def _upsert_invoice(self, invoice_data: Dict) -> bool:
        """Insert or update an invoice and its line items"""
        try:
            # Prepare invoice data
            invoice = {
                'invoice_id': invoice_data['InvoiceID'],
                'tenant_id': self.xero.tenant_id,
                'invoice_number': invoice_data.get('InvoiceNumber'),
                'reference': invoice_data.get('Reference'),
                'type': invoice_data.get('Type'),
                'status': invoice_data.get('Status'),
                'contact_id': invoice_data.get('Contact', {}).get('ContactID'),
                'contact_name': invoice_data.get('Contact', {}).get('Name'),
                'date': self._parse_xero_date(invoice_data.get('Date')),
                'due_date': self._parse_xero_date(invoice_data.get('DueDate')),
                'updated_date_utc': self._parse_xero_datetime(invoice_data.get('UpdatedDateUTC')),
                'currency_code': invoice_data.get('CurrencyCode'),
                'sub_total': float(invoice_data.get('SubTotal', 0)),
                'total_tax': float(invoice_data.get('TotalTax', 0)),
                'total': float(invoice_data.get('Total', 0)),
                'amount_credited': float(invoice_data.get('AmountCredited', 0)),
                'amount_paid': float(invoice_data.get('AmountPaid', 0)),
                'amount_due': float(invoice_data.get('AmountDue', 0))
            }

            logger.debug(f"Prepared invoice data: {invoice}")

            # Check if invoice exists
            result = self.supabase.client.from_('invoices_new')\
                .select('id')\
                .eq('invoice_id', invoice['invoice_id'])\
                .execute()

            is_new = not result.data

            if is_new:
                # Insert new invoice
                result = self.supabase.client.from_('invoices_new')\
                    .insert(invoice)\
                    .execute()
                invoice_id = result.data[0]['id']
                logger.info(f"Created new invoice: {invoice_id}")
            else:
                # Update existing invoice
                invoice_id = result.data[0]['id']
                self.supabase.client.from_('invoices_new')\
                    .update(invoice)\
                    .eq('id', invoice_id)\
                    .execute()
                logger.info(f"Updated existing invoice: {invoice_id}")

            # Process line items
            self._process_line_items(invoice_id, invoice_data.get('LineItems', []))

            return is_new

        except Exception as e:
            logger.error(f"Error upserting invoice: {str(e)}")
            logger.error(f"Failed invoice data: {invoice_data}")
            raise

    def _process_line_items(self, invoice_id: str, line_items: List[Dict]):
        """Process invoice line items"""
        try:
            for item in line_items:
                line_item = {
                    'invoice_id': invoice_id,
                    'line_item_id': item.get('LineItemID'),
                    'description': item.get('Description'),
                    'quantity': float(item.get('Quantity', 0)),
                    'unit_amount': float(item.get('UnitAmount', 0)),
                    'tax_amount': float(item.get('TaxAmount', 0)),
                    'line_amount': float(item.get('LineAmount', 0)),
                    'account_code': item.get('AccountCode'),
                    'tax_type': item.get('TaxType')
                }

                # Upsert line item
                self.supabase.client.from_('invoice_items_new')\
                    .upsert(line_item, on_conflict='invoice_id,line_item_id')\
                    .execute()

        except Exception as e:
            logger.error(f"Error processing line items: {str(e)}")
            raise

    def _create_sync_log(self) -> str:
        """Create a new sync log entry"""
        result = self.supabase.client.from_('sync_logs')\
            .insert({
                'start_time': datetime.now(timezone.utc).isoformat(),
                'status': 'in_progress',
                'records_processed': 0,
                'records_created': 0,
                'records_updated': 0
            })\
            .execute()
        return result.data[0]['id']

    def _update_sync_log(self, sync_id: str, status: str, stats: Dict, error: Optional[str] = None):
        """Update sync log with results"""
        self.supabase.client.from_('sync_logs')\
            .update({
                'end_time': datetime.now(timezone.utc).isoformat(),
                'status': status,
                'records_processed': stats['processed'],
                'records_created': stats['created'],
                'records_updated': stats['updated'],
                'error_message': error
            })\
            .eq('id', sync_id)\
            .execute()

    def initialize_xero_auth(self) -> str:
        """Initialize Xero OAuth flow"""
        return self.xero.initialize_auth()

    def handle_xero_callback(self, auth_response: str) -> None:
        """Handle Xero OAuth callback"""
        self.xero.handle_callback(auth_response)

    def get_last_successful_sync(self) -> Optional[datetime]:
        """Get the last successful sync time"""
        try:
            # Get the earliest invoice's updated_date_utc
            result = self.supabase.client.from_('invoices_new')\
                .select('updated_date_utc')\
                .order('updated_date_utc', desc=False)\
                .limit(1)\
                .execute()

            if result.data:
                # Use the earliest invoice date as our starting point
                return datetime.fromisoformat(result.data[0]['updated_date_utc'])
            
            # If no invoices exist, return None for full sync
            return None

        except Exception as e:
            logger.error(f"Error getting last sync time: {str(e)}")
            return None
