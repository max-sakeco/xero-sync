from typing import List, Dict, Optional
from datetime import datetime, timezone
from requests_oauthlib import OAuth2Session
import os
import logging
import requests
import json
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

class XeroClient:
    def __init__(self, supabase: SupabaseClient):
        self.client_id = os.environ.get('XERO_CLIENT_ID')
        self.client_secret = os.environ.get('XERO_CLIENT_SECRET')
        self.redirect_uri = os.environ.get('XERO_REDIRECT_URI')
        self.scope = ['offline_access', 'accounting.transactions', 'accounting.contacts']
        self.token = None
        self.tenant_id = None
        self.supabase = supabase
        self.api_url = 'https://api.xero.com/api.xro/2.0'
        
        # Get base URL from environment or default to localhost
        self.base_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:3000')
        
        # Ensure redirect URI is properly set
        if not self.redirect_uri:
            self.redirect_uri = f"{self.base_url}/callback"

        # Try to get existing token
        self.ensure_authenticated()

    def get_oauth_session(self):
        """Get OAuth2 session without proxy"""
        return OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=self.scope
        )

    def get_authorization_url(self):
        """Get authorization URL for Xero OAuth2"""
        try:
            oauth = self.get_oauth_session()
            authorization_url, state = oauth.authorization_url(
                'https://login.xero.com/identity/connect/authorize'
            )
            logger.info(f"Generated authorization URL: {authorization_url}")
            return authorization_url
        except Exception as e:
            logger.error(f"Error getting authorization URL: {str(e)}")
            raise

    def callback(self, callback_url: str):
        """Handle OAuth2 callback from Xero"""
        try:
            oauth = self.get_oauth_session()
            token = oauth.fetch_token(
                'https://identity.xero.com/connect/token',
                authorization_response=callback_url,
                client_secret=self.client_secret
            )
            
            # Get tenant ID
            tenant_id = self.get_tenant_id(token)
            
            # Store token in database
            self.supabase.store_token(token, tenant_id)
            
            self.token = token
            self.tenant_id = tenant_id
            
            logger.info("Successfully processed callback and stored token")
            return token
        except Exception as e:
            logger.error(f"Error in callback: {str(e)}")
            raise

    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid token"""
        try:
            # Try to get token from database
            token_data = self.supabase.get_token()
            if not token_data:
                logger.warning("No token found in database")
                return False

            self.token = token_data['token']
            self.tenant_id = token_data['tenant_id']
            
            # Check if token is expired
            expires_at = self.token.get('expires_at')
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                if expires_at <= now:
                    logger.info("Token is expired, refreshing...")
                    self.refresh_token()
            
            logger.info("Successfully authenticated with existing token")
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring authentication: {str(e)}")
            return False

    def refresh_token(self):
        """Refresh the Xero token"""
        try:
            oauth = OAuth2Session(self.client_id)
            
            extra = {
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }

            self.token = oauth.refresh_token(
                'https://identity.xero.com/connect/token',
                refresh_token=self.token['refresh_token'],
                **extra
            )
            
            # Store refreshed token
            self.supabase.store_token(self.token, self.tenant_id)
            logger.info("Token refreshed successfully")
            
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            raise

    def get_tenant_id(self, token):
        """Get Xero tenant ID"""
        try:
            response = requests.get(
                'https://api.xero.com/connections',
                headers={
                    'Authorization': f"Bearer {token['access_token']}",
                    'Content-Type': 'application/json'
                }
            )
            response.raise_for_status()
            connections = response.json()
            
            if not connections:
                raise Exception("No Xero tenants connected")
                
            return connections[0]['tenantId']
        except Exception as e:
            logger.error(f"Error getting tenant ID: {str(e)}")
            raise

    def load_stored_token(self) -> bool:
        """Load stored token from database"""
        try:
            logger.info("Attempting to load stored token")
            result = self.supabase.client.from_('oauth_tokens')\
                .select('*')\
                .order('updated_at', desc=True)\
                .limit(1)\
                .execute()

            logger.debug(f"Load result: {json.dumps(result.data, indent=2)}")

            if result.data:
                data = result.data[0]
                # Reconstruct token dictionary
                self.token = {
                    'access_token': data['access_token'],
                    'refresh_token': data['refresh_token'],
                    'token_type': data['token_type'],
                    'expires_at': datetime.fromisoformat(data['expires_at']).timestamp()
                }
                self.tenant_id = data['tenant_id']
                logger.info(f"Loaded stored token for tenant: {self.tenant_id}")
                logger.debug(f"Reconstructed token: {json.dumps(self.token, indent=2)}")
                return True
            
            logger.error("No token found in database")
            return False
            
        except Exception as e:
            logger.error(f"Error loading stored token: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            return False

    def get_invoices(self, offset=0, limit=50):
        """Get invoices from Xero with pagination"""
        if not self.ensure_authenticated():
            raise Exception("Not authenticated with Xero. Please visit /auth first")
        
        try:
            # Build URL with pagination parameters
            url = f"{self.api_url}/Invoices"
            params = {
                'page': offset // limit + 1,  # Convert offset to page number
                'pageSize': limit,
                'order': 'UpdatedDateUTC DESC'
            }
            
            response = requests.get(
                url,
                params=params,
                headers={
                    'Authorization': f"Bearer {self.token['access_token']}",
                    'Xero-tenant-id': self.tenant_id,
                    'Accept': 'application/json'
                }
            )
            response.raise_for_status()
            
            # Extract invoices from response
            data = response.json()
            return data.get('Invoices', [])
            
        except Exception as e:
            logger.error(f"Error getting invoices: {str(e)}")
            raise

    def get_contacts(self, modified_since: Optional[datetime] = None) -> List[Dict]:
        """Get contacts from Xero"""
        if not self.ensure_authenticated():
            raise Exception("Not authenticated with Xero. Please visit /auth first")
            
        try:
            response = requests.get(
                f"{self.api_url}/Contacts",
                headers={
                    'Authorization': f"Bearer {self.token['access_token']}",
                    'Xero-tenant-id': self.tenant_id,
                    'Accept': 'application/json'
                }
            )
            response.raise_for_status()
            return response.json().get('Contacts', [])
            
        except Exception as e:
            logger.error(f"Error getting contacts: {str(e)}")
            raise

    def sync_all(self, batch_size=50):
        """Sync all data from Xero in batches"""
        try:
            if not self.ensure_authenticated():
                raise Exception("Not authenticated with Xero")
            
            total_processed = 0
            batch_start = 0
            results = {
                "invoices": 0,
                "items": 0,
                "batches": 0
            }
            
            while True:
                invoices = self.get_invoices(offset=batch_start, limit=batch_size)
                if not invoices:
                    break
                
                for idx, invoice in enumerate(invoices):
                    self.process_invoice(invoice)
                    logger.info(f"Processing invoice {batch_start + idx + 1}/{total_processed + len(invoices)}")
                
                total_processed += len(invoices)
                batch_start += batch_size
                results["batches"] += 1
                results["invoices"] = total_processed
                
                if len(invoices) < batch_size:
                    break
            
            return results
            
        except Exception as e:
            logger.error(f"Error in sync_all: {str(e)}")
            raise
