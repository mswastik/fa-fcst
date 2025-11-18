"""
Database migrations for forecast schema changes
"""
import duckdb
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def get_database_connection(db_path: str = "fcst.duckdb"):
    """Get a database connection for migrations"""
    return duckdb.connect(db_path)

def migrate_forecast_schema(db_path: str = "fcst.duckdb"):
    """Migrate the forecast schema to the new structure"""
    conn = get_database_connection(db_path)

    # Create the new forecast_versions table
    create_forecast_versions_table_sql = """
    CREATE TABLE IF NOT EXISTS da.forecast_versions (
        version_id BIGINT PRIMARY KEY,
        version_name VARCHAR,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        location_hierarchy VARCHAR,
        location_value VARCHAR,
        product_hierarchy VARCHAR,
        product_value VARCHAR,
        user_name VARCHAR,
        forecast_horizon BIGINT,
        description VARCHAR
    );
    """

    conn.execute(create_forecast_versions_table_sql)
    logger.info("Created forecast_versions table")

    # Add the new version_id column to forecasts table first
    try:
        conn.execute("ALTER TABLE da.forecasts ADD COLUMN version_id BIGINT;")
        logger.info("Added version_id column to forecasts table")
    except Exception as e:
        # If column already exists, continue
        if "already exists" in str(e):
            logger.info("version_id column already exists in forecasts table")
        else:
            logger.error(f"Error adding version_id column: {e}")

    # Add the new override_value column to forecasts table
    try:
        conn.execute("ALTER TABLE da.forecasts ADD COLUMN override_value DOUBLE;")
        logger.info("Added override_value column to forecasts table")
    except Exception as e:
        # If column already exists, continue
        if "already exists" in str(e):
            logger.info("override_value column already exists in forecasts table")
        else:
            logger.error(f"Error adding override_value column: {e}")

    # Add the forecast_horizon column to forecast_versions table if it doesn't exist already
    try:
        conn.execute("ALTER TABLE da.forecast_versions ADD COLUMN forecast_horizon BIGINT;")
        logger.info("Added forecast_horizon column to forecast_versions table")
    except Exception as e:
        # If column already exists, continue
        if "already exists" in str(e):
            logger.info("forecast_horizon column already exists in forecast_versions table")
        else:
            logger.error(f"Error adding forecast_horizon column: {e}")

    # Drop all indexes on the forecasts table to be safe
    try:
        indexes = conn.execute(f"""
            SELECT index_name
            FROM duckdb_indexes()
            WHERE table_name = 'forecasts' AND schema_name = 'da'
        """).fetchall()

        for (index_name,) in indexes:
            conn.execute(f"DROP INDEX da.{index_name};")
            logger.info(f"Dropped index {index_name} from forecasts table")

    except Exception as e:
        logger.info(f"Could not drop indexes, they might not exist: {e}")

    # Remove the specified columns from the forecasts table
    # DuckDB supports ALTER TABLE DROP COLUMN
    columns_to_drop = ['confidence_lower', 'confidence_upper', 'created_at', 'forecast_horizon']

    for col in columns_to_drop:
        try:
            # Check if the column exists first
            result = conn.execute(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'forecasts'
                AND column_name = '{col}'
            """).fetchall()

            if result:
                conn.execute(f"ALTER TABLE da.forecasts DROP COLUMN {col};")
                logger.info(f"Dropped column {col} from forecasts table")
            else:
                logger.info(f"Column {col} does not exist in forecasts table, skipping")
        except Exception as e:
            logger.error(f"Error dropping column {col}: {e}")

    # Create indexes for performance
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_version_id ON da.forecasts(version_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_item_location ON da.forecasts(item_skey, location_skey);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_date ON da.forecasts(forecast_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forecast_versions_created_at ON da.forecast_versions(created_at);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_override ON da.forecasts(override_value);")

    logger.info("Created indexes for improved performance")

    conn.close()
    logger.info("Forecast schema migration completed successfully")

def add_version_id_to_existing_forecasts(db_path: str = "fcst.duckdb"):
    """Add version_id to any existing forecast records that might not have it"""
    conn = get_database_connection(db_path)

    # Update existing records to have a version_id if they don't already
    # Create a default version record if needed
    try:
        # Check if there are records without version_id
        check_sql = """
        SELECT COUNT(*) as count
        FROM da.forecasts
        WHERE version_id IS NULL OR version_id = 0;
        """
        result = conn.execute(check_sql).fetchone()

        if result and result[0] > 0:
            # Create a default version if one doesn't exist
            conn.execute("""
            INSERT OR IGNORE INTO da.forecast_versions (version_id, version_name, user_name, description)
            VALUES (1, 'Default Version', 'system', 'Default forecast version for legacy records');
            """)

            # Update records without version_id to use the default
            conn.execute("""
            UPDATE da.forecasts
            SET version_id = 1
            WHERE version_id IS NULL OR version_id = 0;
            """)

            logger.info(f"Updated {result[0]} records with default version_id")
    except Exception as e:
        logger.error(f"Error updating records with version_id: {e}")

    conn.close()

if __name__ == "__main__":
    migrate_forecast_schema()
    add_version_id_to_existing_forecasts()
    print("Database migration completed!")