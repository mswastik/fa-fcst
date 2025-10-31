"""
Dashboard routes for the FastAPI application.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json
from typing import Dict, Any
import polars as pl
import pandas as pd
import numpy as np

from models.schemas import FilterState
from services.state_service import state_service
from services.data_service import data_service
from services.filter_service import filter_service # Import filter_service
from core.utils import UIUtils, CustomJsonEncoder

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    # Get or create session
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id
    
    session = state_service.get_or_create_session(session_id)
    
    # DO NOT load sample data on startup/access to avoid memory issues with large datasets
    # Only initialize the session without data
    if session.df is None:
        session.df = None
        session.full_df = None
        session.filtered_df = None
    
    # Get initial filter options (these are small and safe to load with caching)
    initial_filter_options = filter_service.get_initial_filter_options()
    initial_location_options = initial_filter_options['initial_location_options']
    initial_product_options = initial_filter_options['initial_product_options']
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "initial_filter_state": FilterState(),
        "initial_location_options": initial_location_options,
        "initial_product_options": initial_product_options
    })

@router.get("/raw_data", response_class=HTMLResponse)
async def raw_data_page(request: Request):
    """Raw data page showing combined sales and forecast data"""
    session_id = request.session.get('session_id')
    if not session_id:
        session_id = f"session_{len(state_service.sessions) + 1}"
        request.session['session_id'] = session_id
    
    session = state_service.get_or_create_session(session_id)
    
    # Only load filtered data that was applied in the root page instead of full dataset
    # to avoid memory issues with large datasets
    df_json = []
    if session.filtered_df is not None and not session.filtered_df.is_empty():
        # Use filtered data from the dashboard if available
        # Convert to dictionaries first
        df_json = session.filtered_df.to_dicts()
    # If no filtered data is available, return empty array to avoid loading full dataset
    # This will show an empty state in the UI but won't cause memory issues
        
    # Return the template with the data as a JSON string
    return templates.TemplateResponse("raw_data.html", {
        "request": request,
        "df_json": json.dumps(df_json, cls=CustomJsonEncoder)
    })
