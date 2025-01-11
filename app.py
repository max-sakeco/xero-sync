import os
from flask import Flask, request, redirect, session, url_for
from datetime import datetime, timezone
import logging
from xero_client import XeroClient
from supabase_client import SupabaseClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app with secret key
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-here')

# Get environment
is_production = os.environ.get('RENDER', False)

@app.route('/')
def index():
    """Root endpoint"""
    try:
        # Test Supabase connection
        supabase = SupabaseClient()
        # Test Xero client initialization
        xero = XeroClient(supabase)
        return {
            "status": "ok", 
            "environment": "production" if is_production else "development",
            "services": "healthy"
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

@app.route('/auth')
def auth():
    """Start Xero OAuth flow"""
    try:
        logger.info("Starting auth flow")
        xero = XeroClient(SupabaseClient())
        authorization_url = xero.get_authorization_url()
        logger.info(f"Generated auth URL: {authorization_url}")
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Auth failed: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

@app.route('/callback')
def callback():
    """Handle OAuth callback"""
    try:
        logger.info("Handling callback")
        xero = XeroClient(SupabaseClient())
        auth_response = xero.callback(request.url)
        logger.info("Callback processed successfully")
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Callback failed: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

@app.route('/status')
def status():
    """Get sync status"""
    try:
        supabase = SupabaseClient()
        
        # Get counts from tables
        invoices_count = supabase.client.table('invoices_new').select('count', count='exact').execute()
        items_count = supabase.client.table('invoice_items_new').select('count', count='exact').execute()
        
        # Get last sync time
        last_sync = supabase.client.table('tokens').select('updated_at').limit(1).execute()
        
        return {
            "status": "ok",
            "last_sync": last_sync.data[0]['updated_at'] if last_sync.data else None,
            "counts": {
                "invoices": invoices_count.count,
                "invoice_items": items_count.count
            },
            "environment": "production" if os.environ.get('RENDER', False) else "development"
        }
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

@app.route('/sync')
def sync():
    """Sync data from Xero"""
    try:
        xero = XeroClient(SupabaseClient())
        
        # Start sync with batch size
        result = xero.sync_all(batch_size=50)  # Process in smaller batches
        
        return {
            "status": "success",
            "message": "Sync completed successfully",
            "details": result
        }
    except Exception as e:
        logger.error(f"Error in sync: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

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

# Add health check endpoint for Render
@app.route('/health')
def health():
    return {"status": "healthy"}

# Production server configuration
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    if is_production:
        # In production, let Gunicorn handle the serving
        app.run(host="0.0.0.0", port=port)
    else:
        # In development, use Flask's built-in server with debug mode
        app.run(host="0.0.0.0", port=port, debug=True)
