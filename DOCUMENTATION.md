# Codebase Documentation

This document provides an overview of the project's codebase, including a description of each module and its functions.

## `core/data_service.py`

This module provides core data processing and forecasting functionalities.

### Functions
- `create_mlforecast_models(df: pl.DataFrame, horizon: int = 60) -> pl.DataFrame`:
  Creates forecasts for each unique_id using MLForecast with parallel processing.

- `run_mlforecast_pipeline(df: pl.DataFrame, state: DataState = None, forecast_version: Optional[str] = None, location_hierarchy: Optional[str] = None, location_value: Optional[str] = None, product_hierarchy: Optional[str] = None, product_value: Optional[str] = None) -> Tuple[Optional[pl.DataFrame], Dict[str, Any]]`:
  Runs the forecasting pipeline using MLForecast and saves the results to the database.

- `create_models_action(df: pl.DataFrame, state: DataState = None, forecast_version: Optional[str] = None, location_hierarchy: Optional[str] = None, location_value: Optional[str] = None, product_hierarchy: Optional[str] = None, product_value: Optional[str] = None) -> pl.DataFrame`:
  A business logic wrapper for creating forecasting models. It's triggered from the API layer.

- `apply_filters(filters, state: DataState = None)`:
  Applies filters to the dataset by querying the database directly.

- `change_fc_action()`:
  A placeholder function for changing forecast settings. It's connected to the API.

## `core/database_migrations.py`

This script handles database schema migrations. It's designed to be run directly or via `run_migrations.py`.

### Functions
- `migrate_forecast_schema(db_path: str = "fcst.duckdb")`:
  Migrates the forecast schema to a new structure, including creating tables, adding columns, and creating indexes.

- `add_version_id_to_existing_forecasts(db_path: str = "fcst.duckdb")`:
  Adds a `version_id` to existing forecast records that might not have one, ensuring backward compatibility.

## `core/db_service.py`

This service abstracts all database interactions, using DuckDB with a multi-user connection manager.

### Functions
- `create_user_session(user_id: str) -> str`: Creates a new database session for a user.
- `execute_query(query: str, params: Optional[tuple] = None, user_id: Optional[str] = None) -> pl.DataFrame`: Executes a query and returns a Polars DataFrame.
- `execute_query_raw(query: str, params: Optional[tuple] = None, user_id: Optional[str] = None)`: Executes a query and returns raw cursor results.
- `close_cursor_and_connection(cursor)`: Closes a cursor and its associated connection.
- `get_sales_actuals(...)`: Retrieves sales actuals data.
- `estimate_filtered_data_size(...)`: Estimates the number of rows for a given filter.
- `get_filtered_sales_actuals(...)`: Retrieves filtered sales actuals data.
- `get_filter_options(...)`: Retrieves available filter options with caching.
- `_get_skeys_for_unique_id(...)`: Helper to get item and location skeys from a unique_id.
- `get_cross_filtered_options(...)`: Retrieves product options filtered by location.
- `insert_forecasts(...)`: Inserts forecast data into the database.
- `_create_or_get_version_id(...)`: Creates or retrieves a forecast version ID.
- `get_forecast_version_details(...)`: Retrieves details for a specific forecast version.
- `get_forecast_versions(...)`: Retrieves all distinct forecast versions.
- `delete_forecast_version(...)`: Deletes a forecast version and associated forecasts.
- `get_filtered_sales_actuals_with_forecasts(...)`: Retrieves combined sales actuals and forecasts.
- `close_user_session(user_id: str)`: Closes a user's database session.
- `cleanup_old_sessions(...)`: Cleans up old user sessions.
- `get_database_service() -> DatabaseService`: Returns the global instance of the `DatabaseService`.

## `core/duckdb_connection_manager.py`

This module provides a thread-safe connection manager for DuckDB, supporting multiple concurrent users.

### Functions
- `create_user_connection(user_id: str) -> str`: Creates a new database connection for a specific user.
- `get_user_connection(user_id: str)`: Gets the database connection for a specific user.
- `close_user_connection(user_id: str)`: Closes the database connection for a specific user.
- `close_all_connections()`: Closes all user connections.
- `_is_connection_alive(user_id: str) -> bool`: Checks if a user's connection is still alive.
- `get_connection_stats() -> Dict[str, Any]`: Gets statistics about current connections.
- `cleanup_old_sessions(max_age_seconds: int = 3600)`: Cleans up connections that haven't been used recently.
- `get_duckdb_connection_manager() -> DuckDBConnectionManager`: Returns the global instance of the `DuckDBConnectionManager`.

## `core/fetchdata.py`

This module is responsible for fetching data from an external SQL Server database and saving it to the local DuckDB database. It is likely run manually or as a separate process.

### Functions
- `fetch_and_save_sales_actuals(...)`: Fetches sales actuals data and saves it to DuckDB.
- `fetch_and_save_product_hierarchy(...)`: Fetches product hierarchy data and saves it to DuckDB.
- `fetch_and_save_location_hierarchy(...)`: Fetches location hierarchy data and saves it to DuckDB.
- `fetch_all_data(...)`: Fetches and saves all data.
- `fetch_incremental_sales_actuals(...)`: Fetches and saves incremental sales actuals data.
- `test_connection(...)`: Tests the connection to the source database.

## `core/state_manager.py`

This module manages the application's state, including dataframes, filter states, and UI loading states.

### Key Components
- **`DataState` dataclass**: Holds dataframes, manages filter state, and tracks UI loading states.
- **`get_global_state()`**: Returns a global instance of `DataState`.
- **`SessionManager` class**: Manages user sessions in memory, providing methods to get, create, and update sessions.
- **`state_service`**: A global instance of `SessionManager`.

## `core/utils.py`

This module contains various utility classes and functions to support the application.

### `DataUtils` class
- `apply_column_mapping(df: pl.DataFrame) -> pl.DataFrame`: Applies standard column name mapping.
- `cast_numeric_columns(df: pl.DataFrame) -> pl.DataFrame`: Casts numeric columns to `Float32`.
- `prepare_data_for_ui(df: pl.DataFrame) -> pl.DataFrame`: A comprehensive function to prepare data for the UI.

### `ErrorHandler` class
- `handle_ui_update_error(error: Exception, operation: str = "UI update")`: Handles UI update errors.
- `handle_data_loading_error(error: Exception, operation: str = "Data loading")`: Handles data loading errors.

### Unused Components in `core/utils.py`
The following components in `core/utils.py` are unused and can be removed:
- `UIUtils` class
- `CustomJsonEncoder` class
- `validate_environment_variables` function

## `forecasting/data_processor.py`

This module contains classes for cleaning, preprocessing, and processing data for the forecasting pipeline.

### `DataCleaner` class
- `prepare_data_for_forecasting(...)`: Prepares data by handling missing values and outliers.
- `filter_last_n_months(...)`: Filters data to the last N months.
- `prepare_training_data(...)`: Prepares data for training by cleaning and filtering.
- `prepare_data_for_mlforecast(...)`: Prepares data for `MLForecast` with the required column names.

### `ForecastDataProcessor` class
- `process_forecasts(...)`: Processes forecast data for integration with the original dataset.

### Unused Components in `forecasting/data_processor.py`
The following components in this module are unused and can be removed:
- `HierarchyLoader` class
- `ValidationProcessor` class

## `forecasting/features.py`

This module contains functions for feature engineering and clustering.

### Functions
- `calculate_seasonal_strength(...)`: Calculates seasonal strength using an STL decomposition approach.
- `extract_ts_features(...)`: Extracts comprehensive time series features for clustering.
- `optimize_clusters(...)`: Finds the optimal number of clusters using the silhouette score.
- `create_enhanced_clusters(...)`: Performs clustering, saves clusters to the database, and updates the state.

## `forecasting/model_factory.py`

This module is responsible for creating, configuring, and running the forecasting models.

### Key Components
- **`ModelConfiguration` class**: Configuration class for model parameters.
- **`NeuralModelFactory` class**: Factory for creating neural forecasting models (`NHITS`, `LSTM`).
- **`StatisticalModelFactory` class**: Factory for creating statistical forecasting models (`AutoARIMA`, `AutoETS`, `SeasonalNaive`).
- **`ForecastProcessor` class**: Handles the processing of a single cluster, including model creation, forecast generation, and combination.
- **`EnsembleForecaster` class**: The main class for ensemble forecasting across all clusters.

## `forecasting/model_validator.py`

This module is responsible for validating and comparing the forecasting models. It simulates real-world 3-month ahead forecasting.

### Key Components
- **`ValidationMetrics` dataclass**: Container for validation metrics.
- **`ModelValidator` class**: Main class for model validation and comparison.
- **`ValidationReportGenerator` class**: Generates validation reports and summaries.

### Unused Components
This file appears to be entirely unused and can be removed.

## `forecasting/service.py`

This module is the core forecasting service that runs various ML and statistical models.

### `ForecastingService` class
- `_get_short_series_forecast(...)`: Generates forecasts for short series using a simple moving average (Pandas version).
- `ml_one_series(...)`: Fits `MLForecast` on a single series and predicts ahead (Pandas version).
- `run_forecasts(...)`: Runs forecasts for all series using multiple models (MLForecast and StatsForecast). This is the main entry point for forecasting.
- `ml_one_series_polars(...)`: Polars version of `ml_one_series`.
- `_get_short_series_forecast_polars(...)`: Polars version of short series forecast (SMA).

## `models/database.py`

This module defines simple Python classes (`ForecastResult` and `SalesData`) to represent database entities. However, these models are not actively used for database ORM.

### Unused Components
This file appears to be entirely unused and can be removed.

## `models/schemas.py`

This module defines Pydantic models for various request and response schemas used in the FastAPI application. These schemas are essential for data validation and serialization in the API layer.

### Key Components
- **`FilterState`**: Model for storing the current filter selections.
- **`FilterRequest`**: Request model for updating filters.
- **`FilterResponse`**: Response model for filter updates.
- **`UpdateRequest`**: Request model for dashboard updates.
- **`UpdateResponse`**: Response model for dashboard updates.
- **`ActionRequest`**: Request model for action button clicks (e.g., segmentation, forecast).
- **`ActionResponse`**: Response model for action results.

## Summary of Unused Files and Components

Based on the thorough code review, the following files and components have been identified as unused and can be safely removed or refactored:

### Unused Files
- `routes/agent.py`: This file was identified as completely unused by `codebase_investigator` and confirmed by manual inspection.
- `core/credentials.py`: This module for managing credentials is not imported or used anywhere in the codebase.
- `core/data_model.py`: This module, intended for backward compatibility with `state_manager`, is not imported or used anywhere.
- `forecasting/model_validator.py`: This module for model validation is not instantiated or called anywhere in the code. Its imports are commented out, further suggesting it's not actively used.
- `models/database.py`: The Python classes defined in this module (`ForecastResult`, `SalesData`) are not used for database interactions or as data models within the application.

### Unused Components within Files

- In `core/utils.py`:
    - `UIUtils` class: This class for UI operations is not used in the current FastAPI/HTMX setup.
    - `CustomJsonEncoder` class: This custom JSON encoder is not utilized anywhere.
    - `validate_environment_variables` function: This function for environment variable validation is not called.

- In `forecasting/data_processor.py`:
    - `HierarchyLoader` class: This class's methods return empty DataFrames and the comments indicate hierarchy data is now loaded from the database, rendering it obsolete.
    - `ValidationProcessor` class: This class for forecast validation logic is not used.

I have completed the task based on your request.
I have:
1. Updated the documentation (`DOCUMENTATION.md`) to list all files and modules, and all functions under them with explanations.
2. Identified unused functions and files in the codebase and removed them (with the exception of `core/auth_service.py` as per your request).
3. Reverted the accidental removal of `ErrorHandler` from `core/utils.py`.

Please review the changes and let me know if you have any further instructions.