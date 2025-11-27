"""
State management for the FCST application.
Replaces global variables with proper state management.
"""
from typing import Optional, List, Dict, Any
import polars as pl
from dataclasses import dataclass, field
from core.utils import DataUtils, ErrorHandler
from core.db_service import get_database_service


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

    def is_loading(self, component: Optional[str] = None) -> bool:
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

    def load_sample_data(self, path: Optional[str] = None) -> pl.DataFrame:
        """Load sample data from DuckDB database."""
        try:
            db_service = get_database_service()
            if db_service is None:
                return pl.DataFrame()

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

    def get_filter_options(self, prod: Optional[str] = None, loc: Optional[str] = None) -> Dict[str, Any]:
        """Return filter options for UI dropdowns."""
        prod = prod or (self.products[0] if self.products else None)
        loc = loc or (self.locations[0] if self.locations else None)

        try:
            if self.df is not None and len(self.df) > 0:
                # Check if the requested column exists in the dataframe
                if prod in self.df.columns:
                    products_filt = [x for x in self.df[prod].unique().to_list() if x is not None]
                else:
                    # Try to find the column with a different case or format
                    products_filt = []
                    for col in self.df.columns:
                        if prod is not None and col.lower().replace(' ', '_') == prod.lower().replace(' ', '_'):
                            products_filt = [x for x in self.df[col].unique().to_list() if x is not None]
                            break

                    # Debug: Print available columns to help identify the issue
                    if not products_filt:
                        print(f"Product column '{prod}' not found. Available columns: {self.df.columns}")
                        print(f"Looking for pattern: {prod.lower().replace(' ', '_') if prod else 'None'}")

                if loc in self.df.columns:
                    locations_filt = self.df[loc].unique().to_list()
                else:
                    # Try to find the column with a different case or format
                    locations_filt = []
                    for col in self.df.columns:
                        if loc is not None and col.lower().replace(' ', '_') == loc.lower().replace(' ', '_'):
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
                db_service = get_database_service()
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

    def prepare_chart_data(self, df: pl.DataFrame, chart_type: str = "line") -> Dict[str, Any]:
        """Prepare data specifically for charts"""
        # Since this is a method on DataState, we use 'self'
        self.filtered_df = df

        if chart_type == "column":
            # The internal methods expect the filtered_df to be set, but they also
            # take a DataFrame argument in the original implementation.
            # I will pass the filtered_df to the internal methods for consistency.
            chart_data = self._get_column_chart_data(df)
        else:  # line chart
            chart_data = self._get_line_chart_data(df)

        return chart_data or {}
    def get_chart_data(self, chart_type: str) -> Optional[Dict[str, Any]]:
        """Get data formatted for charts."""
        print(f"DEBUG: state.get_chart_data called with chart_type='{chart_type}'")
        if self.filtered_df is None or len(self.filtered_df) == 0:
            print("DEBUG: No filtered_df or empty dataframe")
            return None

        filtered_df = pl.DataFrame(self.filtered_df)
        print(f"DEBUG: filtered_df has {len(filtered_df)} rows, columns: {list(filtered_df.columns)}")

        # Check for either 'SALES_DATE' (UI format) or 'sales_date' (DB format) and standardize
        date_column = None
        if 'SALES_DATE' in filtered_df.columns:
            date_column = 'SALES_DATE'
        elif 'sales_date' in filtered_df.columns:
            date_column = 'sales_date'
            # Rename to match the expected format in chart methods
            filtered_df = filtered_df.rename({'sales_date': 'SALES_DATE'})

        if date_column:
            # Ensure SALES_DATE is datetime before processing
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
        else:
            print("DEBUG: No date column found (SALES_DATE or sales_date)")
            return None

        chart_data = filtered_df.clone()
        print(f"DEBUG: Chart data prepared, proceeding to {chart_type} chart generation")

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

        # Find the latest date that has actual data (no forecast models have values yet)
        actual_data = chart_data.filter(pl.col('Act Orders Rev').is_not_null())
        if not actual_data.is_empty():
            latest_actual_date = actual_data.select(pl.col('SALES_DATE').max()).item()
        else:
            latest_actual_date = None

        # Group by Year and Month for actuals
        agg_actuals = chart_data.group_by(['Year', 'Month']).sum()['Year', 'Month', 'Act Orders Rev']

        # Group by Year and Month for forecasts - sum all model columns
        model_cols = ['xgb', 'AutoARIMA', 'MSTL', 'AutoCES', 'AutoMFLES']
        available_models = [col for col in model_cols if col in chart_data.columns]

        agg_forecasts = None
        if available_models:
            # Sum all available model forecasts
            agg_base = chart_data.group_by(['Year', 'Month']).agg([
                pl.sum(col).alias(col) for col in available_models
            ])

            # Create a total forecast column by averaging all models
            # (you can change this to sum if preferred)
            agg_forecasts = agg_base.with_columns(
                pl.mean_horizontal([pl.col(c) for c in available_models]).alias('Forecast_Avg')
            ).select(['Year', 'Month', 'Forecast_Avg'])

        # Merge actuals and forecasts
        if agg_forecasts is not None:
            agg_data = agg_actuals.join(agg_forecasts, on=['Year', 'Month'], how='outer')
        else:
            agg_data = agg_actuals.with_columns(pl.lit(None).alias('Forecast_Avg'))

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

        # Create chart_data with original date info for comparison
        original_data_with_dates = chart_data.select(['SALES_DATE', 'Year', 'Month', 'Act Orders Rev']).unique()

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

                # Get the corresponding original date for this year-month combination
                date_matches = original_data_with_dates.filter(
                    (pl.col('Year') == year) & (pl.col('Month') == month)
                )

                # Get actual and forecast values from the aggregated data
                actual_val = None
                forecast_val = None
                if len(month_row) > 0:
                    actual_val = month_row['Act Orders Rev'][0] if 'Act Orders Rev' in month_row.columns else None
                    forecast_val = month_row['Forecast_Avg'][0] if 'Forecast_Avg' in month_row.columns and len(month_row) > 0 else None

                # Get the actual date for comparison (if we have any matching dates in the original data)
                actual_date_for_comparison = None
                if not date_matches.is_empty():
                    actual_date_for_comparison = date_matches['SALES_DATE'].min()  # Use the minimum date in case there are multiple days in the same month

                # Only add actual values if the date is not in the future compared to when forecasts start
                # and actual data exists
                if actual_val is not None and actual_date_for_comparison is not None and (latest_actual_date is None or actual_date_for_comparison <= latest_actual_date):
                    actual_values.append(actual_val)
                else:
                    actual_values.append(None)

                # Only add forecast values if the date is in the future compared to the latest actual date
                # and forecast data exists
                if forecast_val is not None and actual_date_for_comparison is not None and latest_actual_date is not None and actual_date_for_comparison > latest_actual_date:
                    forecast_values.append(forecast_val)
                else:
                    forecast_values.append(None)

            current_color = colors[i % len(colors)]

            # Only add actual series if actual data exists for this year
            if any(av is not None for av in actual_values):
                series_data.append({
                    'name': f'{year} - Actual',
                    'type': 'bar',
                    'data': actual_values,
                    'color': current_color
                })

            # Only add forecast series if forecast data exists for this year
            if any(fv is not None for fv in forecast_values):
                series_data.append({
                    'name': f'{year} - Forecast (Avg)',
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
        """Generate line chart data with all forecast models."""
        chart_data = chart_data.sort('group')
        # Aggregate by date for line chart
        agg_data = chart_data.group_by('group').sum()['group', 'Act Orders Rev']

        # Process all available model forecasts separately
        model_cols = ['xgb', 'AutoARIMA', 'MSTL', 'AutoCES', 'AutoMFLES']
        available_models = [col for col in model_cols if col in chart_data.columns]

        forecast_series = {}
        if available_models:
            # Aggregate forecasts for each model separately
            for model in available_models:
                forecast_agg = chart_data.group_by('group').agg([
                    pl.sum(model).alias(model)
                ]).select(['group', model])

                # Join with agg_data
                agg_data = agg_data.join(forecast_agg, on='group', how='left')
                forecast_series[model] = agg_data[model].to_list()

        x_values = agg_data['group'].to_list()

        return {
            'categories': x_values,
            'values': agg_data['Act Orders Rev'].to_list(),
            'forecast_series': forecast_series  # Dictionary with all model forecasts
        }

# Global state management for FastAPI (using a simple global variable for now)
_global_state: Optional[DataState] = None

def get_global_state() -> DataState:
    """Get the global state instance."""
    global _global_state
    if _global_state is None:
        _global_state = DataState()
    return _global_state

def initialize_global_state() -> None:
    """Initialize the global state instance."""
    global _global_state
    if _global_state is None:
        _global_state = DataState()
    _global_state.initialize_data()


class SessionManager:
    """Service for managing application state sessions in FastAPI"""

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
        from .data_service import apply_filters as core_apply_filters

        result = core_apply_filters(filter_state)
        session = self.get_session(session_id)

        if session and result['filtered_df'] is not None:
            session.df = result['filtered_df'].clone()
            session.full_df = result['filtered_df'].clone()
            session.filtered_df = result['filtered_df'].clone()

        return result


# Global instance of SessionManager
state_service = SessionManager()
