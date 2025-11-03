from arrow_odbc import read_arrow_batches_from_odbc
from datetime import datetime
from dateutil.relativedelta import relativedelta
import polars as pl
import os
import pyodbc
#from utils import ErrorHandler
import duckdb
import json

drivers = sorted(pyodbc.drivers())
d = [i for i in drivers if i.find('ODBC Driver') != -1]

# Get connection manager to access the DuckDB instance
from .duckdb_connection_manager import get_duckdb_connection_manager

# Global variable to store loaded credentials
_credentials = None

def _load_credentials():
    """
    Load credentials from JSON file once and cache them.
    Returns the credentials dictionary.
    """
    global _credentials
    
    # If credentials are already loaded, return them
    if _credentials is not None:
        return _credentials
    
    # Get the project root directory (two levels up from core)
    from pathlib import Path
    project_root = Path(__file__).parent.parent
    credentials_file = project_root / "config" / "credentials.json"
    
    # Load credentials from file
    with open(credentials_file, 'r') as f:
        _credentials = json.load(f)
    
    return _credentials

def _get_database_config():
    """
    Get database configuration from loaded credentials.
    Returns a dictionary with server, database_name, username, and password.
    """
    credentials = _load_credentials()
    return credentials.get("database", {})

def _get_database_connection_params():
    """
    Get database connection parameters.
    Returns server, database, username, and password as a tuple.
    """
    db_config = _get_database_config()
    server = db_config.get("server")
    database = db_config.get("database_name")
    username = db_config.get("username")
    password = db_config.get("password")
    return server, database, username, password

def fetch_and_save_sales_actuals(user_id: str = "system", incremental: bool = False):
    """
    Fetch sales actuals data using arrow_odbc and save to DuckDB da.sales_actuals table
    with bucketed approach to handle memory allocation issues
    """
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    
    # Get database connection
    conn_manager = get_duckdb_connection_manager()
    
    # Create connection if it doesn't exist
    try:
        conn = conn_manager.get_user_connection(user_id)
    except ValueError:
        # Connection doesn't exist, create it
        conn_manager.create_user_connection(user_id)
        conn = conn_manager.get_user_connection(user_id)
    
    # Get database connection parameters from credentials
    server, database, username, password = _get_database_connection_params()
    
    # Create connection string
    connection_string = (
        f"Driver={{{d[-1] if d else 'ODBC Driver 18 for SQL Server'}}};"
        f"Server={server};database={database};"
        f"UID={username};PWD={password}"
    )
    
    print("Fetching sales actuals data with bucketed approach...")
    
    # Determine date range based on incremental flag
    if incremental:
        # For incremental updates: from today to 24 months ahead
        start_date = datetime.today().date() - relativedelta(months=3)
        end_date = start_date + relativedelta(months=36)
        print(f"Running incremental update for date range: {start_date} to {end_date}")
    else:
        # For full data load: from 37 months ago to 24 months ahead
        start_date = datetime.today().date() - relativedelta(months=37)
        end_date = datetime.today().date() + relativedelta(months=36)
        print(f"Running full data load for date range: {start_date} to {end_date}")
    
    # Calculate the total date range span in months
    total_months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        total_months -= 1  # Adjust if the day of end_date is earlier
    
    # Determine bucket size (max 12 months per bucket)
    bucket_size_months = min(12, total_months)
    if bucket_size_months <= 0:
        bucket_size_months = 1
    
    # Process data in buckets
    current_start = start_date
    processed_buckets = 0
    
    # Handle deletion before inserting new data
    if incremental:
        # For incremental updates, delete only the overlapping period
        conn.execute(f"""
            DELETE FROM da.sales_actuals 
            WHERE sales_date BETWEEN '{start_date.strftime('%Y-%m-%d')}' 
            AND '{end_date.strftime('%Y-%m-%d')}'
        """)
        print(f"Deleted {start_date} to {end_date} period for incremental update")
    else:
        # For full data load, delete all existing data
        conn.execute("DELETE FROM da.sales_actuals")
        print("Deleted all existing sales_actuals data")
    
    while current_start < end_date:
        # Calculate end date for this bucket
        current_end = current_start + relativedelta(months=bucket_size_months)
        
        # Make sure we don't exceed the overall end date
        if current_end > end_date:
            current_end = end_date
        
        print(f"Processing bucket {processed_buckets + 1}: {current_start} to {current_end}")
        
        # Create query for this bucket
        bucket_query = f'''
            SELECT
                s.[item_skey],[Location_skey],[SALES_DATE],
                AVG([ASP_Final_Rev]) [asp_final_rev], 
                SUM([Act_Orders_Rev]) [act_orders_rev],
                SUM([Act_Orders_Rev_Val]) [act_orders_rev_val],
                SUM(Fcst_DF_Final_Rev) as [fcst_df_final_rev], 
                SUM(s."L0_DF_Final_Rev") as [l0_df_final_rev],
                SUM(s."L1_DF_Final_Rev") as [l1_df_final_rev], 
                SUM(s.[L2_DF_Final_Rev]) as [l2_df_final_rev],
                SUM(Fcst_DF_Final_Rev_Val) as [fcst_df_final_rev_val],
                SUM(Fcst_Stat_Prelim_Rev) as [fcst_stat_prelim_rev],
                SUM(Fcst_Stat_Final_Rev) as [fcst_stat_final_rev],
                SUM(s."L0_Stat_Final_Rev") as [l0_stat_final_rev],
                SUM(s."L1_Stat_Final_Rev") as [l1_stat_final_rev], 
                SUM(s.[L2_Stat_Final_Rev]) as [l2_stat_final_rev] 
                
            FROM [Envision].[Demantra_CLD_Fact_Sales] s
            JOIN [Envision].[DIM_Demantra_CLD_products] p
            ON s.item_skey = p.demantra_item_skey AND p.[Current] = 'True'
            JOIN [Envision].[Dim_DEMANTRA_CLD_MDP_Matrix] m
            ON s.MDP_Key = m.MDP_Key

            WHERE
                [SALES_DATE] BETWEEN '{current_start.strftime('%Y-%m-%d')}' AND '{current_end.strftime('%Y-%m-%d')}' AND
                s.[Location_skey] IN (24,98,120)
                
            GROUP BY
                s.[item_skey],s.[Location_skey],s.[SALES_DATE]
        '''
        
        try:
            print(f"Starting to read batches for bucket {current_start} to {current_end}")
            reader = read_arrow_batches_from_odbc(query=bucket_query, connection_string=connection_string)
            batch_count = 0
            total_rows_processed = 0
            
            for batch in reader:
                # Process each batch directly without accumulating in memory
                print(f"Processing batch {batch_count + 1}")
                batch_df = pl.from_arrow(batch)
                current_batch_rows = len(batch_df)
                total_rows_processed += current_batch_rows
                print(f"Batch {batch_count + 1} has {current_batch_rows} rows")
                
                # Convert SALES_DATE to proper datetime format if needed
                if 'SALES_DATE' in batch_df.columns:
                    batch_df = batch_df.with_columns(
                        pl.col('SALES_DATE').cast(pl.Datetime).dt.replace_time_zone(None)
                    )
                
                # Prepare the data for insertion into DuckDB
                # Rename columns to match DuckDB schema
                rename_mapping = {
                    'SALES_DATE': 'sales_date',
                    'item_skey': 'item_skey',
                    'Location_skey': 'location_skey',
                    'asp_final_rev': 'asp_final_rev',
                    'act_orders_rev': 'act_orders_rev',
                    'act_orders_rev_val': 'act_orders_rev_val',
                    'fcst_df_final_rev': 'fcst_df_final_rev',
                    'l0_df_final_rev': 'l0_df_final_rev',
                    'l1_df_final_rev': 'l1_df_final_rev',
                    'l2_df_final_rev': 'l2_df_final_rev',
                    'fcst_df_final_rev_val': 'fcst_df_final_rev_val',
                    'fcst_stat_prelim_rev': 'fcst_stat_prelim_rev',
                    'fcst_stat_final_rev': 'fcst_stat_final_rev',
                    'l0_stat_final_rev': 'l0_stat_final_rev',
                    'l1_stat_final_rev': 'l1_stat_final_rev',
                    'l2_stat_final_rev': 'l2_stat_final_rev'
                }
                
                # Rename columns that exist in the dataframe
                for old_name, new_name in rename_mapping.items():
                    if old_name in batch_df.columns:
                        batch_df = batch_df.rename({old_name: new_name})
                
                # Ensure numeric columns are properly typed to avoid decimal casting errors
                numeric_columns = ['asp_final_rev', 'act_orders_rev', 'act_orders_rev_val', 
                                  'fcst_df_final_rev', 'l0_df_final_rev', 'l1_df_final_rev', 
                                  'l2_df_final_rev', 'fcst_df_final_rev_val', 'fcst_stat_prelim_rev',
                                  'fcst_stat_final_rev', 'l0_stat_final_rev', 'l1_stat_final_rev', 
                                  'l2_stat_final_rev']
                
                for col in numeric_columns:
                    if col in batch_df.columns:
                        # Convert to float to avoid decimal precision issues
                        batch_df = batch_df.with_columns([
                            pl.col(col).cast(pl.Float64, strict=False).alias(col)
                        ])
                
                if not batch_df.is_empty():
                    # Write this batch directly to DuckDB
                    batch_pandas = batch_df.to_pandas()
                    
                    # Register the DataFrame as a temporary table
                    conn.register("batch_pandas", batch_pandas)
                    
                    # Insert the data into the DuckDB table
                    conn.execute("""
                        INSERT INTO da.sales_actuals 
                        (item_skey, location_skey, sales_date, asp_final_rev, act_orders_rev, act_orders_rev_val,
                         fcst_df_final_rev, l0_df_final_rev, l1_df_final_rev, l2_df_final_rev, 
                         fcst_df_final_rev_val, fcst_stat_prelim_rev, fcst_stat_final_rev, 
                         l0_stat_final_rev, l1_stat_final_rev, l2_stat_final_rev, created_at, updated_at)
                        SELECT 
                            item_skey, location_skey, sales_date, asp_final_rev, act_orders_rev, act_orders_rev_val,
                            fcst_df_final_rev, l0_df_final_rev, l1_df_final_rev, l2_df_final_rev, 
                            fcst_df_final_rev_val, fcst_stat_prelim_rev, fcst_stat_final_rev, 
                            l0_stat_final_rev, l1_stat_final_rev, l2_stat_final_rev, 
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        FROM batch_pandas
                    """)
                    # Unregister the temporary table
                    conn.unregister("batch_pandas")
                    print(f"Inserted batch {batch_count + 1} with {current_batch_rows} rows to DuckDB")
                
                batch_count += 1
            
            print(f"Retrieved data from bucket {current_start} to {current_end} in {batch_count} batches")
            print(f"Total rows processed in this bucket: {total_rows_processed}")
            
            processed_buckets += 1
            print(f"Completed bucket {processed_buckets}.")
            
        except Exception as e:
            print(f"Error processing bucket {current_start} to {current_end}: {e}")
            import traceback
            traceback.print_exc()
            continue  # Continue with next bucket even if one fails
        
        # Move to next bucket
        current_start = current_end + relativedelta(days=1)
    
    print(f"Successfully processed {processed_buckets} buckets")
    
    # Return an empty DataFrame since we're now writing data directly to DuckDB
    return pl.DataFrame()


def fetch_and_save_product_hierarchy(user_id: str = "system"):
    """
    Fetch product hierarchy data using arrow_odbc and save to DuckDB da.product_hierarchy table
    """
    # Get database connection
    conn_manager = get_duckdb_connection_manager()
    
    # Create connection if it doesn't exist
    try:
        conn = conn_manager.get_user_connection(user_id)
    except ValueError:
        # Connection doesn't exist, create it
        conn_manager.create_user_connection(user_id)
        conn = conn_manager.get_user_connection(user_id)
    
    query = '''
    SELECT
        [demantra_item_skey],[Business_Sector] [business_sector],[Franchise],[Business_Unit] [business_unit],[Product_Line] [product_line],[IBP_Level_5] [ibp_level_5],[IBP_Level_6] [ibp_level_6],[IBP_Level_7] [ibp_level_7],
        [CatalogNumber] [catalog_number],[xx_uom_conversion] as uom,[PackContent] AS [pack_content], [current]
        
    FROM [Envision].[DIM_Demantra_CLD_products]
    WHERE [current] = 'True'
    '''
    
    # Get database connection parameters from credentials
    server, database, username, password = _get_database_connection_params()
    
    # Create connection string
    connection_string = (
        f"Driver={{{d[-1] if d else 'ODBC Driver 18 for SQL Server'}}};"
        f"Server={server};database={database};"
        f"UID={username};PWD={password}"
    )
    
    print("Fetching product hierarchy data...")
    try:
        reader = read_arrow_batches_from_odbc(query=query, connection_string=connection_string)
        df = pl.DataFrame()
        
        for batch in reader:
            batch_df = pl.from_arrow(batch)
            df = pl.concat([df, batch_df])
        
        print(f"Retrieved {len(df)} records from product hierarchy")
        
        # Prepare the data for insertion into DuckDB
        # Rename columns to match DuckDB schema
        rename_mapping = {
            'demantra_item_skey': 'demantra_item_skey',
            'business_sector': 'business_sector',
            'business_unit': 'business_unit',
            'franchise': 'franchise',
            'product_line': 'product_line',
            'ibp_level_5': 'ibp_level_5',
            'ibp_level_6': 'ibp_level_6',
            'ibp_level_7': 'ibp_level_7',
            'catalog_number': 'catalog_number',
            'uom': 'uom',
            'pack_content': 'pack_content',
        }
        
        # Rename columns that exist in the dataframe
        for old_name, new_name in rename_mapping.items():
            if old_name in df.columns:
                df = df.rename({old_name: new_name})
        
        # Remove duplicates based on demantra_item_skey to avoid constraint violations
        # Use 'last' to keep the most recent record in case of duplicates
        if 'demantra_item_skey' in df.columns:
            initial_count = len(df)
            df = df.unique(subset=['demantra_item_skey'], keep='last')
            final_count = len(df)
            if initial_count != final_count:
                print(f"Removed {initial_count - final_count} duplicate records based on demantra_item_skey")
        
        # Write to DuckDB product_hierarchy table
        if not df.is_empty():
            df_pandas = df.to_pandas()
            
            # First, clear existing data
            conn.execute("DELETE FROM da.product_hierarchy")
            
            # Register the DataFrame as a temporary table
            conn.register("temp_product_hierarchy", df_pandas)
            
            try:
                # Insert the deduplicated data into the product_hierarchy table
                conn.execute("""
                    INSERT INTO da.product_hierarchy 
                    (demantra_item_skey, business_sector, business_unit, franchise, product_line, 
                     ibp_level_5, ibp_level_6, ibp_level_7, catalog_number, uom, pack_content, 
                     created_at, updated_at)
                    SELECT 
                        demantra_item_skey, business_sector, business_unit, franchise, product_line, 
                        ibp_level_5, ibp_level_6, ibp_level_7, catalog_number, uom, pack_content,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    FROM temp_product_hierarchy
                """)
            finally:
                # Unregister the temporary table
                conn.unregister("temp_product_hierarchy")
        
        print(f"Successfully inserted {len(df)} records into da.product_hierarchy table")
        return df
        
    except Exception as e:
        print(f"Error fetching product hierarchy: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_and_save_location_hierarchy(user_id: str = "system"):
    """
    Fetch location hierarchy data using arrow_odbc and save to DuckDB da.location_hierarchy table
    """
    # Get database connection
    conn_manager = get_duckdb_connection_manager()
    
    # Create connection if it doesn't exist
    try:
        conn = conn_manager.get_user_connection(user_id)
    except ValueError:
        # Connection doesn't exist, create it
        conn_manager.create_user_connection(user_id)
        conn = conn_manager.get_user_connection(user_id)
    
    query = '''
        SELECT DISTINCT
            [Location_skey] as [location_skey], [SellingDivision] as [selling_division],[COUNTRY_GROUP] 'area',[StrykerGroupRegion] as [stryker_group_region],[Region] [region],[Country] as [country]
                
        FROM [Envision].[DIM_Demantra_CLD_DemantraLocation] l
     '''
    
    # Get database connection parameters from credentials
    server, database, username, password = _get_database_connection_params()
    
    # Create connection string
    connection_string = (
        f"Driver={{{d[-1] if d else 'ODBC Driver 18 for SQL Server'}}};"
        f"Server={server};database={database};"
        f"UID={username};PWD={password}"
    )
    
    print("Fetching location hierarchy data...")
    try:
        reader = read_arrow_batches_from_odbc(query=query, connection_string=connection_string)
        df = pl.DataFrame()
        
        for batch in reader:
            batch_df = pl.from_arrow(batch)
            df = pl.concat([df, batch_df])
        
        print(f"Retrieved {len(df)} records from location hierarchy")
        
        # Prepare the data for insertion into DuckDB
        # Rename columns to match DuckDB schema
        rename_mapping = {
            'location_skey': 'location_skey',
            'selling_division': 'selling_division',
            'area': 'area',
            'stryker_group_region': 'stryker_group_region',
            'region': 'region',
            'country': 'country',
        }
        
        # Rename columns that exist in the dataframe
        for old_name, new_name in rename_mapping.items():
            if old_name in df.columns:
                df = df.rename({old_name: new_name})
        
        # Write to DuckDB location_hierarchy table
        if not df.is_empty():
            df_pandas = df.to_pandas()
            
            # Insert the data into the DuckDB table (overwrite existing)
            conn.execute("DELETE FROM da.location_hierarchy")
            conn.register("df_pandas", df_pandas)  # Register the DataFrame as a temporary table
            conn.execute("""
                INSERT INTO da.location_hierarchy 
                (location_skey, selling_division, area, stryker_group_region, region, country, 
                 created_at, updated_at)
                SELECT 
                    location_skey, selling_division, area, stryker_group_region, region, country,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM df_pandas
            """)
            conn.unregister("df_pandas")  # Unregister the temporary table
        
        print(f"Successfully inserted {len(df)} records into da.location_hierarchy table")
        return df
        
    except Exception as e:
        print(f"Error fetching location hierarchy: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_all_data(user_id: str = "system", incremental: bool = False):
    """
    Fetch and save all data to DuckDB tables
    """
    if incremental:
        print("Fetching and saving incremental data to DuckDB...")
    else:
        print("Fetching and saving all data to DuckDB...")
    
    # Fetch and save sales actuals
    sales_df = fetch_and_save_sales_actuals(user_id, incremental=incremental)
    
    # For product and location hierarchies, we always do full refresh since they don't change frequently
    # Fetch and save product hierarchy
    product_df = fetch_and_save_product_hierarchy(user_id)
    
    # Fetch and save location hierarchy
    location_df = fetch_and_save_location_hierarchy(user_id)
    
    print("All data fetching and saving completed!")
    
    return {
        'sales_actuals': sales_df,
        'product_hierarchy': product_df,
        'location_hierarchy': location_df
    }


def fetch_incremental_sales_actuals(user_id: str = "system"):
    """
    Fetch and save only the incremental sales actuals data (next 24 months from today)
    """
    print("Fetching and saving incremental sales actuals data to DuckDB...")
    
    # Fetch and save sales actuals incrementally
    sales_df = fetch_and_save_sales_actuals(user_id, incremental=True)
    
    print("Incremental sales actuals data fetching and saving completed!")
    
    return {
        'sales_actuals': sales_df
    }


def test_connection(server: str = None, database: str = None, username: str = None, password: str = None):
    """
    Test the source database connection
    """
    # Get database connection parameters from credentials
    server, database, username, password = _get_database_connection_params()
    
    # Create connection string
    connection_string = (
        f"Driver={{{d[-1] if d else 'ODBC Driver 18 for SQL Server'}}};"
        f"Server={server};database={database};"
        f"UID={username};PWD={password}"
    )
    
    try:
        # Create a simple test query
        test_query = "SELECT 1 as test"
        reader = read_arrow_batches_from_odbc(query=test_query, connection_string=connection_string)
        
        for batch in reader:
            result = pl.from_arrow(batch)
            print(f"Connection test successful: {result}")
            return True
    except Exception as e:
        print(f"Connection test failed: {e}")
        return False