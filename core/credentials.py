"""
Secure credentials management for the FCST application.
Handles loading credentials from secure configuration files.
"""
import os
import json
from typing import Dict, Optional


class CredentialsManager:
    """Manages secure credential loading and access."""
    
    _instance = None
    _credentials = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CredentialsManager, cls).__new__(cls)
            cls._instance._load_credentials()
        return cls._instance
    
    def _load_credentials(self):
        """Load credentials from secure configuration file."""
        try:
            # Look for credentials file in config directory
            config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
            credentials_file = os.path.join(config_dir, 'credentials.json')
            
            if os.path.exists(credentials_file):
                with open(credentials_file, 'r') as f:
                    self._credentials = json.load(f)
            else:
                # Initialize with empty credentials
                self._credentials = {
                    'database': {
                        'server': '',
                        'database_name': '',
                        'username': '',
                        'password': ''
                    }
                }
        except Exception as e:
            print(f"Warning: Could not load credentials file: {e}")
            self._credentials = {
                'database': {
                    'server': '',
                    'database_name': '',
                    'username': '',
                    'password': ''
                }
            }
    
    def get_database_credentials(self) -> Dict[str, str]:
        """Get database credentials."""
        if not self._credentials or 'database' not in self._credentials:
            return {
                'server': os.getenv('SERVER_NAME', ''),
                'database_name': os.getenv('DATABASE_NAME', ''),
                'username': os.getenv('DB_USERNAME', ''),
                'password': os.getenv('DB_PASSWORD', '')
            }
        
        db_creds = self._credentials.get('database', {})
        return {
            'server': db_creds.get('server') or os.getenv('SERVER_NAME', ''),
            'database_name': db_creds.get('database_name') or os.getenv('DATABASE_NAME', ''),
            'username': db_creds.get('username') or os.getenv('DB_USERNAME', ''),
            'password': db_creds.get('password') or os.getenv('DB_PASSWORD', '')
        }
    
    def save_database_credentials(self, server: str, database_name: str, username: str, password: str):
        """Save database credentials to configuration file."""
        try:
            self._credentials['database'] = {
                'server': server,
                'database_name': database_name,
                'username': username,
                'password': password
            }
            
            # Save to credentials file
            config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
            credentials_file = os.path.join(config_dir, 'credentials.json')
            
            with open(credentials_file, 'w') as f:
                json.dump(self._credentials, f, indent=2)
                
        except Exception as e:
            print(f"Error saving credentials: {e}")
