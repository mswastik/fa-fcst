"""
Script to run all database migrations and initialize the database
This is the main entry point for database setup after a fresh install
"""
import logging
import sys
import os

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database_migrations import run_all_migrations

def run_migration():
    print("=== Starting Database Migration and Setup ===")

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    try:
        # Run all migrations (this will create all tables and indexes)
        success = run_all_migrations()
        
        if not success:
            print("\n✗ Migration failed!")
            sys.exit(1)

        # Test the database setup
        print("\nStep 4: Testing database setup...")

        # Import and test the database service to make sure everything works
        from core.db_service import get_database_service

        db_service = get_database_service()
        user_id = "system"

        # Test that all tables exist
        tables_to_check = [
            'forecast_versions',
            'forecasts',
            'sales_actuals',
            'product_hierarchy',
            'location_hierarchy',
            'causal_factors'
        ]
        
        for table in tables_to_check:
            print(f"  - Checking {table} table...")
            try:
                result = db_service.execute_query(f"SELECT COUNT(*) as count FROM da.{table}", user_id=user_id)
                count = result['count'][0] if len(result) > 0 and 'count' in result.columns else 0
                print(f"  ✓ {table} table exists and has {count} records")
            except Exception as e:
                print(f"  ✗ Error accessing {table} table: {e}")

        print("\n=== Migration and Database Setup Completed Successfully! ===")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
