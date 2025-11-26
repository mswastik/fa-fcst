"""
Database models for the FastAPI application.
"""
from typing import Optional
from datetime import datetime

# This is a simplified version, as most of our DB interactions will use the existing core modules
class ForecastResult:
    """Model for forecast results"""
    def __init__(self, 
                 item_skey: int,
                 location_skey: int, 
                 forecast_date: datetime,
                 forecast_value: float,
                 model_type: str = "MLForecast"):
        self.item_skey = item_skey
        self.location_skey = location_skey
        self.forecast_date = forecast_date
        self.forecast_value = forecast_value
        self.model_type = model_type


class SalesData:
    """Model for sales data"""
    def __init__(self,
                 item_skey: int,
                 location_skey: int,
                 sales_date: datetime,
                 act_orders_rev: float,
                 forecast_value: Optional[float] = None):
        self.item_skey = item_skey
        self.location_skey = location_skey
        self.sales_date = sales_date
        self.act_orders_rev = act_orders_rev
        self.forecast_value = forecast_value