"""
Unified Filter Service for FastAPI Dashboard
Provides centralized, efficient filtering logic with proper caching
"""
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import polars as pl
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import json

#from core.utils import DatabaseUtils
from models.schemas import FilterState
from core.db_service import get_database_service


@dataclass
class FilterOptions:
    """Data class for storing filter options"""
    locations: Dict[str, List[str]]  # e.g., {'Region': [...], 'Country': [...], 'Area': [...]}
    products: Dict[str, List[str]]   # e.g., {'Franchise': [...], 'IBP Level 5': [...], ...}
    timestamp: float                 # When these options were last fetched


class FilterService:
    """
    Centralized filter service that handles all filtering operations efficiently
    """
    
    def __init__(self):
        self._cache: Dict[str, FilterOptions] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 300  # 5 minutes TTL
        self._db_service = None
        
        # Column mapping for display names to database columns
        self.column_mapping = {
            'Region': 'region',
            'Country': 'country', 
            'Area': 'area',
            'Franchise': 'franchise',
            'IBP Level 5': 'ibp_level_5',
            'IBP Level 6': 'ibp_level_6',
            'CatalogNumber': 'catalog_number'
        }
    
    def _get_db_service(self):
        """Lazy initialization of database service"""
        if self._db_service is None:
            self._db_service = get_database_service()
        return self._db_service
    
    def get_all_filter_options(self, force_refresh: bool = False) -> FilterOptions:
        """
        Get all filter options from database with caching
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            FilterOptions object containing all available filter values
        """
        cache_key = "all_options"
        
        # Check cache first
        if not force_refresh and cache_key in self._cache:
            cached_options = self._cache[cache_key]
            if time.time() - cached_options.timestamp < self._cache_ttl:
                return cached_options
        
        # Fetch fresh data
        with self._cache_lock:
            # Double-check cache after acquiring lock
            if not force_refresh and cache_key in self._cache:
                cached_options = self._cache[cache_key]
                if time.time() - cached_options.timestamp < self._cache_ttl:
                    return cached_options
            
            # Fetch filter options from database
            db_service = self._get_db_service()
            if db_service is None:
                return FilterOptions(locations={}, products={}, timestamp=time.time())
            
            try:
                # Get filter options from database
                db_options = db_service.get_filter_options()
                
                # Transform to our format
                locations = {
                    'Region': db_options.get('regions', []),
                    'Country': db_options.get('countries', []),
                    'Area': db_options.get('areas', [])
                }
                
                products = {
                    'Franchise': db_options.get('franchises', []),
                    'IBP Level 5': db_options.get('ibp_level_5s', []),
                    'IBP Level 6': db_options.get('ibp_level_6s', []),
                    'CatalogNumber': db_options.get('catalog_numbers', [])
                }
                
                filter_options = FilterOptions(
                    locations=locations,
                    products=products,
                    timestamp=time.time()
                )
                
                # Update cache
                self._cache[cache_key] = filter_options
                
                return filter_options
                
            except Exception as e:
                print(f"Error fetching filter options: {e}")
                # Return cached data if available, even if stale
                if cache_key in self._cache:
                    return self._cache[cache_key]
                # Return empty options as fallback
                return FilterOptions(locations={}, products={}, timestamp=time.time())
    
    def get_distinct_options_for_column(self, column_name: str) -> List[str]:
        """
        Get all distinct options for a given column name from the cached data.
        
        Args:
            column_name: The display name of the column (e.g., 'Region', 'Franchise')
            
        Returns:
            List of all available options for this column
        """
        filter_options = self.get_all_filter_options()
        
        # Check in locations
        if column_name in filter_options.locations:
            return filter_options.locations[column_name]
        
        # Check in products
        if column_name in filter_options.products:
            return filter_options.products[column_name]
            
        return []

    def get_initial_filter_options(self) -> Dict[str, List[str]]:
        """
        Get initial filter options for the dashboard on first load with additional caching.
        
        Returns:
            Dictionary with initial location and product options
        """
        all_options = self.get_all_filter_options()
        
        # Return initial options based on common columns
        return {
            'initial_location_options': all_options.locations.get('Region', []),
            'initial_product_options': all_options.products.get('Franchise', [])
        }

    def get_options_for_select2(self, filter_state: FilterState) -> Dict[str, List[str]]:
        """
        Get options for location2 and product2 based on current filter state.
        This is called when location1 or product1 changes.
        
        Args:
            filter_state: Current filter state
            
        Returns:
            Dictionary with location2_options and product2_options
        """
        result = {
            'location2_options': [],
            'product2_options': []
        }
        
        # Get location2 options based on location1 selection
        if filter_state.location1:
            if filter_state.product1 and filter_state.product2:
                # If product is selected, get cross-filtered location options
                result['location2_options'] = self.get_cross_filtered_options(
                    filter_type='location2',
                    select1_value=filter_state.location1,  # e.g., 'Country'
                    other_select1=filter_state.product1,    # e.g., 'Franchise'
                    other_select2=filter_state.product2     # e.g., 'MAKO'
                )
            else:
                # No product filter, return all options for this location type
                result['location2_options'] = self.get_distinct_options_for_column(filter_state.location1)
        
        # Get product2 options based on product1 selection
        if filter_state.product1:
            if filter_state.location1 and filter_state.location2:
                # If location is selected, get cross-filtered product options
                result['product2_options'] = self.get_cross_filtered_options(
                    filter_type='product2',
                    select1_value=filter_state.product1,    # e.g., 'Franchise'
                    other_select1=filter_state.location1,   # e.g., 'Country'
                    other_select2=filter_state.location2    # e.g., 'AUSTRALIA'
                )
            else:
                # No location filter, return all options for this product type
                result['product2_options'] = self.get_distinct_options_for_column(filter_state.product1)
        
        return result

    def get_cross_filtered_options(self, filter_type: str, select1_value: str,
                                   other_select1: str, other_select2: str) -> List[str]:
        """
        Get options for select2 based on the current selection of the other filter
        
        Args:
            filter_type: Either 'location2' or 'product2'
            select1_value: The column name selected in select1 (e.g., 'Country', 'Franchise')
            other_select1: The column name selected in the other select1
            other_select2: The value selected in the other select2
            
        Returns:
            List of filtered options
        """
        db_service = self._get_db_service()
        if db_service is None:
            return []
        
        try:
            # Map display names to database columns
            target_col = self.column_mapping.get(select1_value, select1_value.lower().replace(' ', '_'))
            filter_col = self.column_mapping.get(other_select1, other_select1.lower().replace(' ', '_'))
            
            if filter_type == 'product2':
                # Get product options filtered by location
                query = f"""
                SELECT DISTINCT ph.{target_col}
                FROM da.sales_actuals sa
                JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
                JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
                WHERE ph.{target_col} IS NOT NULL
                AND lh.{filter_col} = ?
                ORDER BY ph.{target_col}
                LIMIT 1000
                """
                
            else:  # location2
                # Get location options filtered by product
                query = f"""
                SELECT DISTINCT lh.{target_col}
                FROM da.sales_actuals sa
                JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
                JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
                WHERE lh.{target_col} IS NOT NULL
                AND ph.{filter_col} = ?
                ORDER BY lh.{target_col}
                LIMIT 1000
                """
            
            result = db_service.execute_query(query, (other_select2,), "system")
            if result is not None and not result.is_empty():
                options = [str(x) for x in result[target_col].to_list() if x is not None]
                return options
            
            return []
            
        except Exception as e:
            print(f"Error getting cross-filtered options: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_filtered_data(self, filter_state: FilterState) -> Tuple[Optional[pl.DataFrame], Dict[str, Any]]:
        """
        Get filtered data based on filter state
        
        Args:
            filter_state: Current filter state with location1, location2, product1, product2
            
        Returns:
            Tuple of (filtered_dataframe, metadata)
        """
        db_service = self._get_db_service()
        if db_service is None:
            return None, {"error": "Database service not available"}
        
        try:
            # Build WHERE conditions
            where_conditions = []
            params = []
            
            # Add location filter
            if filter_state.location1 and filter_state.location2:
                location_db_col = self.column_mapping.get(filter_state.location1, filter_state.location1.lower().replace(' ', '_'))
                where_conditions.append(f"lh.{location_db_col} = ?")
                params.append(filter_state.location2)
            
            # Add product filter
            if filter_state.product1 and filter_state.product2:
                product_db_col = self.column_mapping.get(filter_state.product1, filter_state.product1.lower().replace(' ', '_'))
                where_conditions.append(f"ph.{product_db_col} = ?")
                params.append(filter_state.product2)
            
            where_clause = " AND ".join(where_conditions) if where_conditions else ""
            
            # Build optimized query
            query = f"""
            SELECT 
                sa.item_skey,
                sa.location_skey,
                sa.sales_date,
                sa.act_orders_rev,
                sa.fcst_stat_prelim_rev,
                sa.fcst_stat_final_rev,
                sa.l2_stat_final_rev,
                sa.fcst_df_final_rev,
                sa.l2_df_final_rev,
                sa.act_orders_rev_val,
                sa.l1_df_final_rev,
                sa.l0_df_final_rev,
                sa.fcst_df_final_rev_val,
                
                -- Product fields
                ph.catalog_number,
                ph.business_sector,
                ph.business_unit,
                ph.franchise,
                ph.product_line,
                ph.ibp_level_5,
                ph.ibp_level_6,
                ph.ibp_level_7,
                ph.uom,
                ph.pack_content,
                
                -- Location fields
                lh.country,
                lh.region,
                lh.area,
                lh.selling_division,
                lh.stryker_group_region
            FROM da.sales_actuals sa
            INNER JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
            INNER JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
            {"WHERE " + where_clause if where_clause else ""}
            ORDER BY sa.sales_date DESC, sa.item_skey, sa.location_skey
            LIMIT 100000
            """
            
            result = db_service.execute_query(query, tuple(params) if params else None, "system")
            
            if result is not None and not result.is_empty():
                # Apply data preparation
                from core.utils import DataUtils
                result = DataUtils.prepare_data_for_ui(result)
                
                metadata = {
                    "total_records": len(result),
                    "filters_applied": {
                        "location": f"{filter_state.location1} = {filter_state.location2}" if filter_state.location1 and filter_state.location2 else None,
                        "product": f"{filter_state.product1} = {filter_state.product2}" if filter_state.product1 and filter_state.product2 else None
                    },
                    "columns": list(result.columns)
                }
                
                return result, metadata
            else:
                return None, {"error": "No data found with current filters", "total_records": 0}
                
        except Exception as e:
            print(f"Error getting filtered data: {e}")
            return None, {"error": str(e), "total_records": 0}
    
    def clear_cache(self):
        """Clear the filter options cache"""
        with self._cache_lock:
            self._cache.clear()
    
    def refresh_cache(self):
        """Force refresh the filter options cache"""
        self.clear_cache()
        return self.get_all_filter_options(force_refresh=True)


# Global instance
filter_service = FilterService()
