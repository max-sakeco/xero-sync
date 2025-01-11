import os
from supabase import create_client, Client
import logging

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL')
        self.key = os.environ.get('SUPABASE_KEY')
        self.client = create_client(self.url, self.key)

    def store_token(self, token: dict, tenant_id: str):
        """Store Xero token in Supabase"""
        try:
            data = {
                'token': token,
                'tenant_id': tenant_id
            }
            
            result = self.client.table('xero_tokens').upsert(data).execute()
            logger.info("Token stored successfully")
            return result
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            raise

    def get_token(self):
        """Get latest Xero token from Supabase"""
        try:
            result = self.client.table('xero_tokens').select("*").limit(1).execute()
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting token: {str(e)}")
            raise
