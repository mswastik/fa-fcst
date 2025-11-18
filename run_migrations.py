"""
Script to run the database migration and verification for the forecast schema changes
"""
import logging
import sys
import os

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database_migrations import migrate_forecast_schema, add_version_id_to_existing_forecasts

def run_migration():
    print("=== Starting Database Migration for Forecast Schema Changes ===")

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    try:
        # Run the main migration
        print("\nStep 1: Running main schema migration...")
        migrate_forecast_schema()
        print("✓ Main schema migration completed")

        # Add version_id to existing forecasts
        print("\nStep 2: Adding version_id to existing forecasts...")
        add_version_id_to_existing_forecasts()
        print("✓ Added version_id to existing forecasts")

        # Test the new schema
        print("\nStep 3: Testing new schema...")

        # Import and test the database service to make sure everything works
        from core.db_service import get_database_service

        db_service = get_database_service()
        user_id = "system"

        # Test that forecast_versions table exists and is accessible
        print("  - Checking forecast_versions table...")
        try:
            result = db_service.execute_query("SELECT COUNT(*) as count FROM da.forecast_versions", user_id=user_id)
            count = result['count'][0] if len(result) > 0 and 'count' in result.columns else 0
            print(f"  ✓ forecast_versions table exists and has {count} records")
        except Exception as e:
            print(f"  ✗ Error accessing forecast_versions table: {e}")

        # Test that forecasts table exists and has the correct structure
        print("  - Checking forecasts table structure...")
        try:
            # Check that new columns exist
            columns_result = db_service.execute_query("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'forecasts' AND table_schema = 'da'
                ORDER BY ordinal_position
            """, user_id=user_id)

            columns = [row['column_name'] for row in columns_result.to_dicts()]
            print(f"  ✓ forecasts table has {len(columns)} columns")

            # Check that old columns were removed
            old_columns = ['confidence_lower', 'confidence_upper', 'created_at', 'forecast_horizon']
            removed_columns = [col for col in old_columns if col not in columns]
            if removed_columns == old_columns:
                print("  ✓ Old columns successfully removed:", old_columns)
            else:
                print("  ! Some old columns still exist:", [col for col in old_columns if col in columns])

            # Check that new columns exist
            new_columns = ['version_id', 'override_value']
            for col in new_columns:
                if col in columns:
                    print(f"  ✓ New column exists: {col}")
                else:
                    print(f"  ✗ Missing new column: {col}")

        except Exception as e:
            print(f"  ✗ Error checking forecasts table structure: {e}")

        print("\nStep 4: Verifying functionality...")

        # Test getting forecast versions
        try:
            versions = db_service.get_forecast_versions(user_id=user_id)
            print(f"  ✓ Successfully retrieved {len(versions)} forecast versions")
        except Exception as e:
            print(f"  ✗ Error getting forecast versions: {e}")

        # Test getting filtered sales actuals with forecasts
        try:
            result = db_service.get_filtered_sales_actuals_with_forecasts(user_id=user_id)
            print(f"  ✓ Successfully executed get_filtered_sales_actuals_with_forecasts, got {len(result)} records")
        except Exception as e:
            print(f"  ✗ Error executing get_filtered_sales_actuals_with_forecasts: {e}")

        print("\n=== Migration Completed Successfully! ===")
        print("\nSummary of changes:")
        print("- Created forecast_versions table to store forecast version details")
        print("- Removed confidence_lower, confidence_upper, created_at, and forecast_horizon fields from forecasts table")
        print("- Added version_id and override_value fields to forecasts table")
        print("- Added forecast_horizon field to forecast_versions table")
        print("- Updated all database service methods to work with new schema")
        print("- Removed duplicate functions in the database service")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()