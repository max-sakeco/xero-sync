import os
from datetime import datetime
from typing import Dict, List, Optional
import logging
from supabase import create_client, Client
import dateutil.parser
from urllib.parse import urlparse, parse_qs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define all possible invoice fields
INVOICE_FIELDS = [
    'invoice_id', 'tenant_id', 'contact_id', 'contact_name', 'invoice_number',
    'reference', 'issue_date', 'due_date', 'status', 'line_amount_types',
    'sub_total', 'total_tax', 'total', 'currency_code', 'type', 'xero_updated_at'
]

# Define all possible invoice item fields
INVOICE_ITEM_FIELDS = [
    'item_id', 'invoice_id', 'tenant_id', 'description', 'quantity',
    'unit_amount', 'tax_amount', 'line_amount', 'account_code', 'tax_type',
    'item_code', 'tracking'
]

class SupabaseClient:
    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
        self.client = create_client(url, key)

    def get_last_sync_time(self) -> Optional[datetime]:
        """Get the timestamp of the last successful sync"""
        result = self.client.from_('sync_logs')\
            .select('end_time')\
            .eq('status', 'success')\
            .order('end_time', desc=True)\
            .limit(1)\
            .execute()
        
        if result.data:
            # Parse the timestamp string to datetime
            try:
                return dateutil.parser.parse(result.data[0]['end_time'])
            except Exception as e:
                logger.error(f"Error parsing last sync time: {e}")
                return None
        return None

    def handle_xero_callback(self, auth_response: str) -> None:
        """Handle Xero OAuth callback"""
        # Extract code and state from callback URL
        parsed_url = urlparse(auth_response)
        params = parse_qs(parsed_url.query)
        
        if 'code' not in params:
            raise ValueError("No authorization code found in callback URL")
        
        return params['code'][0]

    def _parse_date(self, date_value: Optional[any]) -> Optional[str]:
        """Parse a date value and return ISO format"""
        if not date_value:
            return None
        try:
            if isinstance(date_value, datetime):
                return date_value.isoformat()
            return dateutil.parser.parse(str(date_value)).isoformat()
        except Exception as e:
            logger.warning(f"Error parsing date {date_value}: {e}")
            return None

    def _transform_invoice_items(self, invoice: Dict, tenant_id: str) -> List[Dict]:
        """Transform invoice line items"""
        items = []
        line_items = invoice.get('LineItems', [])
        
        for item in line_items:
            try:
                # Create item with all possible fields initialized to None
                transformed_item = {field: None for field in INVOICE_ITEM_FIELDS}
                
                # Update with actual values
                transformed_item.update({
                    'item_id': item.get('LineItemID'),
                    'invoice_id': invoice.get('InvoiceID'),
                    'tenant_id': tenant_id,
                    'description': item.get('Description'),
                    'quantity': float(item.get('Quantity', 0)),
                    'unit_amount': float(item.get('UnitAmount', 0)),
                    'tax_amount': float(item.get('TaxAmount', 0)),
                    'line_amount': float(item.get('LineAmount', 0)),
                    'account_code': item.get('AccountCode'),
                    'tax_type': item.get('TaxType'),
                    'item_code': item.get('ItemCode'),
                    'tracking': item.get('Tracking')
                })
                
                items.append(transformed_item)
            except Exception as e:
                logger.error(f"Error transforming invoice item: {str(e)}")
                logger.error(f"Item data: {item}")
                continue
                
        return items

    def upsert_invoices(self, invoices: List[Dict]) -> Dict[str, int]:
        """Bulk upsert invoices and their line items into Supabase"""
        if not invoices:
            return {'created': 0, 'updated': 0, 'items_created': 0, 'items_updated': 0}

        # Transform Xero invoice data to match our schema
        transformed_invoices = []
        all_invoice_items = []
        
        for invoice in invoices:
            try:
                logger.debug(f"Processing invoice: {invoice.get('InvoiceID')}")
                
                # Parse dates
                issue_date = self._parse_date(invoice.get('Date'))
                due_date = self._parse_date(invoice.get('DueDate'))
                updated_date = self._parse_date(invoice.get('UpdatedDateUTC'))
                
                # Create invoice with all possible fields initialized to None
                transformed_invoice = {field: None for field in INVOICE_FIELDS}
                
                # Update with actual values
                transformed_invoice.update({
                    'invoice_id': invoice.get('InvoiceID'),
                    'tenant_id': invoice.get('tenant_id'),
                    'contact_id': invoice.get('Contact', {}).get('ContactID'),
                    'contact_name': invoice.get('Contact', {}).get('Name'),
                    'invoice_number': invoice.get('InvoiceNumber'),
                    'reference': invoice.get('Reference'),
                    'issue_date': issue_date,
                    'due_date': due_date,
                    'status': invoice.get('Status'),
                    'line_amount_types': invoice.get('LineAmountTypes'),
                    'sub_total': float(invoice.get('SubTotal', 0)),
                    'total_tax': float(invoice.get('TotalTax', 0)),
                    'total': float(invoice.get('Total', 0)),
                    'currency_code': invoice.get('CurrencyCode'),
                    'type': invoice.get('Type'),
                    'xero_updated_at': updated_date
                })
                
                transformed_invoices.append(transformed_invoice)
                
                # Transform and collect invoice items
                invoice_items = self._transform_invoice_items(invoice, invoice.get('tenant_id'))
                all_invoice_items.extend(invoice_items)
                
            except Exception as e:
                logger.error(f"Error transforming invoice {invoice.get('InvoiceID')}: {str(e)}")
                logger.error(f"Invoice data: {invoice}")
                continue

        if not transformed_invoices:
            logger.warning("No invoices were successfully transformed")
            return {'created': 0, 'updated': 0, 'items_created': 0, 'items_updated': 0}

        stats = {'created': 0, 'updated': 0, 'items_created': 0, 'items_updated': 0}

        try:
            # Sync invoices
            logger.info(f"Upserting {len(transformed_invoices)} invoices to Supabase")
            batch_size = 100
            
            for i in range(0, len(transformed_invoices), batch_size):
                batch = transformed_invoices[i:i + batch_size]
                logger.info(f"Processing invoice batch {i//batch_size + 1} of {(len(transformed_invoices) + batch_size - 1)//batch_size}")
                
                result = self.client.from_('invoices')\
                    .upsert(
                        batch,
                        on_conflict='invoice_id'
                    )\
                    .execute()
                
                if result.data:
                    batch_created = len([r for r in result.data if r.get('created_at') == r.get('updated_at')])
                    stats['created'] += batch_created
                    stats['updated'] += len(result.data) - batch_created

            # Sync invoice items
            logger.info(f"Upserting {len(all_invoice_items)} invoice items to Supabase")
            for i in range(0, len(all_invoice_items), batch_size):
                batch = all_invoice_items[i:i + batch_size]
                logger.info(f"Processing items batch {i//batch_size + 1} of {(len(all_invoice_items) + batch_size - 1)//batch_size}")
                
                result = self.client.from_('invoice_items')\
                    .upsert(
                        batch,
                        on_conflict='item_id'
                    )\
                    .execute()
                
                if result.data:
                    batch_created = len([r for r in result.data if r.get('created_at') == r.get('updated_at')])
                    stats['items_created'] += batch_created
                    stats['items_updated'] += len(result.data) - batch_created

            return stats
        except Exception as e:
            logger.error(f"Error upserting data: {str(e)}")
            raise

    def get_token(self, tenant_id: str) -> Optional[Dict]:
        """Get the OAuth token for a tenant"""
        try:
            response = self.client.from_('oauth_tokens')\
                .select('*')\
                .eq('tenant_id', tenant_id)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting token: {str(e)}")
            raise

    def log_sync(self, start_time: datetime, end_time: datetime, status: str,
                error_message: Optional[str] = None, records_processed: int = 0,
                records_created: int = 0, records_updated: int = 0,
                items_processed: int = 0, items_created: int = 0,
                items_updated: int = 0) -> None:
        """Log sync results to Supabase"""
        log_data = {
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'status': status,
            'error_message': error_message,
            'records_processed': records_processed,
            'records_created': records_created,
            'records_updated': records_updated,
            'items_processed': items_processed,
            'items_created': items_created,
            'items_updated': items_updated
        }
        
        try:
            self.client.from_('sync_logs')\
                .insert(log_data)\
                .execute()
        except Exception as e:
            logger.error(f"Error logging sync: {str(e)}")
            raise

    def log_error(self, error_type: str, error_message: str, stack_trace: Optional[str] = None, 
                 additional_data: Optional[Dict] = None):
        """Log error details"""
        error_entry = {
            'error_type': error_type,
            'error_message': error_message,
            'stack_trace': stack_trace,
            'additional_data': additional_data
        }
        
        self.client.from_('error_logs')\
            .insert(error_entry)\
            .execute()
