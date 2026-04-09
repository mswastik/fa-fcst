"""
Database migrations for forecast schema changes
Comprehensive migration system that initializes all required database tables
"""
import duckdb
import logging

logger = logging.getLogger(__name__)

def get_database_connection(db_path: str = "fcst.duckdb"):
    """Get a database connection for migrations"""
    return duckdb.connect(db_path)

def initialize_database_schema(db_path: str = "fcst.duckdb"):
    """Initialize the complete database schema with all required tables"""
    conn = get_database_connection(db_path)
    
    try:
        # Create schema
        conn.sql("CREATE SCHEMA IF NOT EXISTS da")
        logger.info("Created 'da' schema")

        # Create sales_actuals table
        create_sales_actuals_table_sql = """
        CREATE TABLE IF NOT EXISTS da.sales_actuals (
            item_skey BIGINT,
            location_skey BIGINT,
            sales_date DATE,
            asp_final_rev DOUBLE,
            act_orders_rev DOUBLE,
            act_orders_rev_val DOUBLE,
            fcst_df_final_rev DOUBLE,
            l0_df_final_rev DOUBLE,
            l1_df_final_rev DOUBLE,
            l2_df_final_rev DOUBLE,
            fcst_df_final_rev_val DOUBLE,
            fcst_stat_prelim_rev DOUBLE,
            fcst_stat_final_rev DOUBLE,
            l0_stat_final_rev DOUBLE,
            l1_stat_final_rev DOUBLE,
            l2_stat_final_rev DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        conn.execute(create_sales_actuals_table_sql)
        logger.info("Created sales_actuals table")

        # Create product_hierarchy table
        create_product_hierarchy_table_sql = """
        CREATE TABLE IF NOT EXISTS da.product_hierarchy (
            demantra_item_skey BIGINT PRIMARY KEY,
            business_sector VARCHAR,
            business_unit VARCHAR,
            franchise VARCHAR,
            product_line VARCHAR,
            ibp_level_5 VARCHAR,
            ibp_level_6 VARCHAR,
            ibp_level_7 VARCHAR,
            catalog_number VARCHAR,
            uom VARCHAR,
            pack_content VARCHAR,
            current VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        conn.execute(create_product_hierarchy_table_sql)
        logger.info("Created product_hierarchy table")

        # Create location_hierarchy table
        create_location_hierarchy_table_sql = """
        CREATE TABLE IF NOT EXISTS da.location_hierarchy (
            location_skey BIGINT PRIMARY KEY,
            country VARCHAR,
            region VARCHAR,
            area VARCHAR,
            selling_division VARCHAR,
            stryker_group_region VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        conn.execute(create_location_hierarchy_table_sql)
        logger.info("Created location_hierarchy table")

        # Create forecasts table
        create_forecasts_table_sql = """
        CREATE TABLE IF NOT EXISTS da.forecasts (
            forecast_id BIGINT PRIMARY KEY,
            item_skey BIGINT,
            location_skey BIGINT,
            forecast_date DATE,
            model_type VARCHAR,
            forecast_value DOUBLE,
            model_version VARCHAR,
            version_id BIGINT,
            override_value DOUBLE
        );
        """
        conn.execute(create_forecasts_table_sql)
        logger.info("Created forecasts table")

        # Create forecast_versions table
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

        # Create causal_factors table
        create_causal_factors_table_sql = """
        CREATE TABLE IF NOT EXISTS da.causal_factors (
            location_skey BIGINT,
            item_skey BIGINT,
            forecast_date DATE,
            version_id BIGINT,
            causal_factor_1 DOUBLE,
            causal_factor_2 DOUBLE,
            PRIMARY KEY (location_skey, item_skey, forecast_date, version_id)
        );
        """
        conn.execute(create_causal_factors_table_sql)
        logger.info("Created causal_factors table")

        conn.commit()
        logger.info("Database schema initialization completed successfully")

    except Exception as e:
        logger.error(f"Error initializing database schema: {e}")
        raise
    finally:
        conn.close()

    return True

def migrate_forecast_schema(db_path: str = "fcst.duckdb"):
    """Migrate the forecast schema to the new structure"""
    # First initialize the complete schema to ensure all tables exist
    initialize_database_schema(db_path)
    
    conn = get_database_connection(db_path)

    try:
        # Create indexes for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_version_id ON da.forecasts(version_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_item_location ON da.forecasts(item_skey, location_skey);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_date ON da.forecasts(forecast_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecast_versions_created_at ON da.forecast_versions(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_override ON da.forecasts(override_value);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_causal_factors_version_id ON da.causal_factors(version_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_causal_factors_item_location ON da.causal_factors(item_skey, location_skey);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_causal_factors_date ON da.causal_factors(forecast_date);")
        logger.info("Created indexes for improved performance")
        
        logger.info("Forecast schema migration completed successfully")
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        raise
    finally:
        conn.close()

def add_version_id_to_existing_forecasts(db_path: str = "fcst.duckdb"):
    """Add version_id to any existing forecast records that might not have it"""
    conn = get_database_connection(db_path)

    try:
        # Update existing records to have a version_id if they don't already
        # Create a default version record if needed
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
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating records with version_id: {e}")
    finally:
        conn.close()

def run_all_migrations(db_path: str = "fcst.duckdb"):
    """Run all database migrations in the correct order"""
    print("=== Starting Database Migration ===")
    
    try:
        # Step 1: Initialize the complete database schema
        print("\nStep 1: Initializing database schema with all required tables...")
        initialize_database_schema(db_path)
        print("✓ Database schema initialized successfully")

        # Step 2: Run forecast schema migration (adds indexes)
        print("\nStep 2: Running forecast schema migration...")
        migrate_forecast_schema(db_path)
        print("✓ Forecast schema migration completed")

        # Step 3: Add version_id to existing forecasts
        print("\nStep 3: Adding version_id to existing forecasts...")
        add_version_id_to_existing_forecasts(db_path)
        print("✓ Added version_id to existing forecasts")

        print("\n=== All Migrations Completed Successfully! ===")
        print("\nSummary of tables created:")
        print("- da.sales_actuals")
        print("- da.product_hierarchy")
        print("- da.location_hierarchy")
        print("- da.forecasts")
        print("- da.forecast_versions")
        print("- da.causal_factors")
        
        return True
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    run_all_migrations()
    print("\nDatabase migration completed!")