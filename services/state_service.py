"""
State management service for the FastAPI application.
"""
from typing import Dict, Optional, Any
from datetime import datetime
import polars as pl
from core.state_manager import DataState
from core.utils import DataUtils
import json
import uuid

class StateService:
    """Service for managing application state in FastAPI"""
    
    def __init__(self):
        # We'll store user sessions in memory for now, but this could be adapted for Redis or database storage
        self.sessions: Dict[str, DataState] = {}
    
    def get_or_create_session(self, session_id: str) -> DataState:
        """Get existing session or create a new one"""
        if session_id not in self.sessions:
            self.sessions[session_id] = DataState()
            self.sessions[session_id].initialize_data()
        return self.sessions[session_id]
    
    def initialize_session(self, session_id: str) -> DataState:
        """Initialize a new session with default state"""
        self.sessions[session_id] = DataState()
        self.sessions[session_id].initialize_data()
        return self.sessions[session_id]
    
    def get_session(self, session_id: str) -> Optional[DataState]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def update_session_data(self, session_id: str, df: pl.DataFrame) -> None:
        """Update session with new data"""
        session = self.get_session(session_id)
        if session:
            session.df = df
            session.full_df = df.clone()
            session.filtered_df = df.clone()
    
    def load_sample_data(self, session_id: str) -> pl.DataFrame:
        """Load sample data for a session"""
        session = self.get_session(session_id)
        if session:
            return session.load_sample_data()
        return pl.DataFrame()
    
    def apply_filters(self, session_id: str, filter_state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply filters to session data"""
        # Import the existing apply_filters function
        from core.data_service import apply_filters as core_apply_filters
        
        result = core_apply_filters(filter_state)
        session = self.get_session(session_id)
        
        if session and result['filtered_df'] is not None:
            session.df = result['filtered_df'].clone()
            session.full_df = result['filtered_df'].clone()
            session.filtered_df = result['filtered_df'].clone()
        
        return result


# Global instance
state_service = StateService()