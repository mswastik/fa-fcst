"""
Data models and schemas for the FastAPI application.
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import polars as pl

class FilterState(BaseModel):
    """Model for filter state"""
    location1: str = "Region"
    location2: str = ""
    product1: str = "Franchise"
    product2: str = ""
    forecast_version: Optional[str] = None


class FilterRequest(BaseModel):
    """Request model for filter updates"""
    filter_name: str
    value: str
    filter_state: FilterState


class FilterResponse(BaseModel):
    """Response model for filter updates"""
    products_filt: List[str] = []
    locations_filt: List[str] = []
    products: List[str] = []
    locations: List[str] = []


class UpdateRequest(BaseModel):
    """Request model for dashboard updates"""
    filter_state: FilterState


class UpdateResponse(BaseModel):
    """Response model for dashboard updates"""
    success: bool
    message: str
    filtered_df_json: str = ""
    chart_html: str = ""
    table_html: str = ""


class ActionRequest(BaseModel):
    """Request model for action button clicks"""
    action: str  # segmentation, forecast, validate, change_fc, view
    filter_state: FilterState


class ActionResponse(BaseModel):
    """Response model for action results"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None