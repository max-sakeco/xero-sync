from flask import Flask, jsonify, redirect, request
import os
import logging
from sync_manager import SyncManager
import requests
from xero_client import XeroClient
from supabase_client import SupabaseClient
from urllib.parse import urlencode
from datetime import datetime, timezone

# Configure logging with more detail
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
sync_manager = None

@app.route('/')
def health():
    return jsonify({'status': 'ok'})

@app.get("/auth")
def auth():
    """Start OAuth flow with Xero"""
    try:
        xero = XeroClient(SupabaseClient())
        authorization_url = xero.get_authorization_url()
        logger.info(f"Generated authorization URL: {authorization_url}")
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Auth failed: {str(e)}")
        return {"message": str(e), "status": "error"}

@app.get("/callback")
def auth_callback():
    """Handle OAuth callback from Xero"""
    try:
        # Log all query parameters
        logger.info("Callback received with params:")
        for key, value in request.args.items():
            logger.info(f"{key}: {value}")

        code = request.args.get('code')
        if not code:
            error = request.args.get('error')
            error_description = request.args.get('error_description')
            logger.error(f"No code provided. Error: {error}, Description: {error_description}")
            return {"error": error_description or "No code provided"}, 400

        xero = XeroClient(SupabaseClient())
        success = xero.process_callback(code)

        if success:
            # Redirect to a success page
            params = urlencode({'status': 'success'})
            return redirect(f"/?{params}")
        else:
            # Redirect to an error page
            params = urlencode({'status': 'error', 'message': 'Authentication failed'})
            return redirect(f"/?{params}")

    except Exception as e:
        logger.error(f"Callback failed: {str(e)}")
        # Redirect to an error page
        params = urlencode({'status': 'error', 'message': str(e)})
        return redirect(f"/?{params}")

@app.get("/sync")
def sync():
    """Sync data from Xero"""
    try:
        force_full_sync = request.args.get('force_full_sync', '').lower() == 'true'
        xero = XeroClient(SupabaseClient())
        stats = {
            'contacts': {'processed': 0, 'created': 0, 'updated': 0},
            'invoices': {'processed': 0, 'created': 0, 'updated': 0, 'items_processed': 0, 'items_created': 0, 'items_updated': 0}
        }

        # First sync contacts
        logger.info("Starting contacts sync")
        contacts = xero.get_contacts()
        logger.info(f"Got {len(contacts)} contacts to process")

        for contact in contacts:
            try:
                stats['contacts']['processed'] += 1
                
                # Parse the date
                updated_date_str = contact.get('UpdatedDateUTC')
                if updated_date_str and "/Date(" in updated_date_str:
                    # Remove "/Date(" and "+0000)/"
                    timestamp_ms = int(updated_date_str.replace("/Date(", "").replace("+0000)/", ""))
                    updated_date = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
                else:
                    updated_date = datetime.now(timezone.utc)

                # Extract contact data
                contact_data = {
                    'contact_id': contact['ContactID'],
                    'tenant_id': xero.tenant_id,
                    'name': contact.get('Name', ''),
                    'first_name': None,  # Not provided in the data
                    'last_name': None,   # Not provided in the data
                    'email': contact.get('EmailAddress', ''),
                    'updated_date_utc': updated_date.isoformat()
                }

                logger.debug(f"Processing contact: {contact_data['name']} ({contact_data['contact_id']})")
                logger.debug(f"Contact data to insert: {contact_data}")

                # Upsert contact
                result = xero.supabase.client.from_('contacts')\
                    .upsert(contact_data, on_conflict='contact_id')\
                    .execute()

                if result.data:
                    stats['contacts']['created'] += 1
                    logger.debug(f"Created/Updated contact: {contact_data['name']}")

            except Exception as e:
                logger.error(f"Error processing contact {contact.get('ContactID')}: {str(e)}")
                continue

        logger.info(f"Completed contact sync. Stats: {stats['contacts']}")

        # Then sync invoices
        logger.info("Starting invoices sync")
        invoices = xero.get_invoices()
        logger.info(f"Got {len(invoices)} invoices to process")

        for invoice in invoices:
            try:
                stats['invoices']['processed'] += 1
                logger.info(f"Processing invoice {stats['invoices']['processed']}/{len(invoices)}")
                
                # Parse dates
                date_str = invoice.get('DateString')
                due_date_str = invoice.get('DueDateString')
                updated_date_str = invoice.get('UpdatedDateUTC')

                logger.debug(f"Raw dates - date: {date_str}, due_date: {due_date_str}, updated: {updated_date_str}")

                # Handle date parsing
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S') if date_str else None
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M:%S') if due_date_str else None
                except ValueError as e:
                    logger.error(f"Error parsing dates: {str(e)}")
                    logger.error(f"Raw date strings: date={date_str}, due_date={due_date_str}")
                    date = None
                    due_date = None
                
                if updated_date_str and "/Date(" in updated_date_str:
                    timestamp_ms = int(updated_date_str.replace("/Date(", "").replace("+0000)/", ""))
                    updated_date = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
                else:
                    updated_date = datetime.now(timezone.utc)

                # Get contact details
                contact = invoice.get('Contact', {})
                contact_id = contact.get('ContactID')
                contact_name = contact.get('Name')

                # Extract invoice data
                try:
                    invoice_data = {
                        'invoice_id': invoice['InvoiceID'],
                        'tenant_id': xero.tenant_id,
                        'invoice_number': invoice.get('InvoiceNumber'),
                        'reference': invoice.get('Reference'),
                        'type': invoice.get('Type'),
                        'status': invoice.get('Status'),
                        'contact_id': contact_id,
                        'contact_name': contact_name,
                        'date': date.date().isoformat() if date else None,
                        'due_date': due_date.date().isoformat() if due_date else None,
                        'updated_date_utc': updated_date.isoformat(),
                        'currency_code': invoice.get('CurrencyCode'),
                        'sub_total': str(invoice.get('SubTotal', '0')),  # Convert to string first
                        'total_tax': str(invoice.get('TotalTax', '0')),
                        'total': str(invoice.get('Total', '0')),
                        'amount_due': str(invoice.get('AmountDue', '0')),
                        'amount_paid': str(invoice.get('AmountPaid', '0')),
                        'amount_credited': str(invoice.get('AmountCredited', '0'))
                    }
                except Exception as e:
                    logger.error(f"Error preparing invoice data: {str(e)}")
                    logger.error(f"Raw invoice: {invoice}")
                    continue

                logger.debug(f"Processing invoice: {invoice_data['invoice_number']} ({invoice_data['invoice_id']})")

                try:
                    # Upsert invoice
                    result = xero.supabase.client.from_('invoices_new')\
                        .upsert(invoice_data, on_conflict='invoice_id')\
                        .execute()

                    if result.data:
                        stats['invoices']['created'] += 1
                        logger.debug(f"Created/Updated invoice: {invoice_data['invoice_number']}")

                        # Process line items
                        line_items = invoice.get('LineItems', [])
                        for item in line_items:
                            try:
                                stats['invoices']['items_processed'] += 1
                                
                                item_data = {
                                    'xero_invoice_id': invoice['InvoiceID'],
                                    'line_item_id': item.get('LineItemID'),
                                    'description': item.get('Description'),
                                    'quantity': str(item.get('Quantity', '0')),
                                    'unit_amount': str(item.get('UnitAmount', '0')),
                                    'tax_amount': str(item.get('TaxAmount', '0')),
                                    'line_amount': str(item.get('LineAmount', '0')),
                                    'account_code': item.get('AccountCode'),
                                    'tax_type': item.get('TaxType')
                                }

                                result = xero.supabase.client.from_('invoice_items_new')\
                                    .upsert(item_data, on_conflict='xero_invoice_id,line_item_id')\
                                    .execute()

                                if result.data:
                                    stats['invoices']['items_created'] += 1
                            except Exception as e:
                                logger.error(f"Error processing line item: {str(e)}")
                                logger.error(f"Line item data: {item}")
                                continue

                except Exception as e:
                    logger.error(f"Error upserting invoice: {str(e)}")
                    logger.error(f"Invoice data: {invoice_data}")
                    continue

            except Exception as e:
                logger.error(f"Error processing invoice {invoice.get('InvoiceID')}: {str(e)}")
                logger.error(f"Raw invoice data: {invoice}")
                continue

        logger.info(f"Completed invoice sync. Stats: {stats}")

        return {
            "success": True,
            "stats": stats
        }

    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "stats": stats
        }

@app.get("/xero/check")
def check_xero():
    """Diagnostic endpoint to check Xero API directly"""
    try:
        xero = XeroClient(SupabaseClient())
        
        # First ensure we're authenticated
        if not xero.ensure_authenticated():
            return {"error": "Not authenticated with Xero. Please visit /auth first"}

        # Make a simple request to count invoices
        headers = {
            'Authorization': f"Bearer {xero.token['access_token']}",
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Xero-tenant-id': xero.tenant_id
        }

        # Try different endpoints
        results = {}
        
        # 1. Check basic invoices
        url = f"{xero.api_url}/Invoices"
        logger.info(f"Checking URL: {url}")
        logger.info(f"Using headers: {headers}")
        
        response = requests.get(url, headers=headers)
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response content: {response.text[:1000]}")  # First 1000 chars
        
        if response.status_code != 200:
            return {
                "error": f"Failed to fetch invoices. Status: {response.status_code}",
                "details": response.text
            }

        try:
            data = response.json()
        except ValueError as e:
            logger.error(f"Failed to parse JSON: {str(e)}")
            logger.error(f"Response content: {response.text[:1000]}")
            return {"error": f"Failed to parse response: {str(e)}"}

        results['basic'] = {
            'status': response.status_code,
            'count': len(data.get('Invoices', [])),
            'first_few': data.get('Invoices', [])[:2]  # Show first 2 invoices
        }

        # 2. Check with where clause
        params = {
            'where': 'Type=="ACCREC" OR Type=="ACCPAY"',
            'summaryOnly': 'true'
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            results['with_where'] = {
                'status': response.status_code,
                'count': len(data.get('Invoices', [])),
                'params': params
            }

        # 3. Check each type separately
        for inv_type in ['ACCREC', 'ACCPAY']:
            params = {
                'where': f'Type=="{inv_type}"',
                'summaryOnly': 'true'
            }
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                results[f'type_{inv_type}'] = {
                    'status': response.status_code,
                    'count': len(data.get('Invoices', [])),
                    'params': params
                }

        return {
            "success": True,
            "results": results,
            "headers": {
                k: v for k, v in dict(response.headers).items()
                if k.lower() in ['x-rate-limit-remaining', 'x-rate-limit-reset', 'x-xero-correlation-id']
            }
        }

    except Exception as e:
        logger.error(f"Error checking Xero: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response content: {e.response.text}")
        return {"error": str(e)}

@app.get("/xero/contacts")
def get_contacts():
    """Get contacts from Xero"""
    try:
        xero = XeroClient(SupabaseClient())
        
        # First ensure we're authenticated
        if not xero.ensure_authenticated():
            return {"error": "Not authenticated with Xero. Please visit /auth first"}

        # Get contacts
        contacts = xero.get_contacts()
        
        return {
            "success": True,
            "count": len(contacts),
            "first_few": contacts[:2]  # Show first 2 contacts for debugging
        }

    except Exception as e:
        logger.error(f"Error getting contacts: {str(e)}")
        return {"error": str(e)}

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', '3000'))
        logger.info(f'Starting server on port {port}')
        app.run(host='localhost', port=port, debug=True)
    except Exception as e:
        logger.error(f'Failed to start server: {e}')
