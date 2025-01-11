from typing import List, Dict, Optional
from datetime import datetime, timezone
from requests_oauthlib import OAuth2Session
import os
import logging
import requests
import json

# Allow OAuth2 without HTTPS for development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

logger = logging.getLogger(__name__)

# Define scopes directly
SCOPES = [
    'accounting.transactions',
    'accounting.contacts',
    'offline_access'
]

class XeroClient:
    def __init__(self, supabase_client):
        self.client_id = os.getenv('XERO_CLIENT_ID')
        self.client_secret = os.getenv('XERO_CLIENT_SECRET')
        self.redirect_uri = os.getenv('XERO_REDIRECT_URI')
        self.supabase = supabase_client
        self.token = None
        self.tenant_id = None

        # OAuth endpoints
        self.authorization_url = 'https://login.xero.com/identity/connect/authorize'
        self.token_url = 'https://identity.xero.com/connect/token'
        self.connections_url = 'https://api.xero.com/connections'
        self.api_url = 'https://api.xero.com/api.xro/2.0'

        # Initialize OAuth session
        self.oauth = OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=['offline_access', 'accounting.transactions', 'accounting.contacts']
        )

    def ensure_authenticated(self) -> bool:
        """Check if we have valid tokens"""
        try:
            logger.info("Checking authentication")
            logger.debug(f"Current token: {json.dumps(self.token, indent=2) if self.token else None}")
            logger.debug(f"Current tenant_id: {self.tenant_id}")
            
            if not self.token or not self.tenant_id:
                logger.info("No token or tenant_id, trying to load from storage")
                if not self.load_stored_token():
                    logger.error("No stored token found")
                    return False
            
            # Check if token is expired
            if self.token:
                logger.info(f"Using tenant_id: {self.tenant_id}")
                logger.debug(f"Token present: {bool(self.token)}")
                return True
            
            logger.error("No valid token found")
            return False
            
        except Exception as e:
            logger.error(f"Authentication check failed: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            return False

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

    def get_authorization_url(self) -> str:
        """Get the authorization URL for Xero OAuth"""
        try:
            authorization_url, _ = self.oauth.authorization_url(
                self.authorization_url
            )
            return authorization_url
        except Exception as e:
            logger.error(f"Failed to get authorization URL: {str(e)}")
            raise

    def process_callback(self, code: str) -> bool:
        """Process OAuth callback"""
        try:
            logger.info("Processing Xero callback")
            logger.info(f"Using code: {code[:10]}...")
            
            # Exchange code for token
            logger.info("Fetching token...")
            token = self.oauth.fetch_token(
                self.token_url,
                code=code,
                client_secret=self.client_secret,
                include_client_id=True
            )
            logger.info("Successfully obtained token")
            logger.debug(f"Token received: {json.dumps(token, indent=2)}")

            # Get tenant ID
            logger.info("Getting tenant ID...")
            response = requests.get(
                self.connections_url,
                headers={
                    'Authorization': f"Bearer {token['access_token']}",
                    'Content-Type': 'application/json'
                }
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get connections. Status: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return False

            connections = response.json()
            logger.debug(f"Connections response: {json.dumps(connections, indent=2)}")
            
            if not connections:
                logger.error("No Xero tenants connected")
                return False

            tenant_id = connections[0]['tenantId']
            logger.info(f"Got tenant ID: {tenant_id}")

            # Store token and tenant ID
            self.token = token
            self.tenant_id = tenant_id
            
            # Save to database
            logger.info("Storing token...")
            self.store_token()
            
            logger.info("Authentication complete")
            return True

        except Exception as e:
            logger.error(f"Callback failed: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            return False

    def store_token(self):
        """Store token in database"""
        try:
            logger.info(f"Storing tokens for tenant {self.tenant_id}")
            logger.debug(f"Token to store: {json.dumps(self.token, indent=2)}")
            
            # Extract token components
            data = {
                'tenant_id': self.tenant_id,
                'access_token': self.token['access_token'],
                'refresh_token': self.token['refresh_token'],
                'token_type': self.token['token_type'],
                'expires_at': datetime.fromtimestamp(self.token['expires_at'], tz=timezone.utc).isoformat()
            }
            logger.debug(f"Data to insert: {json.dumps(data, indent=2)}")
            
            # Insert new token
            result = self.supabase.client.from_('oauth_tokens')\
                .upsert(data, on_conflict='tenant_id')\
                .execute()
                
            logger.debug(f"Store result: {json.dumps(result.data, indent=2)}")

        except Exception as e:
            logger.error(f"Failed to store token: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.text}")
            raise

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
