import polars as pl
from core.state_manager import get_global_state
from typing import Optional, Dict, Any

# Remove early state access - make it lazy
# state = get_global_state()  # This causes import-time error

# Backward compatibility - expose state properties as module-level variables via lazy access
def get_df():
    return get_global_state().df

def get_filtered_df():
    return get_global_state().filtered_df

def get_filtered_products():
    return get_global_state().filtered_products

def get_filtered_models():
    return get_global_state().filtered_models

# For backward compatibility, create module-level references (lazy)
@property
def df():
    return get_global_state().df

@property
def filtered_df():
    return get_global_state().filtered_df

@property
def filtered_products():
    return get_global_state().filtered_products

@property
def filtered_models():
    return get_global_state().filtered_models

def initialize_data():
    """Initialize the application data"""
    state = get_global_state()
    state.initialize_data()




