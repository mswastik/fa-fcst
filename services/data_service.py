"""
Data service for the FastAPI application.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import polars as pl
from core.data_service import apply_filters, create_models_action, change_fc_action
from core.utils import DataUtils, DatabaseUtils, UIUtils, ErrorHandler
from core.state_manager import get_global_state


class DataService:
    """Service for handling data operations"""
    
    @staticmethod
    def get_database_service():
        """Get database service instance"""
        return DatabaseUtils.get_database_service()
    
    @staticmethod
    def load_sample_data() -> pl.DataFrame:
        """Load sample data from database"""
        db_service = DataService.get_database_service()
        if db_service is None:
            return pl.DataFrame()
        
        # Load sales actuals with joined hierarchy data
        df = db_service.get_sales_actuals()
        
        # Apply standard data preparation
        df = DataUtils.prepare_data_for_ui(df)
        
        return df
    
    @staticmethod
    def get_filter_options(prod: str = None, loc: str = None) -> Dict[str, Any]:
        """Get filter options from database"""
        from core.state_manager import DataState
        state = DataState()  # Create temporary state to get default options
        return state.get_filter_options(prod, loc)
    
    @staticmethod
    def apply_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
        """Apply filters to the dataset"""
        # This calls the existing apply_filters function
        return apply_filters(filters)
    
    @staticmethod
    def create_models(df: pl.DataFrame, file_path: str = "") -> pl.DataFrame:
        """Create forecasting models"""
        # This calls the existing create_models_action function
        return create_models_action(df, file_path)
    
    @staticmethod
    def change_fc() -> str:
        """Change forecast settings"""
        # This calls the existing change_fc_action function
        return change_fc_action()
    
    @staticmethod
    def get_data_for_charts(df: pl.DataFrame, chart_type: str = "line") -> Dict[str, Any]:
        """Prepare data specifically for charts"""
        from core.state_manager import DataState
        state = DataState()
        state.filtered_df = df
        
        if chart_type == "column":
            chart_data = state._get_column_chart_data(df)
        else:  # line chart
            chart_data = state._get_line_chart_data(df)
            
        return chart_data or {}
    
    @staticmethod
    def get_cross_filtered_options(product_type: str, location_type: str) -> List[str]:
        """Get product options filtered by location type from database"""
        try:
            db_service = DataService.get_database_service()
            if db_service is None:
                return []
            
            # Map display names to database column names
            column_mapping = {
                'Region': 'region',
                'Country': 'country',
                'Area': 'area',
                'Franchise': 'franchise',
                'IBP Level 5': 'ibp_level_5',
                'IBP Level 6': 'ibp_level_6',
                'CatalogNumber': 'catalog_number'
            }
            
            # Get the corresponding database column names
            db_product_col = column_mapping.get(product_type, product_type.lower().replace(' ', '_'))
            db_location_col = column_mapping.get(location_type, location_type.lower().replace(' ', '_'))
            
            # Query to get distinct products for the specified location type
            query = f"""
            SELECT DISTINCT ph.{db_product_col}
            FROM da.sales_actuals sa
            JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
            JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
            WHERE ph.{db_product_col} IS NOT NULL
            AND lh.{db_location_col} IS NOT NULL
            """
            
            result_df = db_service.execute_query(query, user_id="system")
            
            if result_df is not None and not result_df.is_empty():
                # Extract values, filtering out nulls
                values = [x for x in result_df[db_product_col].unique().to_list() if x is not None]
                return values
            else:
                return []
                
        except Exception as e:
            print(f"Error getting cross-filtered options: {e}")
            # Fallback: return all possible values for the product type
            try:
                db_service = DataService.get_database_service()
                if db_service:
                    filter_options = db_service.get_filter_options()
                    
                    prod_key = 'catalog_numbers'  # Default
                    if product_type == 'Franchise':
                        prod_key = 'franchises'
                    elif product_type == 'IBP Level 5':
                        prod_key = 'ibp_level_5s'
                    elif product_type == 'IBP Level 6':
                        prod_key = 'ibp_level_6s'
                    elif product_type == 'CatalogNumber':
                        prod_key = 'catalog_numbers'
                    
                    return filter_options.get(prod_key, [])
            except:
                return []


# Global instance
data_service = DataService()