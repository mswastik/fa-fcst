"""
State management for the FCST application.
Replaces global variables with proper state management.
"""
from typing import Optional, List, Dict, Any
import polars as pl
from dataclasses import dataclass, field
from datetime import datetime
from core.utils import DataUtils, DatabaseUtils, ErrorHandler
from nicegui import app


@dataclass
class DataState:
    """Centralized state management for application data."""

    # Main dataframes
    df: Optional[pl.DataFrame] = None
    full_df: Optional[pl.DataFrame] = None  # Store original full dataset
    filtered_df: Optional[pl.DataFrame] = None

    # Filter state
    filtered_products: List[str] = field(default_factory=list)
    filtered_models: List[str] = field(default_factory=list)

    # UI state
    by_month: bool = False

    # UI state - Loading indicators for different components
    loading_charts: bool = False
    loading_table: bool = False
    loading_data: bool = False
    loading_message_charts: str = ""
    loading_message_table: str = ""
    loading_message_data: str = ""
    
    # Constants
    products: List[str] = field(default_factory=lambda: [
        "Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"
    ])
    locations: List[str] = field(default_factory=lambda: [
        'Area', 'Region', 'Country'
    ])
    levels: List[str] = field(default_factory=lambda: [
        "Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"
    ])
    
    # Hierarchy data
    products_filt: Optional[pl.DataFrame] = None
    locations_filt: Optional[pl.DataFrame] = None
    
    def __post_init__(self):
        """Initialize hierarchy data after object creation."""
        # Don't initialize database connection during module import
        # This will be loaded lazily when needed
        self.products_filt = pl.DataFrame()
        self.locations_filt = pl.DataFrame()
    
    def set_loading_state(self, component: str, loading: bool, message: str = "") -> None:
        """Set loading state for a specific component."""
        if component == 'charts':
            self.loading_charts = loading
            self.loading_message_charts = message
        elif component == 'table':
            self.loading_table = loading
            self.loading_message_table = message
        elif component == 'data':
            self.loading_data = loading
            self.loading_message_data = message
    
    def is_loading(self, component: str = None) -> bool:
        """Check if a component or any component is loading."""
        if component == 'charts':
            return self.loading_charts
        elif component == 'table':
            return self.loading_table
        elif component == 'data':
            return self.loading_data
        else:
            return self.loading_charts or self.loading_table or self.loading_data
    
    def get_loading_message(self, component: str) -> str:
        """Get the loading message for a specific component."""
        if component == 'charts':
            return self.loading_message_charts
        elif component == 'table':
            return self.loading_message_table
        elif component == 'data':
            return self.loading_message_data
        else:
            return ""
    
    def initialize_data(self) -> None:
        """Initialize the application data."""
        # Reset dataframes
        self.df = None
        self.full_df = None
        self.filtered_df = None
    
    def load_sample_data(self, path: str = None) -> pl.DataFrame:
        """Load sample data from DuckDB database."""
        try:
            db_service = DatabaseUtils.get_database_service()
            if db_service is None:
                return None

            # Load sales actuals with joined hierarchy data
            self.df = db_service.get_sales_actuals()

            # Apply standard data preparation
            self.df = DataUtils.prepare_data_for_ui(self.df)

            self.full_df = self.df.clone()  # Store original full dataset
            self.filtered_df = self.df.clone()
            return self.df
        except Exception as e:
            ErrorHandler.handle_data_loading_error(e, "Sample data loading")
            raise ValueError(f"Failed to load data from database: {e}")
    
    def get_filter_options(self, prod: str = None, loc: str = None) -> Dict[str, Any]:
        """Return filter options for UI dropdowns."""
        prod = prod or self.products[0]
        loc = loc or self.locations[0]
        
        try:
            if self.df is not None and len(self.df) > 0:
                # Check if the requested column exists in the dataframe
                if prod in self.df.columns:
                    products_filt = [x for x in self.df[prod].unique().to_list() if x is not None]
                else:
                    # Try to find the column with a different case or format
                    products_filt = []
                    for col in self.df.columns:
                        if col.lower().replace(' ', '_') == prod.lower().replace(' ', '_'):
                            products_filt = [x for x in self.df[col].unique().to_list() if x is not None]
                            break
                    
                    # Debug: Print available columns to help identify the issue
                    if not products_filt:
                        print(f"Product column '{prod}' not found. Available columns: {self.df.columns}")
                        print(f"Looking for pattern: {prod.lower().replace(' ', '_')}")
                
                if loc in self.df.columns:
                    locations_filt = self.df[loc].unique().to_list()
                else:
                    # Try to find the column with a different case or format
                    locations_filt = []
                    for col in self.df.columns:
                        if col.lower().replace(' ', '_') == loc.lower().replace(' ', '_'):
                            locations_filt = self.df[col].unique().to_list()
                            break
                
                return {
                    'products_filt': products_filt,
                    'locations_filt': locations_filt,
                    'products': self.products,
                    'locations': self.locations,
                    'levels': self.levels
                }
            else:
                # Load filter options from database when no data is loaded yet
                db_service = DatabaseUtils.get_database_service()
                if db_service is None:
                    return self._get_default_filter_options()
                
                filter_options = db_service.get_filter_options()
                
                # Map the requested product/location to appropriate database fields
                prod_key = 'catalog_numbers'  # Default
                if prod == 'Franchise':
                    prod_key = 'franchises'
                elif prod == 'IBP Level 5':
                    prod_key = 'ibp_level_5s'
                elif prod == 'IBP Level 6':
                    prod_key = 'ibp_level_6s'
                elif prod == 'CatalogNumber':
                    prod_key = 'catalog_numbers'
                
                loc_key = 'countries'  # Default
                if loc == 'Region':
                    loc_key = 'regions'
                elif loc == 'Area':
                    loc_key = 'areas'
                elif loc == 'Country':
                    loc_key = 'countries'
                
                return {
                    'products_filt': filter_options.get(prod_key, []),
                    'locations_filt': filter_options.get(loc_key, []),
                    'products': self.products,
                    'locations': self.locations,
                    'levels': self.levels
                }
        except Exception as e:
            print(f"Error getting filter options: {e}")
            return self._get_default_filter_options()
    
    def _get_default_filter_options(self) -> Dict[str, Any]:
        """Return default filter options as fallback."""
        return {
            'products_filt': [],
            'locations_filt': [],
            'products': self.products,
            'locations': self.locations,
            'levels': self.levels
        }
    
    def update_filtered_data(self, new_filtered_df: pl.DataFrame) -> None:
        """Update the filtered DataFrame and apply necessary transformations."""
        if new_filtered_df is not None:
            # Apply data preparation for UI before storing
            self.filtered_df = DataUtils.prepare_data_for_ui(new_filtered_df)
            print("DEBUG: Filtered data updated and prepared for UI.")
        else:
            self.filtered_df = None
            print("DEBUG: Filtered data set to None.")

        # Update filtered products and models based on new data
        if new_filtered_df is not None and len(new_filtered_df) > 0:
            try:
                # Extract unique products from filtered data
                if 'CatalogNumber' in new_filtered_df.columns:
                    self.filtered_products = new_filtered_df['CatalogNumber'].unique().to_list()
                else:
                    self.filtered_products = []
                
                # Generate model names (placeholder for real model data)
                self.filtered_models = [f"Model for {product}" for product in self.filtered_products]
            except Exception:
                self.filtered_products = []
                self.filtered_models = []
    
    def get_chart_data(self, chart_type: str) -> Optional[Dict[str, Any]]:
        """Get data formatted for charts."""
        print(f"DEBUG: state.get_chart_data called with chart_type='{chart_type}'")
        if self.filtered_df is None or len(self.filtered_df) == 0:
            print("DEBUG: No filtered_df or empty dataframe")
            return None
        
        filtered_df = pl.DataFrame(self.filtered_df)
        print(f"DEBUG: filtered_df has {len(filtered_df)} rows, columns: {list(filtered_df.columns)}")
        
        # Ensure SALES_DATE is datetime before processing
        if 'SALES_DATE' in filtered_df.columns:
            try:
                # Check if it's already datetime
                if filtered_df['SALES_DATE'].dtype != pl.Datetime:
                    print(f"DEBUG: Converting SALES_DATE from {filtered_df['SALES_DATE'].dtype} to datetime")
                    filtered_df = filtered_df.with_columns(
                        pl.col('SALES_DATE').str.to_datetime().alias('SALES_DATE')
                    )
                else:
                    print("DEBUG: SALES_DATE is already datetime")
            except Exception as e:
                print(f"DEBUG: Error converting SALES_DATE to datetime: {e}")
                # Try alternative conversion
                try:
                    filtered_df = filtered_df.with_columns(
                        pl.col('SALES_DATE').cast(pl.Datetime).alias('SALES_DATE')
                    )
                    print("DEBUG: Alternative datetime conversion successful")
                except Exception as e2:
                    print(f"DEBUG: Alternative datetime conversion failed: {e2}")
                    return None
        
        chart_data = filtered_df.clone()
        print(f"DEBUG: Chart data prepared, proceeding to {chart_type} chart generation")
        
        # Group by month if toggle is active
        if self.by_month:
            chart_data = chart_data.with_columns(
                group=pl.col('SALES_DATE').dt.strftime('%b')
            )
        else:
            chart_data = chart_data.with_columns(
                group=pl.col('SALES_DATE')
            )
        
        # Prepare data based on chart type
        if chart_type == 'column':
            return self._get_column_chart_data(chart_data)
        elif chart_type == 'line':
            return self._get_line_chart_data(chart_data)
        
        return None
    
    def _get_column_chart_data(self, chart_data: pl.DataFrame) -> Dict[str, Any]:
        """Generate column chart data."""
        chart_data = chart_data.with_columns(Month=pl.col('SALES_DATE').dt.strftime('%b'))
        chart_data = chart_data.with_columns(Year=pl.col('SALES_DATE').dt.year())
        
        # Group by Year and Month for actuals
        agg_actuals = chart_data.group_by(['Year', 'Month']).sum()['Year', 'Month', 'Act Orders Rev']
        
        # Group by Year and Month for forecasts (only if NHITS exists)
        agg_forecasts = None
        if 'NHITS' in chart_data.columns:
            agg_forecasts = chart_data.group_by(['Year', 'Month']).sum()['Year', 'Month', 'NHITS']
        
        # Merge actuals and forecasts
        if agg_forecasts is not None:
            agg_data = agg_actuals.join(agg_forecasts, on=['Year', 'Month'], how='outer')
        else:
            agg_data = agg_actuals.with_columns(pl.lit(None).alias('NHITS'))
        
        # Sort by Year and then by Month
        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        agg_data = agg_data.with_columns(
            pl.col('Month').map_elements(
                lambda x: month_order.index(x), 
                return_dtype=pl.Int32
            ).alias('MonthOrder')
        )
        agg_data = agg_data.sort(['Year', 'MonthOrder'])
        
        unique_years = sorted(agg_data['Year'].unique().to_list())
        series_data = []
        colors = ['#5470C6', '#91CC75', '#EE6666', '#73C0DE', 
                 '#3BA272', '#FC8452', '#9A60B4', '#EA7CCC']
        
        for i, year in enumerate(unique_years):
            year_data = agg_data.filter(pl.col('Year') == year)
            
            actual_values = []
            forecast_values = []
            for month in month_order:
                month_row = year_data.filter(pl.col('Month') == month)
                if len(month_row) > 0:
                    actual_values.append(month_row['Act Orders Rev'][0])
                    forecast_values.append(
                        month_row['NHITS'][0] if 'NHITS' in month_row.columns else None
                    )
                else:
                    actual_values.append(None)
                    forecast_values.append(None)
            
            current_color = colors[i % len(colors)]
            
            series_data.append({
                'name': f'{year} - Actual',
                'type': 'bar',
                'data': actual_values,
                'color': current_color
            })
            
            if any(fv is not None for fv in forecast_values):
                series_data.append({
                    'name': f'{year} - Forecast',
                    'type': 'line',
                    'data': forecast_values,
                    'color': current_color,
                    'lineStyle': {'type': 'dashed'}
                })
        
        return {
            'months': month_order,
            'series': series_data
        }
    
    def _get_line_chart_data(self, chart_data: pl.DataFrame) -> Dict[str, Any]:
        """Generate line chart data."""
        chart_data = chart_data.sort('group')
        
        if self.by_month:
            agg_data = chart_data.group_by('group').sum()['Act Orders Rev']
            forecast_values = []
            if 'NHITS' in chart_data.columns:
                agg_data = agg_data.with_columns(
                    chart_data.group_by('group').sum()['NHITS']
                )
                forecast_values = agg_data['NHITS'].to_list()
            x_values = agg_data['group'].to_list()
        else:
            # Aggregate by date for line chart
            agg_data = chart_data.group_by('group').sum()['group', 'Act Orders Rev']
            forecast_values = []
            if 'NHITS' in chart_data.columns:
                agg_data = agg_data.with_columns(
                    chart_data.group_by('group').sum()['NHITS']
                )
                forecast_values = agg_data['NHITS'].to_list()
            x_values = agg_data['group'].to_list()
        
        return {
            'categories': x_values,
            'values': agg_data['Act Orders Rev'].to_list(),
            'forecast_values': forecast_values
        }


# Lazy state management using NiceGUI app.storage for proper multi-session support
def get_global_state() -> DataState:
    """Get the client-specific state instance using app.storage.client (lazy access)."""
    # This can only be called within page builder functions, not during import
    try:
        # Use client storage for per-browser-tab isolation
        if 'fcst_state' not in app.storage.client:
            app.storage.client['fcst_state'] = DataState()
        return app.storage.client['fcst_state']
    except RuntimeError:
        # If called outside of page context, return a temporary global instance
        # This should only happen during import/initialization
        global _temp_state
        if '_temp_state' not in globals():
            _temp_state = DataState()
        return _temp_state

def initialize_global_state() -> None:
    """Initialize the client-specific session state (only works within page context)."""
    try:
        if 'fcst_state' not in app.storage.client:
            app.storage.client['fcst_state'] = DataState()
        app.storage.client['fcst_state'].initialize_data()
    except RuntimeError:
        # If called outside of page context, initialize temp state
        global _temp_state
        if '_temp_state' not in globals():
            _temp_state = DataState()
        _temp_state.initialize_data()
