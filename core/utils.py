"""
Common utilities and constants for the FCST application.
Centralizes frequently used patterns to reduce code duplication.
"""

import os
from typing import Dict, Any, Optional
import polars as pl
from nicegui import ui
from datetime import datetime
from json import JSONEncoder


# Column mapping constants
COLUMN_MAPPING = {
    'act_orders_rev': 'Act Orders Rev',
    'fcst_stat_prelim_rev': 'Fcst Stat Prelim Rev',
    'fcst_stat_final_rev': 'Fcst Stat Final Rev',
    'l2_stat_final_rev': 'L2 Stat Final Rev',
    'fcst_df_final_rev': 'Fcst DF Final Rev',
    'l2_df_final_rev': 'L2 DF Final Rev',
    'sales_date': 'SALES_DATE',
    'catalog_number': 'CatalogNumber',
    'region': 'Region',
    'country': 'Country',
    'area': 'Area',
    'business_unit': 'Business Unit',
    'franchise': 'Franchise',
    'ibp_level_5': 'IBP Level 5',
    'ibp_level_6': 'IBP Level 6'
}

NUMERIC_COLUMNS = [
    'Act Orders Rev', 'Fcst Stat Prelim Rev', 'Fcst Stat Final Rev',
    'L2 Stat Final Rev', 'Fcst DF Final Rev', 'L2 DF Final Rev'
]

class DataUtils:
    """Utility functions for data manipulation."""

    @staticmethod
    def apply_column_mapping(df: pl.DataFrame) -> pl.DataFrame:
        """Apply standard column name mapping to dataframe."""
        if df is None:
            return None

        rename_dict = {}
        for db_col, ui_col in COLUMN_MAPPING.items():
            if db_col in df.columns:
                rename_dict[db_col] = ui_col

        if rename_dict:
            df = df.rename(rename_dict)

        return df

    @staticmethod
    def cast_numeric_columns(df: pl.DataFrame) -> pl.DataFrame:
        """Cast numeric columns to Float32."""
        if df is None:
            return None

        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float32))

        return df

    @staticmethod
    def prepare_data_for_ui(df: pl.DataFrame) -> pl.DataFrame:
        """Apply all standard data preparation steps."""
        if df is None:
            return None
        # Hard-coded conversion for SALES_DATE column
        if 'sales_date' in df.columns and df['sales_date'].dtype == pl.Utf8:
            try:
                # First try timezone-aware ISO format: "2022-09-01T00:00:00 +00:00"
                df = df.with_columns(
                    pl.col('sales_date').str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S %z", strict=False)
                    .dt.convert_time_zone("UTC")
                    .dt.replace_time_zone(None)
                )
            except Exception:
                try:
                    # Try timezone-aware ISO format without space: "2022-09-01T00:00:00+00:00"
                    df = df.with_columns(
                        pl.col('sales_date').str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z", strict=False)
                        .dt.convert_time_zone("UTC")
                        .dt.replace_time_zone(None)
                    )
                except Exception:
                    try:
                        # Try standard datetime format: "2022-09-01 00:00:00"
                        df = df.with_columns(
                            pl.col('sales_date').str.strptime(pl.Datetime, "%Y-%m-%d %H:%M:%S", strict=False)
                        )
                    except Exception:
                        try:
                            # Try ISO format without timezone: "2022-09-01T00:00:00"
                            df = df.with_columns(
                                pl.col('sales_date').str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S", strict=False)
                            )
                        except Exception as e:
                            print(f"Warning: Could not parse 'sales_date' column as datetime. Error: {e}")
                            # If all parsing fails, convert to string to avoid further errors
                            df = df.with_columns(pl.col('sales_date').cast(pl.Utf8))
        
        # Ensure 'sales_date' is a datetime type for further operations
        if 'sales_date' in df.columns and df['sales_date'].dtype != pl.Datetime:
            try:
                df = df.with_columns(pl.col('sales_date').cast(pl.Datetime))
            except Exception as e:
                print(f"Warning: Could not cast 'sales_date' to Datetime after parsing attempts. Error: {e}")
                # If casting fails, convert to string to avoid further errors
                df = df.with_columns(pl.col('sales_date').cast(pl.Utf8))

        # Rename 'sales_date' to 'SALES_DATE' for consistency with chart components
        if 'sales_date' in df.columns:
            df = df.rename({'sales_date': 'SALES_DATE'})

        # Rename 'act_orders_rev' to 'Act Orders Rev' for consistency with chart components
        if 'act_orders_rev' in df.columns:
            df = df.rename({'act_orders_rev': 'Act Orders Rev'})

        # Rename 'country' to 'Country' for consistency with chart components
        if 'country' in df.columns:
            df = df.rename({'country': 'Country'})

        df = DataUtils.apply_column_mapping(df)
        df = DataUtils.cast_numeric_columns(df)
        return df


class UIUtils:
    """Utility class for common UI operations."""

    @staticmethod
    def show_loading_indicator(container, message: str = "Loading..."):
        """Show loading indicator in container."""
        container.clear()
        with container:
            with ui.row().classes('w-full h-full justify-center items-center'):
                ui.spinner(size='lg')
                ui.label(message).classes('ml-2 text-gray-600')

    @staticmethod
    def show_error_message(message: str, type: str = 'negative'):
        """Show error notification."""
        ui.notify(message, type=type)

    @staticmethod
    def show_success_message(message: str):
        """Show success notification."""
        ui.notify(message, type='positive')

    @staticmethod
    def show_info_message(message: str):
        """Show info notification."""
        ui.notify(message, type='info')

    @staticmethod
    def create_loading_notification(timeout=None):
        """Create a loading notification."""
        n = ui.notification(timeout=timeout)
        n.spinner = True
        return n


class DatabaseUtils:
    """Utility class for database operations."""

    @staticmethod
    def get_database_service():
        """Get database service instance with proper imports."""
        try:
            from core.db_service import get_database_service
            return get_database_service()
        except ImportError as e:
            print(f"Failed to import database service: {e}")
            return None


class ErrorHandler:
    """Centralized error handling utilities."""

    @staticmethod
    def handle_ui_update_error(error: Exception, operation: str = "UI update"):
        """Handle UI update errors with consistent messaging."""
        error_msg = f"{operation} failed: {str(error)}"
        print(f"{operation} error: {error}")
        UIUtils.show_error_message(error_msg)

    @staticmethod
    def handle_data_loading_error(error: Exception, operation: str = "Data loading"):
        """Handle data loading errors with consistent messaging."""
        error_msg = f"{operation} failed: {str(error)}"
        print(f"{operation} error: {error}")
        UIUtils.show_error_message(error_msg)


# Common filter options
FILTER_OPTIONS = {
    'products': [
        "Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"
    ],
    'locations': [
        'Area', 'Region', 'Country'
    ],
    'levels': [
        "Franchise", "IBP Level 5", "IBP Level 6", "CatalogNumber"
    ]
}


class CustomJsonEncoder(JSONEncoder):
    """Custom JSON encoder to handle non-serializable types like datetime, NaN, and Inf."""
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        # Handle NaN and Inf which are not valid JSON numbers
        if isinstance(o, float) and (o != o or o == float('inf') or o == float('-inf')):
            return None
        return JSONEncoder.default(self, o)


def validate_environment_variables(required_vars: list) -> Dict[str, bool]:
    """Validate that required environment variables are set."""
    results = {}
    for var in required_vars:
        results[var] = bool(os.getenv(var))
    return results
