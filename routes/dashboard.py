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

from models.schemas import FilterState
from services.state_service import state_service
from services.data_service import data_service
from services.filter_service import filter_service # Import filter_service
from core.utils import UIUtils

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
    
    session = state_service.get_session(session_id)
    
    # For now, return a basic template - we'll implement the full functionality later
    return templates.TemplateResponse("raw_data.html", {
        "request": request
    })
