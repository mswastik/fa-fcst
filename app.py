from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import json
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

# Import existing modules
from core.state_manager import DataState, get_global_state
from core.data_service import apply_filters, create_models_action, change_fc_action
from core.utils import DataUtils, ErrorHandler
#from ui.charts import render_column_chart, render_line_chart
import polars as pl

app = FastAPI(title="ML Integration Forecast Dashboard", version="1.0.0")

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Add session middleware for state management
app.add_middleware(SessionMiddleware, secret_key="my_secret_key")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Import routes
from routes import dashboard, api, api_raw_data

# Include routes
app.include_router(dashboard.router)
app.include_router(api.router)
app.include_router(api_raw_data.router)

# Add a route for the agent page
@app.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request):
    return templates.TemplateResponse("agent.html", {"request": request})

@app.get("/raw_data", response_class=HTMLResponse)
async def raw_data_page(request: Request):
    """Raw data page"""
    from core.db_service import get_database_service
    db_service = get_database_service()
    filter_options = db_service.get_filter_options(user_id="system")
    forecast_versions = db_service.get_forecast_versions(user_id="system")

    initial_location_options = ["Region", "Country", "Area"]
    initial_product_options = ["Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"]

    context = {
        "request": request,
        "initial_location_options": initial_location_options,
        "initial_product_options": initial_product_options,
        "location_options": filter_options.get('regions', []),
        "product_options": filter_options.get('franchises', []),
        "all_filter_options": filter_options,  # Add all filter options for complete functionality
        "forecast_versions": forecast_versions,
    }
    return templates.TemplateResponse("raw_data.html", context)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root route that serves the main dashboard"""
    return templates.TemplateResponse("dashboard.html", {"request": request})

# Initialize the application data on startup
@app.on_event("startup")
async def startup_event():
    # Initialize global state here if needed
    # Don't connect to database on startup to avoid blocking
    pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)