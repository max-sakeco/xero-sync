import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging
import time
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from requests_oauthlib import OAuth2Session

from xero import Xero
from xero.auth import OAuth2Credentials
from xero.constants import XeroScopes
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Allow insecure transport for development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class XeroClient:
    def __init__(self, supabase_client):
        self.client_id = os.getenv('XERO_CLIENT_ID')
        self.client_secret = os.getenv('XERO_CLIENT_SECRET')
        self.redirect_uri = os.getenv('XERO_REDIRECT_URI')
        self.supabase = supabase_client
        self.xero_client = None
        self.credentials = None
        self.tenant_id = None
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.adapter = HTTPAdapter(max_retries=retry_strategy)

    def initialize_auth(self) -> str:
        """Initialize OAuth2 flow and return authorization URL"""
        # Create a session with retry strategy
        session = OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=[
                XeroScopes.ACCOUNTING_TRANSACTIONS,
                XeroScopes.ACCOUNTING_CONTACTS,
                XeroScopes.OFFLINE_ACCESS
            ]
        )
        session.mount("https://", self.adapter)
        session.mount("http://", self.adapter)
        
        self.credentials = OAuth2Credentials(
            client_id=self.client_id,
            client_secret=self.client_secret,
            callback_uri=self.redirect_uri,
            scope=[
                XeroScopes.ACCOUNTING_TRANSACTIONS,
                XeroScopes.ACCOUNTING_CONTACTS,
                XeroScopes.OFFLINE_ACCESS
            ]
        )
        return self.credentials.generate_url()

    def handle_callback(self, auth_response: str) -> None:
        """Handle OAuth callback and store tokens"""
        # Initialize credentials first if not already done
        if not self.credentials:
            self.credentials = OAuth2Credentials(
                client_id=self.client_id,
                client_secret=self.client_secret,
                callback_uri=self.redirect_uri,
                scope=[
                    XeroScopes.ACCOUNTING_TRANSACTIONS,
                    XeroScopes.ACCOUNTING_CONTACTS,
                    XeroScopes.OFFLINE_ACCESS
                ]
            )
        
        try:
            logger.info("Verifying Xero callback")
            # Create a session with retry strategy
            session = OAuth2Session(
                self.client_id,
                redirect_uri=self.redirect_uri,
                scope=[
                    XeroScopes.ACCOUNTING_TRANSACTIONS,
                    XeroScopes.ACCOUNTING_CONTACTS,
                    XeroScopes.OFFLINE_ACCESS
                ]
            )
            session.mount("https://", self.adapter)
            session.mount("http://", self.adapter)
            
            # Use the session to verify the callback
            self.credentials.verify(auth_response)
            
            # Get the tenant ID from the first connected organization
            logger.info("Getting Xero tenants")
            self.xero_client = Xero(self.credentials)
            tenants = self.credentials.get_tenants()
            if not tenants:
                raise Exception("No Xero organizations authorized")
            
            self.tenant_id = tenants[0]['tenantId']
            logger.info(f"Got tenant ID: {self.tenant_id}")
            self._store_tokens()
        except Exception as e:
            logger.error(f"Error handling Xero callback: {str(e)}")
            raise

    def _store_tokens(self) -> None:
        """Store OAuth tokens in Supabase"""
        if not self.tenant_id:
            raise Exception("No tenant ID available")

        token_data = {
            'tenant_id': self.tenant_id,
            'access_token': self.credentials.token['access_token'],
            'refresh_token': self.credentials.token['refresh_token'],
            'token_type': self.credentials.token['token_type'],
            'expires_at': datetime.fromtimestamp(
                self.credentials.token['expires_at'],
                tz=timezone.utc
            ).isoformat()
        }
        
        logger.info(f"Storing tokens for tenant {self.tenant_id}")
        try:
            # First try to update existing token
            result = self.supabase.client.from_('oauth_tokens')\
                .update(token_data)\
                .eq('tenant_id', self.tenant_id)\
                .execute()
            
            # If no rows were updated, insert new token
            if not result.data:
                self.supabase.client.from_('oauth_tokens')\
                    .insert(token_data)\
                    .execute()
        except Exception as e:
            logger.error(f"Error storing tokens: {str(e)}")
            raise

    def _load_tokens(self) -> Optional[Dict]:
        """Load tokens from Supabase"""
        result = self.supabase.client.from_('oauth_tokens')\
            .select('*')\
            .limit(1)\
            .execute()
            
        if result.data:
            return result.data[0]
        return None

    def ensure_authenticated(self) -> bool:
        """Ensure we have valid tokens and refresh if needed"""
        if self.xero_client and not self.credentials.expired():
            return True

        tokens = self._load_tokens()
        if not tokens:
            return False

        self.tenant_id = tokens['tenant_id']
        self.credentials = OAuth2Credentials(
            client_id=self.client_id,
            client_secret=self.client_secret,
            callback_uri=self.redirect_uri,
            token={
                'access_token': tokens['access_token'],
                'refresh_token': tokens['refresh_token'],
                'token_type': tokens['token_type'],
                'expires_at': datetime.fromisoformat(tokens['expires_at']).timestamp()
            }
        )

        if self.credentials.expired():
            self.credentials.refresh()
            self._store_tokens()

        # Set the tenant ID for API calls
        self.credentials.tenant_id = self.tenant_id
        self.xero_client = Xero(self.credentials)
        return True

    def get_invoices(self, modified_since: Optional[datetime] = None) -> List[Dict]:
        """Fetch invoices from Xero with pagination"""
        if not self.ensure_authenticated():
            raise Exception("Not authenticated with Xero")

        # Get the current token from our database
        token = self.supabase.get_token(self.tenant_id)
        if not token:
            raise Exception("No token found in database")

        all_invoices = []
        page = 1
        while True:
            params = {
                'page': page,
                'order': 'UpdatedDateUtc DESC'
            }
            
            # Set modified_since header
            headers = {
                'Authorization': f'Bearer {token["access_token"]}',
                'Xero-tenant-id': self.tenant_id,
                'Accept': 'application/json'
            }
            if modified_since:
                # Format modified_since as RFC 1123 format
                headers['If-Modified-Since'] = modified_since.strftime('%a, %d %b %Y %H:%M:%S GMT')

            try:
                logger.info(f"Fetching invoices page {page} with params: {params} and headers: {headers}")
                logger.info(f"Using tenant ID: {self.tenant_id}")
                
                # Make the request directly
                url = 'https://api.xero.com/api.xro/2.0/Invoices'
                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()
                
                # Parse the response
                data = response.json()
                if not data.get('Invoices'):
                    break
                
                invoices = data['Invoices']
                logger.info(f"Got response with {len(invoices)} invoices")

                # Add tenant_id to each invoice
                for invoice in invoices:
                    invoice['tenant_id'] = self.tenant_id

                all_invoices.extend(invoices)
                page += 1
            except Exception as e:
                logger.error(f"Error fetching invoices: {str(e)}")
                logger.error(f"Error type: {type(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise Exception(f"Error fetching invoices from Xero: {str(e)}")

        return all_invoices
