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

from core.utils import DatabaseUtils
from models.schemas import FilterState


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
            self._db_service = DatabaseUtils.get_database_service()
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
            'initial_location_options': all_options.locations.get('Region', []),  # Limit to first 50 for performance
            'initial_product_options': all_options.products.get('Franchise', [])   # Limit to first 50 for performance
        }

    def get_cross_filtered_options(self, filter_type: str, filter_value: str,
                                 other_filter_type: str, other_filter_value: str) -> List[str]:
        """
        Get options for one filter based on the current selection of another filter
        
        Args:
            filter_type: The filter we want options for ('location2' or 'product2')
            filter_value: The selected value for this filter
            other_filter_type: The other filter type that constrains our options
            other_filter_value: The selected value for the other filter
            
        Returns:
            List of filtered options
        """
        db_service = self._get_db_service()
        if db_service is None:
            return []
        
        try:
            # Map filter types to database columns
            # filter_value is the column name for the filter we want options for (e.g., 'Franchise')
            # other_filter_type is the column name for the filter we are filtering by (e.g., 'Region')
            
            filter_db_col = self.column_mapping.get(filter_value, filter_value.lower().replace(' ', '_'))
            other_db_col = self.column_mapping.get(other_filter_type, other_filter_type.lower().replace(' ', '_'))
            
            if filter_type == 'product2':
                # We want product options based on location selection
                
                print(f"Debug: Getting {filter_value} products where {other_filter_type} = {other_filter_value}")
                print(f"Debug: Using columns {filter_db_col} and {other_db_col}")
                
                # Build query for product options
                query = f"""
                SELECT DISTINCT ph.{filter_db_col}
                FROM da.sales_actuals sa
                JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
                JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
                WHERE ph.{filter_db_col} IS NOT NULL
                AND lh.{other_db_col} IS NOT NULL
                AND lh.{other_db_col} = ?
                ORDER BY ph.{filter_db_col}
                LIMIT 1000
                """
                
                result = db_service.execute_query(query, (other_filter_value,), "system")
                if result is not None and not result.is_empty():
                    options = [str(x) for x in result[filter_db_col].to_list() if x is not None]
                    print(f"Debug: Found {len(options)} {filter_value} options for {other_filter_type} = {other_filter_value}")
                    return options
                else:
                    print(f"Debug: No results for {filter_value} in {other_filter_type} = {other_filter_value}")
                    
            elif filter_type == 'location2':
                # We want location options based on product selection
                
                print(f"Debug: Getting {filter_value} locations where {other_filter_type} = {other_filter_value}")
                print(f"Debug: Using columns {filter_db_col} and {other_db_col}")
                
                # Build query for location options
                query = f"""
                SELECT DISTINCT lh.{filter_db_col}
                FROM da.sales_actuals sa
                JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
                JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
                WHERE lh.{filter_db_col} IS NOT NULL
                AND ph.{other_db_col} IS NOT NULL
                AND ph.{other_db_col} = ?
                ORDER BY lh.{filter_db_col}
                LIMIT 1000
                """
                
                result = db_service.execute_query(query, (other_filter_value,), "system")
                if result is not None and not result.is_empty():
                    options = [str(x) for x in result[filter_db_col].to_list() if x is not None]
                    print(f"Debug: Found {len(options)} {filter_value} options for {other_filter_type} = {other_filter_value}")
                    return options
                else:
                    print(f"Debug: No results for {filter_value} in {other_filter_type} = {other_filter_value}")
            
            return []
            
        except Exception as e:
            print(f"Error getting cross-filtered options: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_unconstrained_options(self, filter_type: str) -> List[str]:
        """
        Get all available options for a filter type without constraints
        
        Args:
            filter_type: Either 'location2' or 'product2'
            
        Returns:
            List of all available options for this filter type
        """
        filter_options = self.get_all_filter_options()
        
        if filter_type == 'location2':
            # Return all location options from all location types
            all_locations = []
            for location_type, options in filter_options.locations.items():
                all_locations.extend(options)
            return sorted(list(set(all_locations)))  # Remove duplicates and sort
        elif filter_type == 'product2':
            # Return all product options from all product types
            all_products = []
            for product_type, options in filter_options.products.items():
                all_products.extend(options)
            return sorted(list(set(all_products)))  # Remove duplicates and sort
        
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
    
    def get_available_filter_combinations(self, filter_state: FilterState) -> Dict[str, List[str]]:
        """
        Get all available filter combinations based on current selections
        
        Args:
            filter_state: Current filter state
            
        Returns:
            Dictionary with 'location2_options' and 'product2_options' keys
        """
        filter_options = self.get_all_filter_options()
        result = {
            'location2_options': [],
            'product2_options': []
        }
        
        try:
            print(f"Debug: Getting combinations for filter_state: {filter_state}")
            
            # Get product2 options based on location2 selection (if available)
            if filter_state.product1:
                if filter_state.location1 and filter_state.location2:
                    # Cross-filter: get products that are sold in this specific location
                    # For product2 options: find products of type 'Franchise' that have sales in 'AUSTRALIA'
                    result['product2_options'] = self.get_cross_filtered_options(
                        'product2', filter_state.product1,
                        filter_state.location1, filter_state.location2
                    )
                else:
                    # Use all available options for the selected product type
                    result['product2_options'] = filter_options.products.get(filter_state.product1, [])
            
            # Get location2 options based on product2 selection (if available)
            if filter_state.location1:
                if filter_state.product1 and filter_state.product2:
                    # Cross-filter: get locations that have this specific product
                    # For location2 options: find locations of type 'Country' that have sales of the selected product
                    result['location2_options'] = self.get_cross_filtered_options(
                        'location2', filter_state.location1,
                        filter_state.product1, filter_state.product2
                    )
                else:
                    # Use all available options for the selected location type
                    result['location2_options'] = filter_options.locations.get(filter_state.location1, [])
            
            print(f"Debug: Result: {result}")
            return result
            
        except Exception as e:
            print(f"Error getting available filter combinations: {e}")
            import traceback
            traceback.print_exc()
            # Return cached options as fallback
            return {
                'location2_options': filter_options.locations.get(filter_state.location1, []) if filter_state.location1 else [],
                'product2_options': filter_options.products.get(filter_state.product1, []) if filter_state.product1 else []
            }
    
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