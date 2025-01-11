import os
from supabase import create_client
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        try:
            url: str = os.environ.get('SUPABASE_URL', '')
            key: str = os.environ.get('SUPABASE_KEY', '')
            
            if not url or not key:
                raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
            
            # Initialize without any extra options
            self.client = create_client(
                supabase_url=url,
                supabase_key=key
            )
            
            logger.info("Supabase client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {str(e)}")
            raise

    def store_token(self, token: Dict, tenant_id: str) -> Optional[Dict]:
        """Store Xero token in Supabase"""
        try:
            data = {
                'token': token,
                'tenant_id': tenant_id
            }
            
            result = self.client.table('xero_tokens').upsert(data).execute()
            logger.info("Token stored successfully")
            return result.data if result else None
            
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            raise

    def get_token(self) -> Optional[Dict]:
        """Get latest Xero token from Supabase"""
        try:
            result = self.client.table('xero_tokens').select("*").limit(1).execute()
            if result.data and len(result.data) > 0:
                logger.info("Token retrieved successfully")
                return result.data[0]
            logger.warning("No token found in database")
            return None
            
        except Exception as e:
            logger.error(f"Error getting token: {str(e)}")
            raise
