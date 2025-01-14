import os
from supabase import create_client
import logging
from typing import Optional, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class SupabaseClient:
    def __init__(self):
        try:
            url: str = os.environ.get('SUPABASE_URL', '')
            key: str = os.environ.get('SUPABASE_KEY', '')
            
            if not url or not key:
                raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
            
            self.client = create_client(
                supabase_url=url,
                supabase_key=key
            )
            
            logger.info("Supabase client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {str(e)}")
            raise

    def _format_timestamp(self, timestamp) -> str:
        """Convert timestamp to ISO format"""
        if isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return dt.isoformat()
        return timestamp

    def store_token(self, token: Dict, tenant_id: str) -> Optional[Dict]:
        """Store Xero token in Supabase"""
        try:
            # Convert expires_at to proper timestamp format
            expires_at = self._format_timestamp(token.get('expires_at'))
            
            data = {
                'tenant_id': tenant_id,
                'access_token': token.get('access_token'),
                'refresh_token': token.get('refresh_token'),
                'token_type': token.get('token_type', 'Bearer'),
                'expires_at': expires_at,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            logger.info(f"Preparing to store token data with expires_at: {expires_at}")
            # Use id=1 for upsert since we only have one token
            result = self.client.table('tokens').update(data).eq('id', 1).execute()
            logger.info("Token stored successfully")
            return result.data if result else None
            
        except Exception as e:
            logger.error(f"Error storing token: {str(e)}")
            raise

    def get_token(self) -> Optional[Dict]:
        """Get latest Xero token from Supabase"""
        try:
            result = self.client.table('tokens')\
                .select("access_token,refresh_token,token_type,expires_at,tenant_id")\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data and len(result.data) > 0:
                token_data = result.data[0]
                # Reconstruct token format
                token = {
                    'access_token': token_data.get('access_token'),
                    'refresh_token': token_data.get('refresh_token'),
                    'token_type': token_data.get('token_type'),
                    'expires_at': token_data.get('expires_at')
                }
                logger.info("Token retrieved successfully")
                return {
                    'token': token,
                    'tenant_id': token_data.get('tenant_id')
                }
            logger.warning("No token found in database")
            return None
            
        except Exception as e:
            logger.error(f"Error getting token: {str(e)}")
            raise
