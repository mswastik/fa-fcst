"""
Enhanced Database Service with Multi-User Support
Supports multiple concurrent users with separate database connections
"""
import os
import threading
import time
import logging
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import polars as pl
import duckdb

# Import the updated multi-user connection manager
from .duckdb_connection_manager import get_duckdb_connection_manager

logger = logging.getLogger(__name__)

class DatabaseService:
    """Enhanced database service with multi-user support"""

    def __init__(self):
        self.connection_manager = get_duckdb_connection_manager()
        logger.info("Enhanced Database Service initialized with DuckDB multi-user support")

        # Define schema mapping for consistent DataFrame creation
        self.schema_mapping = {
            # String types
            'VARCHAR': pl.Utf8,
            'NVARCHAR': pl.Utf8,
            'TEXT': pl.Utf8,
            'STRING': pl.Utf8,

            # Numeric types
            'INT': pl.Int64,
            'BIGINT': pl.Int64,
            'SMALLINT': pl.Int32,
            'TINYINT': pl.Int16,

            # Decimal types (handle as Float64 for consistency)
            'DECIMAL': pl.Float64,
            'NUMERIC': pl.Float64,
            'MONEY': pl.Float64,

            # Float types
            'FLOAT': pl.Float64,
            'REAL': pl.Float32,
            'DOUBLE': pl.Float64,

            # Date/Time types
            'DATE': pl.Date,
            'TIME': pl.Time,
            'DATETIME': pl.Datetime,
            'TIMESTAMP': pl.Datetime,

            # Boolean
            'BIT': pl.Boolean,
            'BOOL': pl.Boolean,
            'BOOLEAN': pl.Boolean,
        }

    def create_user_session(self, user_id: str) -> str:
        """Create a new database session for a user"""
        try:
            session_id = self.connection_manager.create_user_connection(user_id)
            logger.info(f"Created database session for user: {user_id}")
            return session_id
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            raise

    def execute_query(self, query: str, params: Optional[tuple] = None, user_id: Optional[str] = None) -> pl.DataFrame:
        """Execute a query for a specific user and return Polars DataFrame using Arrow format"""
        if not user_id:
            raise ValueError("user_id is required for multi-user operation")

        column_mapping = {
            'Region': 'region',
            'Country': 'country',
            'Area': 'area',
            'Franchise': 'franchise',
            'IBP Level 5': 'ibp_level_5',
            'IBP Level 6': 'ibp_level_6',
            'CatalogNumber': 'catalog_number'
        }

        # Use a temporary direct connection to avoid locking issues
        import duckdb
        from time import sleep
        import random

        max_retries = 3
        retry_delay = 0.05

        conn = None
        for attempt in range(max_retries):
            try:
                conn = duckdb.connect(self.connection_manager._db_path)
                break
            except Exception as e:
                error_msg = str(e)
                if "The process cannot access the file because it is being used by another process" in error_msg or "IO Error" in error_msg:
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        print(f"Database file locked during query, retrying in {sleep_time:.2f}s... (attempt {attempt + 1}/{max_retries})")
                        sleep(sleep_time)
                        continue
                    else:
                        print(f"Failed to create query connection after {max_retries} attempts: {e}")
                        raise
                else:
                    print(f"Failed to create query connection: {e}")
                    raise

        try:
            # Execute query directly on connection (DuckDB supports this)
            if params:
                df_result = conn.execute(query, params).fetchdf()
            else:
                df_result = conn.execute(query).fetchdf()

            # Convert to Polars DataFrame
            df = pl.from_pandas(df_result)

            # Handle any remaining datetime timezone issues
            for col in df.columns:
                if df[col].dtype == pl.Datetime:
                    try:
                        # Convert timezone-aware datetimes to UTC and remove timezone
                        df = df.with_columns(
                            pl.col(col).dt.convert_time_zone("UTC").dt.replace_time_zone(None)
                        )
                    except Exception:
                        # If timezone conversion fails, convert to string
                        df = df.with_columns(pl.col(col).cast(pl.Utf8))

            return df

        except Exception as e:
            logger.error(f"Query execution failed for user {user_id}: {e}")
            raise
        finally:
            # Always close the temporary connection
            if conn:
                conn.close()

    def execute_query_raw(self, query: str, params: Optional[tuple] = None, user_id: Optional[str] = None):
        """Execute a query and return raw cursor results"""
        if not user_id:
            raise ValueError("user_id is required for multi-user operation")

        # Use a temporary direct connection to avoid locking issues
        import duckdb
        from contextlib import contextmanager
        from time import sleep
        import random

        max_retries = 3
        retry_delay = 0.05

        conn = None
        for attempt in range(max_retries):
            try:
                conn = duckdb.connect(self.connection_manager._db_path)
                break
            except Exception as e:
                error_msg = str(e)
                if "The process cannot access the file because it is being used by another process" in error_msg or "IO Error" in error_msg:
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        print(f"Database file locked during raw query, retrying in {sleep_time:.2f}s... (attempt {attempt + 1}/{max_retries})")
                        sleep(sleep_time)
                        continue
                    else:
                        print(f"Failed to create raw query connection after {max_retries} attempts: {e}")
                        raise
                else:
                    print(f"Failed to create raw query connection: {e}")
                    raise

        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        # We'll still return both cursor and connection for proper cleanup
        # But also provide a close method for the caller
        cursor._temp_conn = conn  # Attach connection to cursor for cleanup
        return cursor

    def close_cursor_and_connection(self, cursor):
        """Helper method to close cursor and its associated connection"""
        try:
            cursor.close()
        except:
            pass  # Cursor might already be closed

        # Close the associated temporary connection
        if hasattr(cursor, '_temp_conn') and cursor._temp_conn:
            try:
                cursor._temp_conn.close()
            except:
                pass  # Connection might already be closed

    def get_sales_actuals(self, filters: Optional[Dict] = None, limit: Optional[int] = None, user_id: Optional[str] = None) -> pl.DataFrame:
        """Get sales actuals data for a specific user"""
        if not user_id:
            user_id = "system"

        query = """
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
            lh.country,
            lh.region,
            lh.area,
            lh.selling_division,
            lh.stryker_group_region
        FROM da.sales_actuals sa
        LEFT JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
        LEFT JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
        """

        conditions = []
        params = []

        if filters:
            if 'item_skey' in filters:
                conditions.append("sa.item_skey = ?")
                params.append(filters['item_skey'])
            if 'location_skey' in filters:
                conditions.append("sa.location_skey = ?")
                params.append(filters['location_skey'])
            if 'start_date' in filters:
                conditions.append("sa.sales_date >= ?")
                params.append(filters['start_date'])
            if 'end_date' in filters:
                conditions.append("sa.sales_date <= ?")
                params.append(filters['end_date'])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        if limit:
            query += f" LIMIT {limit}"

        return self.execute_query(query, tuple(params) if params else None, user_id)

    def estimate_filtered_data_size(self, location_col: Optional[str] = None, location_val: Optional[str] = None, product_col: Optional[str] = None, product_val: Optional[str] = None, user_id: Optional[str] = None) -> int:
        """Estimate the number of rows that would be returned with given filters"""
        if not user_id:
            user_id = "system"

        # Build WHERE conditions
        where_conditions = []
        params = []

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

        if location_col and location_val:
            db_location_col = column_mapping.get(location_col, location_col.lower().replace(' ', '_'))
            where_conditions.append(f"lh.{db_location_col} = ?")
            params.append(location_val)

        if product_col and product_val:
            db_product_col = column_mapping.get(product_col, product_col.lower().replace(' ', '_'))
            where_conditions.append(f"ph.{db_product_col} = ?")
            params.append(product_val)

        where_clause = " AND ".join(where_conditions) if where_conditions else ""

        # Count query with filters applied at database level
        count_query = f"""
        SELECT COUNT(*) as count
        FROM da.sales_actuals sa
        JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
        JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
        {"WHERE " + where_clause if where_clause else ""}
        """

        result = self.execute_query(count_query, tuple(params) if params else None, user_id)
        return result['count'][0] if len(result) > 0 and 'count' in result.columns else 0

    def get_filtered_sales_actuals(self, location_col: Optional[str] = None, location_val: Optional[str] = None, product_col: Optional[str] = None, product_val: Optional[str] = None, user_id: Optional[str] = None) -> pl.DataFrame:
        """Get filtered sales actuals data for a specific user"""
        if not user_id:
            user_id = "system"

        # Build WHERE conditions
        where_conditions = []
        params = []

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

        if location_col and location_val:
            db_location_col = column_mapping.get(location_col, location_col.lower().replace(' ', '_'))
            where_conditions.append(f"lh.{db_location_col} = ?")
            params.append(location_val)

        if product_col and product_val:
            db_product_col = column_mapping.get(product_col, product_col.lower().replace(' ', '_'))
            where_conditions.append(f"ph.{db_product_col} = ?")
            params.append(product_val)

        where_clause = " AND ".join(where_conditions) if where_conditions else ""

        # Query with filters applied at database level - optimized for performance
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

            -- Location fields
            lh.country,
            lh.region,
            lh.area,
            lh.selling_division,
            lh.stryker_group_region,

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
            ph.pack_content
        FROM da.sales_actuals sa
        INNER JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
        INNER JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
        {"WHERE " + where_clause if where_clause else ""}
        ORDER BY sa.sales_date DESC, sa.item_skey, sa.location_skey
        LIMIT 1000000
        """

        return self.execute_query(query, tuple(params) if params else None, user_id)

    # Cache for filter options with a 5-minute TTL
    _filter_options_cache = {}
    _last_refresh_time = 0
    _cache_ttl = 300  # 5 minutes in seconds
    _cache_lock = threading.Lock()

    def get_filter_options(self, user_id: str = None, force_refresh: bool = False) -> Dict[str, List[str]]:
        """Get available filter options from hierarchy tables with caching.

        Optimized version using simpler queries to avoid expensive ARRAY_AGG operations.

        Args:
            user_id: Optional user ID (defaults to 'system')
            force_refresh: If True, bypass cache and refresh data

        Returns:
            Dictionary of filter options
        """
        current_time = time.time()
        cache_expired = (current_time - self._last_refresh_time) > self._cache_ttl

        # Return cached data if available and not forcing refresh
        if not force_refresh and not cache_expired and self._filter_options_cache:
            logger.debug("Returning cached filter options")
            return self._filter_options_cache

        with self._cache_lock:
            # Check again in case another thread already refreshed the cache
            if not force_refresh and not cache_expired and self._filter_options_cache:
                logger.debug("Returning cached filter options (double-checked)")
                return self._filter_options_cache

            # Use default user_id if not provided
            user_id = user_id or "system"
            logger.info(f"Refreshing filter options for user {user_id}")

            try:
                options = {}

                # Use simpler queries with LIMIT to avoid expensive ARRAY_AGG operations
                # This is much faster for large datasets

                # Get product options with LIMIT to prevent memory issues
                product_queries = [
                    ("SELECT DISTINCT franchise FROM da.product_hierarchy WHERE franchise IS NOT NULL ORDER BY franchise LIMIT 1000", 'franchises'),
                    ("SELECT DISTINCT ibp_level_5 FROM da.product_hierarchy WHERE ibp_level_5 IS NOT NULL ORDER BY ibp_level_5 LIMIT 2000", 'ibp_level_5s'),
                    ("SELECT DISTINCT ibp_level_6 FROM da.product_hierarchy WHERE ibp_level_6 IS NOT NULL ORDER BY ibp_level_6 LIMIT 2000", 'ibp_level_6s'),
                    ("SELECT DISTINCT catalog_number FROM da.product_hierarchy WHERE catalog_number IS NOT NULL ORDER BY catalog_number LIMIT 22000", 'catalog_numbers')
                ]

                # Get location options with LIMIT
                location_queries = [
                    ("SELECT DISTINCT region FROM da.location_hierarchy WHERE region IS NOT NULL ORDER BY region LIMIT 1000", 'regions'),
                    ("SELECT DISTINCT country FROM da.location_hierarchy WHERE country IS NOT NULL ORDER BY country LIMIT 1000", 'countries'),
                    ("SELECT DISTINCT area FROM da.location_hierarchy WHERE area IS NOT NULL ORDER BY area LIMIT 1000", 'areas')
                ]

                logger.debug("Executing optimized filter options queries with limits")

                # Execute queries in parallel with smaller batches
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = []

                    # Submit all queries
                    for query, key in product_queries + location_queries:
                        future = executor.submit(self.execute_query, query, None, user_id)
                        futures.append((future, key))

                    # Process results
                    for future, key in futures:
                        try:
                            result = future.result(timeout=10)  # 10 second timeout per query
                            if result is not None and not result.is_empty():
                                # Extract the single column values
                                values = result.to_numpy().flatten().tolist()
                                # Filter out None and empty values
                                options[key] = [str(v) for v in values if v is not None and str(v).strip() != '']
                                logger.debug(f"Got {len(options[key])} options for {key}")
                            else:
                                options[key] = []
                                logger.warning(f"No data found for {key}")
                        except Exception as e:
                            logger.error(f"Error processing {key}: {e}", exc_info=True)
                            options[key] = []

                # Ensure all expected keys exist with at least empty lists
                for key in ['franchises', 'ibp_level_5s', 'ibp_level_6s', 'catalog_numbers',
                           'regions', 'countries', 'areas']:
                    if key not in options:
                        options[key] = []

                # Update cache
                self._filter_options_cache = options
                self._last_refresh_time = current_time

                total_options = sum(len(v) for v in options.values())
                logger.info(f"Successfully refreshed filter options. Found {total_options} total options")
                return options

            except Exception as e:
                error_msg = f"Error getting filter options: {str(e)}"
                logger.error(error_msg, exc_info=True)

                # Return cached data if available, even if stale
                if self._filter_options_cache:
                    logger.warning("Using cached filter options due to error")
                    return self._filter_options_cache

                # If no cached data, return empty options
                logger.warning("No cached filter options available, returning empty options")
                return {
                    'franchises': [],
                    'ibp_level_5s': [],
                    'ibp_level_6s': [],
                    'catalog_numbers': [],
                    'regions': [],
                    'countries': [],
                    'areas': []
                }

    def _get_skeys_for_unique_id(self, unique_id: str, user_id: str) -> Tuple[Optional[int], Optional[int]]:
        """Helper to get item_skey and location_skey from unique_id (item_skey_location_skey format)"""
        logger.debug(f"Getting skeys for unique_id: {unique_id}")
        try:
            # First try the item_skey_location_skey format
            item_skey, location_skey = unique_id.split('_', 1)
            item_skey = int(item_skey)
            location_skey = int(location_skey)
            logger.debug(f"Parsed item_skey: {item_skey}, location_skey: {location_skey}")
            return item_skey, location_skey
        except ValueError:
            # If that fails, try the Country,CatalogNumber format as fallback
            try:
                country, catalog_number = unique_id.split(',', 1)
                logger.debug(f"Parsed country: {country}, catalog_number: {catalog_number}")
            except ValueError:
                logger.warning(f"Invalid unique_id format: {unique_id}. Expected 'item_skey_location_skey' or 'Country,CatalogNumber'")
                return None, None

        # Query product_hierarchy for item_skey
        logger.debug(f"Querying product_hierarchy for catalog_number: {catalog_number}")
        product_query = "SELECT demantra_item_skey FROM da.product_hierarchy WHERE UPPER(TRIM(catalog_number)) = UPPER(TRIM(?))"
        try:
            product_result = self.execute_query(product_query, (catalog_number,), user_id)
            item_skey = product_result['demantra_item_skey'][0] if not product_result.is_empty() else None
            logger.debug(f"Product query result - item_skey: {item_skey}, found {len(product_result)} matches")
        except Exception as e:
            logger.error(f"Error querying product_hierarchy: {e}")
            item_skey = None

        # Query location_hierarchy for location_skey
        logger.debug(f"Querying location_hierarchy for country: {country}")
        location_query = "SELECT location_skey FROM da.location_hierarchy WHERE UPPER(TRIM(country)) = UPPER(TRIM(?))"
        try:
            location_result = self.execute_query(location_query, (country,), user_id)
            location_skey = location_result['location_skey'][0] if not location_result.is_empty() else None
            logger.debug(f"Location query result - location_skey: {location_skey}, found {len(location_result)} matches")
        except Exception as e:
            logger.error(f"Error querying location_hierarchy: {e}")
            location_skey = None

        return item_skey, location_skey

    def get_cross_filtered_options(self, product_type: str, location_type: str, user_id: str = "system") -> List[str]:
        """Get product options filtered by location type from database"""
        if not user_id:
            user_id = "system"

        try:
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

            result_df = self.execute_query(query, user_id=user_id)

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
                filter_options = self.get_filter_options(user_id=user_id)

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

    def insert_forecasts(self, forecast_df: pl.DataFrame, model_type: str, forecast_version: Optional[str] = None, user_id: str = None) -> int:
        """
        Inserts forecast data into the da.forecasts table.
        Assumes forecast_df has 'unique_id', 'forecast_date' (or 'ds' or 'SALES_DATE'), and forecast columns (e.g., 'Fcst Ensemble Rev').
        If item_skey and location_skey columns are present, uses them directly.
        Otherwise, parses unique_id in Country,CatalogNumber format.
        """
        if not user_id:
            user_id = "system" # Default to system user if not provided

        total_input_records = len(forecast_df)
        logger.info(f"Starting forecast insertion for {total_input_records} records, user: {user_id}, version: {forecast_version}")
        print(f"DEBUG: Starting forecast insertion for {total_input_records} records, version: {forecast_version}")
        print(f"DEBUG: DataFrame schema: {forecast_df.schema}")

        if forecast_df.is_empty():
            logger.warning("No forecast data to insert.")
            print("DEBUG: No forecast data to insert.")
            return 0

        # For forecast insertion, use a temporary direct connection to avoid locking issues
        import duckdb
        from time import sleep
        import random

        max_retries = 5
        retry_delay = 0.1

        conn = None
        for attempt in range(max_retries):
            try:
                conn = duckdb.connect(self.connection_manager._db_path)
                logger.info("Database connection established for forecast insertion")
                break
            except Exception as e:
                error_msg = str(e)
                if "The process cannot access the file because it is being used by another process" in error_msg or "IO Error" in error_msg:
                    if attempt < max_retries - 1:  # Don't sleep on the last attempt
                        sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        print(f"Database file locked, retrying in {sleep_time:.2f}s... (attempt {attempt + 1}/{max_retries})")
                        sleep(sleep_time)
                        continue
                    else:
                        print(f"Failed to create connection after {max_retries} attempts: {e}")
                        raise
                else:
                    print(f"Failed to create connection for forecast insertion: {e}")
                    raise

        # Store connection reference for use in finally block
        self._temp_conn = conn

        # Ensure forecast_date is present and correctly typed (handle different possible column names)
        date_column_found = False
        if 'forecast_date' in forecast_df.columns:
            # Already has the correct column name
            forecast_df = forecast_df.with_columns(pl.col('forecast_date').cast(pl.Datetime))
            date_column_found = True
        elif 'ds' in forecast_df.columns:
            # Rename 'ds' to 'forecast_date'
            forecast_df = forecast_df.rename({'ds': 'forecast_date'})
            forecast_df = forecast_df.with_columns(pl.col('forecast_date').cast(pl.Datetime))
            date_column_found = True
        elif 'SALES_DATE' in forecast_df.columns:
            # Rename 'SALES_DATE' to 'forecast_date'
            forecast_df = forecast_df.rename({'SALES_DATE': 'forecast_date'})
            forecast_df = forecast_df.with_columns(pl.col('forecast_date').cast(pl.Datetime))
            date_column_found = True

        if not date_column_found:
            raise ValueError("Forecast DataFrame must contain a date column ('forecast_date', 'ds', or 'SALES_DATE').")

        logger.info("DataFrame prepared for insertion")
        print(f"DEBUG: DataFrame prepared - number of unique_id values: {forecast_df['unique_id'].n_unique() if 'unique_id' in forecast_df.columns else 0}")

        # Prepare data for insertion - batch process to improve performance
        logger.info("Starting batch data preparation for insertion...")
        records_to_insert = []
        skipped_count = 0
        total_records = len(forecast_df)
        logger.info(f"Processing {total_records} forecast records")

        # Check if item_skey and location_skey are available directly
        use_direct_skeys = 'item_skey' in forecast_df.columns and 'location_skey' in forecast_df.columns
        logger.info(f"Using direct skeys: {use_direct_skeys}")

        # Use the passed forecast_version, default to "1.0" if None
        current_model_version = forecast_version if forecast_version is not None else "1.0"

        # Create or get version_id for this forecast run
        version_id = self._create_or_get_version_id(current_model_version, user_id=user_id)

        if use_direct_skeys:
            # Process all records at once when skeys are available directly
            logger.info("Processing records with direct skeys...")

            # Get all required columns
            unique_ids = forecast_df['unique_id'].to_list() if 'unique_id' in forecast_df.columns else [None] * len(forecast_df)
            item_skeys = forecast_df['item_skey'].to_list()
            location_skeys = forecast_df['location_skey'].to_list()
            forecast_dates = forecast_df['forecast_date'].to_list()

            # Handle different possible forecast value columns
            forecast_value_col = None
            possible_forecast_cols = ['Fcst Ensemble Rev', 'ensemble', 'NHITS', 'LSTM', 'AutoARIMA', 'AutoETS', 'SeasonalNaive']
            for col in possible_forecast_cols:
                if col in forecast_df.columns:
                    forecast_value_col = col
                    break

            if forecast_value_col:
                forecast_values = forecast_df[forecast_value_col].to_list()
            else:
                # Fallback if no forecast column is found
                forecast_values = [0.0] * len(forecast_df)

            # Process all records in a vectorized way
            for i in range(len(forecast_df)):
                if item_skeys[i] is None or location_skeys[i] is None:
                    logger.warning(f"Skipping row {i} due to missing item_skey or location_skey: item_skey={item_skeys[i]}, location_skey={location_skeys[i]}")
                    skipped_count += 1
                    continue

                # Generate a unique forecast_id
                forecast_id = uuid.uuid4().int & (1<<63)-1  # Generate a 63-bit integer UUID

                records_to_insert.append({
                    'forecast_id': forecast_id,
                    'item_skey': item_skeys[i],
                    'location_skey': location_skeys[i],
                    'forecast_date': forecast_dates[i].strftime('%Y-%m-%d'),  # Format date for SQL
                    'model_type': model_type,
                    'forecast_value': forecast_values[i],
                    'version_id': version_id
                })
        else:
            # Process records efficiently by extracting skeys from unique_id in bulk
            logger.info("Processing records by extracting skeys from unique_id in bulk...")

            # Extract all unique_id values to process in bulk
            unique_ids = forecast_df['unique_id'].to_list()

            # First, handle unique_ids in item_skey_location_skey format directly without database calls
            item_skeys = []
            location_skeys = []

            # Calculate total unique IDs to process
            total_unique_ids = len(unique_ids)
            processed_unique_ids = 0

            for unique_id in unique_ids:
                item_skey = None
                location_skey = None

                if unique_id and isinstance(unique_id, str):
                    # Check if unique_id is in item_skey_location_skey format
                    if '_' in unique_id:
                        parts = unique_id.split('_', 1)  # Split only on first underscore
                        if len(parts) == 2:
                            try:
                                item_skey = int(parts[0])
                                location_skey = int(parts[1])
                            except ValueError:
                                # If conversion fails, it's not in the expected format
                                item_skey = None
                                location_skey = None
                    elif ',' in unique_id:  # Country,CatalogNumber format
                        # For this format, extract country and catalog number
                        try:
                            country, catalog_number = unique_id.split(',', 1)
                            # Since we can't do bulk lookups without a separate method,
                            # we'll still need to call _get_skeys_for_unique_id
                            item_skey, location_skey = self._get_skeys_for_unique_id(unique_id, user_id)
                        except ValueError:
                            # If split fails, set both to None
                            item_skey = None
                            location_skey = None
                    else:
                        # For other formats, try to get skeys via database
                        item_skey, location_skey = self._get_skeys_for_unique_id(unique_id, user_id)

                item_skeys.append(item_skey)
                location_skeys.append(location_skey)

                processed_unique_ids += 1
                if processed_unique_ids % 1000 == 0 or processed_unique_ids == total_unique_ids:
                    print(f"DEBUG: Processed {processed_unique_ids}/{total_unique_ids} unique IDs ({processed_unique_ids/total_unique_ids*100:.1f}%)")

            # Now process all records in bulk with the extracted skeys
            forecast_values = []
            forecast_value_col = None
            possible_forecast_cols = ['Fcst Ensemble Rev', 'ensemble', 'NHITS', 'LSTM', 'AutoARIMA', 'AutoETS', 'SeasonalNaive']

            for col in possible_forecast_cols:
                if col in forecast_df.columns:
                    forecast_value_col = col
                    break

            if forecast_value_col:
                forecast_values = forecast_df[forecast_value_col].to_list()
            else:
                # Fallback if no forecast column is found
                forecast_values = [0.0] * len(forecast_df)

            forecast_dates = forecast_df['forecast_date'].to_list()
            unique_ids_list = forecast_df['unique_id'].to_list()

            # Create all records in bulk
            total_processed = 0
            for i, (unique_id, item_skey, location_skey) in enumerate(zip(unique_ids_list, item_skeys, location_skeys)):
                if item_skey is None or location_skey is None:
                    logger.warning(f"Could not find s_keys for unique_id: {unique_id}. Item_skey: {item_skey}, Location_skey: {location_skey}. Skipping row.")
                    skipped_count += 1
                    continue

                # Generate a unique forecast_id
                forecast_id = uuid.uuid4().int & (1<<63)-1  # Generate a 63-bit integer UUID

                records_to_insert.append({
                    'forecast_id': forecast_id,
                    'item_skey': item_skey,
                    'location_skey': location_skey,
                    'forecast_date': forecast_dates[i].strftime('%Y-%m-%d'),  # Format date for SQL
                    'model_type': model_type,
                    'forecast_value': forecast_values[i],
                    'model_version': current_model_version,
                    'version_id': version_id
                })

                total_processed += 1
                if total_processed % 1000 == 0:
                    print(f"DEBUG: Prepared {total_processed} records for insertion (skipped {skipped_count})")

        logger.info(f"Prepared {len(records_to_insert)} records for insertion, skipped {skipped_count}")
        print(f"DEBUG: Prepared {len(records_to_insert)} records for insertion, skipped {skipped_count} records")
        print(f"DEBUG: Sample of data being sent: {records_to_insert[0] if records_to_insert else 'No records prepared'}")

        if not records_to_insert:
            logger.warning(f"No valid records to insert after processing. Skipped {skipped_count} records.")
            print(f"DEBUG: No valid records to insert after processing.")
            return 0

        cursor = conn.cursor()
        # Set a timeout for the cursor operations
        logger.info("Database cursor created")

        try:
            # Delete existing forecasts for this version_id
            delete_query = "DELETE FROM da.forecasts WHERE version_id = ?"
            cursor.execute(delete_query, (version_id,))
            deleted_count = cursor.rowcount
            logger.info(f"Deleted {deleted_count} existing forecast records for version_id {version_id}")
            print(f"DEBUG: Deleted {deleted_count} existing records for version_id {version_id}")

            # Execute in larger batches to improve performance
            batch_size = 5000  # Increase batch size for better performance
            total_records = len(records_to_insert)
            inserted_count = 0

            logger.info(f"Starting batch insertion of {total_records} records with batch size {batch_size}")
            print(f"DEBUG: Starting batch insertion of {total_records} records...")

            import time
            start_time = time.time()

            for i in range(0, total_records, batch_size):
                batch_end = min(i + batch_size, total_records)
                batch = records_to_insert[i:batch_end]

                if i % 5000 == 0:  # Log progress every 5000 records
                    elapsed = time.time() - start_time
                    records_so_far = i + len(batch)
                    print(f"DEBUG: Inserting records {records_so_far}/{total_records} (elapsed: {elapsed:.2f}s)")

                # Prepare the batch INSERT statement
                columns = list(batch[0].keys())
                columns_str = ", ".join(columns)
                placeholders_str = ", ".join(["?" for _ in columns])
                insert_query = f"INSERT INTO da.forecasts ({columns_str}) VALUES ({placeholders_str})"

                # Prepare batch values - convert each record to tuple in the correct order
                batch_values = []
                for record in batch:
                    # Ensure values are in the same order as columns
                    values = []
                    for col in columns:
                        value = record[col]
                        # Handle datetime conversion if needed
                        if isinstance(value, str) and 'date' in col.lower():
                            # Already formatted as string in correct format
                            values.append(value)
                        else:
                            # Convert Polars Series values to Python types for Databricks compatibility
                            if hasattr(value, 'item'):
                                try:
                                    values.append(value.item())
                                except (ValueError, AttributeError):
                                    values.append(value if not hasattr(value, '__len__') or len(value) == 0 else value[0])
                            else:
                                values.append(value)
                    batch_values.append(tuple(values))

                # Execute batch insert with executemany for better performance
                cursor.executemany(insert_query, batch_values)
                inserted_count += len(batch_values)

            elapsed = time.time() - start_time
            logger.info(f"Successfully inserted {inserted_count} forecast records into da.forecasts. Skipped {skipped_count} records. Elapsed time: {elapsed:.2f}s")
            print(f"DEBUG: Successfully inserted {inserted_count} forecast records. Elapsed time: {elapsed:.2f}s")
        except Exception as e:
            logger.error(f"Failed to insert forecasts: {e}", exc_info=True)
            print(f"ERROR: Failed to insert forecasts: {e}")
            raise
        finally:
            logger.info("Closing database cursor and connection")
            cursor.close()
            # Close the temporary connection if we created one
            if conn:
                conn.close()

        return inserted_count

    def _create_or_get_version_id(self, version_name: str, user_id: str = "system", location_hierarchy: Optional[str] = None,
                                  location_value: Optional[str] = None, product_hierarchy: Optional[str] = None,
                                  product_value: Optional[str] = None):
        """Create a new version record or get an existing one based on version name and other details."""
        conn = duckdb.connect(self.connection_manager._db_path)
        try:
            # Check if a version with this name already exists
            check_query = """
            SELECT version_id FROM da.forecast_versions
            WHERE version_name = ?
            """
            params = [version_name]

            result = conn.execute(check_query, params).fetchone()

            if result:
                return result[0]  # Return existing version_id
            else:
                # Create a new version record
                import uuid
                from datetime import datetime
                version_id = uuid.uuid4().int & (1<<63)-1  # Generate a 63-bit integer UUID

                insert_query = """
                INSERT INTO da.forecast_versions (version_id, version_name, created_at, location_hierarchy,
                                                location_value, product_hierarchy, product_value, user_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """

                params = [
                    version_id,
                    version_name,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    location_hierarchy,
                    location_value,
                    product_hierarchy,
                    product_value,
                    user_id
                ]

                conn.execute(insert_query, params)
                return version_id
        except Exception as e:
            logger.error(f"Error creating/finding version_id: {e}")
            raise
        finally:
            conn.close()

    def get_forecast_versions(self, user_id: Optional[str] = None) -> List[str]:
        """Get all distinct forecast versions from the forecast_versions table."""
        if not user_id:
            user_id = "system"

        query = "SELECT DISTINCT version_name FROM da.forecast_versions ORDER BY created_at DESC"

        try:
            result_df = self.execute_query(query, user_id=user_id)
            if result_df is not None and not result_df.is_empty():
                return result_df['version_name'].to_list()
            return []
        except Exception as e:
            logger.error(f"Error getting forecast versions: {e}")
            return []

    def get_filtered_sales_actuals_with_forecasts(self, location_col: Optional[str] = None, location_val: Optional[str] = None,
                                                product_col: Optional[str] = None, product_val: Optional[str] = None,
                                                forecast_version: Optional[str] = None, user_id: Optional[str] = None) -> pl.DataFrame:
        """Get combined sales actuals and forecasts data for a specific user, showing both actuals and forecasts for same product and location"""
        if not user_id:
            user_id = "system"

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

        where_conditions = []
        params = []
        if location_col and location_val:
            db_location_col = column_mapping.get(location_col, location_col.lower().replace(' ', '_'))
            where_conditions.append(f"lh.{db_location_col} = ?")
            params.append(location_val)

        if product_col and product_val:
            db_product_col = column_mapping.get(product_col, product_col.lower().replace(' ', '_'))
            where_conditions.append(f"ph.{db_product_col} = ?")
            params.append(product_val)

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        # This CTE identifies the skeys for the filtered products/locations
        skeys_cte = f"""
        WITH FilteredSkeys AS (
            SELECT DISTINCT sa.item_skey, sa.location_skey
            FROM da.sales_actuals sa
            INNER JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
            INNER JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
            WHERE {where_clause}
        )
        """

        # Query for Actuals
        actuals_query = """
        SELECT
            sa.item_skey,
            sa.location_skey,
            sa.sales_date AS "SALES_DATE",
            sa.act_orders_rev AS "Act Orders Rev",
            NULL AS "NHITS",
            lh.country AS "Country",
            lh.region AS "Region",
            lh.area AS "Area",
            ph.catalog_number AS "CatalogNumber",
            ph.franchise AS "Franchise",
            ph.ibp_level_5 AS "IBP Level 5",
            ph.ibp_level_6 AS "IBP Level 6"
        FROM da.sales_actuals sa
        INNER JOIN FilteredSkeys fs ON sa.item_skey = fs.item_skey AND sa.location_skey = fs.location_skey
        INNER JOIN da.product_hierarchy ph ON sa.item_skey = ph.demantra_item_skey
        INNER JOIN da.location_hierarchy lh ON sa.location_skey = lh.location_skey
        """

        # Query for Forecasts
        forecasts_query = """
        SELECT
            f.item_skey,
            f.location_skey,
            f.forecast_date AS "SALES_DATE",
            NULL AS "Act Orders Rev",
            f.forecast_value AS "NHITS",
            lh.country AS "Country",
            lh.region AS "Region",
            lh.area AS "Area",
            ph.catalog_number AS "CatalogNumber",
            ph.franchise AS "Franchise",
            ph.ibp_level_5 AS "IBP Level 5",
            ph.ibp_level_6 AS "IBP Level 6"
        FROM da.forecasts f
        INNER JOIN da.forecast_versions fv ON f.version_id = fv.version_id
        INNER JOIN FilteredSkeys fs ON f.item_skey = fs.item_skey AND f.location_skey = fs.location_skey
        INNER JOIN da.product_hierarchy ph ON f.item_skey = ph.demantra_item_skey
        INNER JOIN da.location_hierarchy lh ON f.location_skey = lh.location_skey
        """

        if forecast_version and forecast_version != 'All':
            forecasts_query += f" WHERE fv.version_name = '{forecast_version}'"

        # Combine with UNION ALL
        full_query = f"""
        {skeys_cte}
        {actuals_query}
        UNION ALL
        {forecasts_query}
        ORDER BY "SALES_DATE"
        """

        return self.execute_query(full_query, tuple(params), user_id)

    def close_user_session(self, user_id: str):
        """Close the database session for a specific user"""
        self.connection_manager.close_user_connection(user_id)
        logger.info(f"Closed database session for user: {user_id}")
        # This line was causing a Pylance error, it seems to be a misplaced docstring or comment
        # """Get statistics about current connections"""
        # The actual return is handled by the next line
        return self.connection_manager.get_connection_stats()

    def cleanup_old_sessions(self, max_age_seconds: int = 3600):
        """Clean up old user sessions"""
        self.connection_manager.cleanup_old_connections(max_age_seconds)
        logger.info("Cleaned up old database sessions")

# Global instance
_enhanced_db_service = None

def get_database_service() -> DatabaseService:
    """Get the global enhanced database service instance"""
    global _enhanced_db_service
    if _enhanced_db_service is None:
        _enhanced_db_service = DatabaseService()
    return _enhanced_db_service
