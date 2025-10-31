"""
Authentication service for Microsoft OAuth2 SSO
"""
import os
#from typing import Optional
from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from authlib.integrations.starlette_client import OAuth
from nicegui import app, ui


class AuthService:
    """Handles Microsoft OAuth2 authentication"""

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
        """Check if user is authenticated"""
        return app.storage.user.get('authenticated', False)

    def get_user_info(self):
        """Get current user information"""
        return app.storage.user

    def logout(self):
        """Clear user session"""
        app.storage.user.clear()

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

            # Store user information in session
            app.storage.user.update({
                'authenticated': True,
                'username': user_info.get('displayName', user_info.get('userPrincipalName', 'Unknown')),
                'email': user_info.get('userPrincipalName', user_info.get('mail')),
                'microsoft_id': user_info.get('id'),
                'token': token
            })

            return True, user_info
        except Exception as e:
            print(f"OAuth callback error: {e}")
            return False, str(e)


# Global auth service instance
auth_service = AuthService()


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to protect routes with authentication"""

    def __init__(self, app, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or ['/login', '/auth', '/favicon.ico']

    async def dispatch(self, request, call_next):
        # Allow access to excluded paths
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # Allow NiceGUI internal routes
        if request.url.path.startswith('/_nicegui'):
            return await call_next(request)

        # Check authentication
        if not auth_service.is_authenticated(request):
            return RedirectResponse(f'/login?redirect_to={request.url.path}')

        return await call_next(request)


# Authentication pages
@ui.page('/login')
def login_page(redirect_to: str = '/'):
    """Login page with Microsoft OAuth2"""
    def initiate_microsoft_login():
        """Handle Microsoft login button click"""
        print("Login button clicked - initiating OAuth flow")
        try:
            # Check if environment variables are set
            client_id = os.getenv('MICROSOFT_CLIENT_ID')
            tenant_id = os.getenv('MICROSOFT_TENANT_ID')
            client_secret = os.getenv('MICROSOFT_CLIENT_SECRET')

            print(f"Client ID set: {bool(client_id)}")
            print(f"Tenant ID set: {bool(tenant_id)}")
            print(f"Client Secret set: {bool(client_secret)}")

            if not client_id or client_id == 'your-client-id':
                ui.notify('Microsoft OAuth not configured. Please set MICROSOFT_CLIENT_ID environment variable.', type='negative')
                return

            # Navigate to auth endpoint
            ui.navigate.to('/auth/login')
        except Exception as e:
            print(f"Error in login initiation: {e}")
            ui.notify(f'Login initiation failed: {str(e)}', type='negative')

    if auth_service.is_authenticated(None):
        ui.navigate.to(redirect_to)
        return

    with ui.card().classes('absolute-center'):
        ui.label('Company Forecasting App').classes('text-2xl text-center mb-4')
        ui.label('Please sign in with your Microsoft account').classes('text-center mb-6')

        ui.button(
            'Sign in with Microsoft',
            on_click=initiate_microsoft_login,
            icon='login'
        ).classes('w-full').props('color=primary')
        ui.label('SSO Login is yet implemented as it requires app registration in Azure').classes('text text-red-600 mt-4 text-center')


@ui.page('/logout')
def logout_page():
    """Logout page"""
    auth_service.logout()
    ui.navigate.to('/login')
