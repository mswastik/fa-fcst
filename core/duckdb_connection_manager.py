"""
DuckDB Connection Manager with Multi-User Support
Supports multiple concurrent users with separate database connections
"""
import threading
import time
from typing import Dict, Optional, Any
import duckdb


class DuckDBConnectionManager:
    """Connection manager that supports multiple concurrent users"""

    def __init__(self, db_path: Optional[str] = None):
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        # Set default database path if not provided
        if db_path is None:
            db_path = "fcst.duckdb"
        
        self._db_path = db_path
        print(f"Using DuckDB database at: {self._db_path}")

    def create_user_connection(self, user_id: str) -> str:
        """Create a new database connection for a specific user"""
        from time import sleep
        import random
        
        with self._lock:
            if user_id in self._connections:
                # Check if existing connection is still alive
                if self._is_connection_alive(user_id):
                    return user_id

            # Create new connection for user with retry logic for file locking
            max_retries = 5
            retry_delay = 0.1  # Start with 100ms
            
            for attempt in range(max_retries):
                try:
                    connection = duckdb.connect(self._db_path)
                    
                    # Register pandas if available
                    try:
                        import pandas as pd
                        connection.register('pandas', pd.DataFrame())
                    except:
                        pass
                    
                    self._connections[user_id] = {
                        'connection': connection,
                        'created_at': time.time(),
                        'last_used': time.time(),
                        'thread_id': threading.current_thread().ident
                    }

                    return user_id

                except Exception as e:
                    error_msg = str(e)
                    if "The process cannot access the file because it is being used by another process" in error_msg or "IO Error" in error_msg:
                        if attempt < max_retries - 1:  # Don't sleep on the last attempt
                            sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 0.1)  # Exponential backoff + jitter
                            print(f"Database file locked, retrying in {sleep_time:.2f}s... (attempt {attempt + 1}/{max_retries})")
                            sleep(sleep_time)
                            continue
                        else:
                            print(f"Failed to create connection after {max_retries} attempts: {e}")
                            raise
                    else:
                        print(f"Failed to create connection for user {user_id}: {e}")
                        raise

    def get_user_connection(self, user_id: str):
        """Get the database connection for a specific user"""
        with self._lock:
            if user_id not in self._connections:
                raise ValueError(f"No connection found for user {user_id}")

            conn_data = self._connections[user_id]

            # Check if connection is still alive
            if not self._is_connection_alive(user_id):
                # Recreate connection with retry logic for file locking
                max_retries = 3
                retry_delay = 0.1
                
                for attempt in range(max_retries):
                    try:
                        conn_data['connection'] = duckdb.connect(self._db_path)
                        conn_data['created_at'] = time.time()
                        break
                    except Exception as e:
                        error_msg = str(e)
                        if "The process cannot access the file because it is being used by another process" in error_msg or "IO Error" in error_msg:
                            if attempt < max_retries - 1:  # Don't sleep on the last attempt
                                sleep_time = retry_delay * (2 ** attempt)
                                print(f"Database file locked during recreation, retrying in {sleep_time:.2f}s... (attempt {attempt + 1}/{max_retries})")
                                time.sleep(sleep_time)
                                continue
                            else:
                                print(f"Failed to recreate connection after {max_retries} attempts: {e}")
                                raise
                        else:
                            print(f"Failed to recreate connection for user {user_id}: {e}")
                            raise

            # Update last used timestamp
            conn_data['last_used'] = time.time()
            return conn_data['connection']

    def close_user_connection(self, user_id: str):
        """Close the database connection for a specific user"""
        with self._lock:
            if user_id in self._connections:
                try:
                    self._connections[user_id]['connection'].close()
                except Exception:
                    pass  # Ignore errors during cleanup
                del self._connections[user_id]

    def close_all_connections(self):
        """Close all user connections"""
        with self._lock:
            for user_id in list(self._connections.keys()):
                self.close_user_connection(user_id)

    def _is_connection_alive(self, user_id: str) -> bool:
        """Check if a user's connection is still alive"""
        if user_id not in self._connections:
            return False

        try:
            conn = self._connections[user_id]['connection']
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except Exception:
            return False

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about current connections"""
        with self._lock:
            return {
                'total_connections': len(self._connections),
                'connections': {
                    user_id: {
                        'created_at': data['created_at'],
                        'last_used': data['last_used'],
                        'thread_id': data['thread_id']
                    }
                    for user_id, data in self._connections.items()
                }
            }

    def cleanup_old_connections(self, max_age_seconds: int = 3600):
        """Clean up connections that haven't been used recently"""
        with self._lock:
            current_time = time.time()
            to_remove = []

            for user_id, data in self._connections.items():
                if current_time - data['last_used'] > max_age_seconds:
                    to_remove.append(user_id)

            for user_id in to_remove:
                print(f"Cleaning up old connection for user {user_id}")
                self.close_user_connection(user_id)


# Global instance
_connection_manager = None
_manager_lock = threading.Lock()


def get_duckdb_connection_manager() -> DuckDBConnectionManager:
    """Get the global DuckDB connection manager instance"""
    global _connection_manager
    if _connection_manager is None:
        with _manager_lock:
            if _connection_manager is None:
                _connection_manager = DuckDBConnectionManager()
    return _connection_manager