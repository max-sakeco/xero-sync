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
            if self.is_token_expired():
                logger.info("Token is expired, refreshing...")
                self.refresh_token()

            return True
        except Exception as e:
            logger.error(f"Error ensuring authentication: {str(e)}")
            return False

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

    def get_invoices(self, modified_since: Optional[datetime] = None) -> List[Dict]:
        """Get invoices from Xero"""
        try:
            if not self.ensure_authenticated():
                raise Exception("Not authenticated with Xero")

            all_invoices = []
            page = 1
            page_size = 100  # Xero's maximum page size

            while True:
                headers = {
                    'Authorization': f"Bearer {self.token['access_token']}",
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Xero-tenant-id': self.tenant_id
                }

                if modified_since:
                    headers['If-Modified-Since'] = modified_since.strftime('%Y-%m-%dT%H:%M:%S')

                params = {
                    'page': page,
                    'pageSize': page_size,
                    'summaryOnly': 'false',
                    'includeArchived': 'true',
                    'order': 'UpdatedDateUTC ASC'
                }

                url = f"{self.api_url}/Invoices"
                logger.info(f"Fetching invoices page {page}")
                logger.debug(f"URL: {url}")
                logger.debug(f"Headers: {headers}")
                logger.debug(f"Params: {params}")

                response = requests.get(url, headers=headers, params=params)
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(f"Response content: {response.text[:1000]}")  # First 1000 chars

                if response.status_code == 404:
                    logger.info("No more pages")
                    break

                response.raise_for_status()
                data = response.json()
                invoices = data.get('Invoices', [])

                if not invoices:
                    logger.info("No invoices in response")
                    break

                all_invoices.extend(invoices)
                logger.info(f"Fetched {len(invoices)} invoices from page {page}")

                # Check if we got less than a full page
                if len(invoices) < page_size:
                    logger.info("Last page (incomplete)")
                    break

                page += 1
                logger.info(f"Moving to page {page}")

            logger.info(f"Successfully fetched {len(all_invoices)} invoices in total")
            return all_invoices

        except Exception as e:
            logger.error(f"Error fetching invoices: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            raise

    def get_contacts(self, modified_since: Optional[datetime] = None) -> List[Dict]:
        """Get contacts from Xero"""
        try:
            if not self.ensure_authenticated():
                raise Exception("Not authenticated with Xero")

            all_contacts = []
            page = 1
            page_size = 100  # Xero's maximum page size

            while True:
                headers = {
                    'Authorization': f"Bearer {self.token['access_token']}",
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Xero-tenant-id': self.tenant_id
                }

                if modified_since:
                    headers['If-Modified-Since'] = modified_since.strftime('%Y-%m-%dT%H:%M:%S')

                params = {
                    'page': page,
                    'pageSize': page_size,
                    'includeArchived': 'true',
                    'order': 'UpdatedDateUTC ASC'
                }

                url = f"{self.api_url}/Contacts"
                logger.info(f"Fetching contacts page {page}")
                logger.debug(f"URL: {url}")
                logger.debug(f"Headers: {headers}")
                logger.debug(f"Params: {params}")

                response = requests.get(url, headers=headers, params=params)
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(f"Response content: {response.text[:1000]}")

                if response.status_code == 404:
                    logger.info("No more pages")
                    break

                response.raise_for_status()
                data = response.json()
                contacts = data.get('Contacts', [])

                if not contacts:
                    logger.info("No contacts in response")
                    break

                all_contacts.extend(contacts)
                logger.info(f"Fetched {len(contacts)} contacts from page {page}")

                # Check if we got less than a full page
                if len(contacts) < page_size:
                    logger.info("Last page (incomplete)")
                    break

                page += 1
                logger.info(f"Moving to page {page}")

            logger.info(f"Successfully fetched {len(all_contacts)} contacts in total")
            return all_contacts

        except Exception as e:
            logger.error(f"Error fetching contacts: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            raise
