"""
Authentication service for Microsoft OAuth2 SSO.
NOTE: This service is currently not integrated into the main FastAPI application.
It is not currently integrated into the main FastAPI application.
"""
import os
from fastapi import Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth


class AuthService:
    """Handles Microsoft OAuth2 authentication"""
    
    # NOTE: This service is not used in the current FastAPI application.

    def __init__(self, app_instance=None):
        self.oauth = OAuth()
        # Microsoft OAuth2 configuration
        self.client_id = os.getenv('MICROSOFT_CLIENT_ID', 'your-client-id')
        self.client_secret = os.getenv('MICROSOFT_CLIENT_SECRET', 'your-client-secret')
        self.tenant_id = os.getenv('MICROSOFT_TENANT_ID', '4e9dbbfb-394a-4583-8810-53f81f819e3b')  # 'common' for multi-tenant

        # Register Microsoft OAuth
        self.oauth.register(
            name='microsoft',
            client_id=self.client_id,
            client_secret=self.client_secret,
            authorize_url=f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize',
            access_token_url=f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token',
            client_kwargs={
                'scope': 'openid profile email',
            },
        )

    def is_authenticated(self, request: Request) -> bool:
        """Check if user is authenticated (Placeholder)"""
        return False

    def get_user_info(self):
        """Get current user information (Placeholder)"""
        return {}

    def logout(self):
        """Clear user session (Placeholder)"""
        pass

    async def initiate_login(self, request: Request):
        """Initiate Microsoft OAuth2 login flow"""
        redirect_uri = str(request.url_for('auth_callback'))
        return await self.oauth.microsoft.authorize_redirect(request, redirect_uri)

    async def handle_callback(self, request: Request):
        """Handle OAuth2 callback and process user info"""
        try:
            token = await self.oauth.microsoft.authorize_access_token(request)
            user_info_response = await self.oauth.microsoft.get(
                'https://graph.microsoft.com/v1.0/me',
                token=token
            )
            user_info = user_info_response.json()

            # NOTE: Session management for FastAPI needs to be implemented here.
            return True, user_info
        except Exception as e:
            print(f"OAuth callback error: {e}")
            return False, str(e)


# Global auth service instance
auth_service = AuthService()
