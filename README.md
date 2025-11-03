# FastAPI Forecasting Application Documentation

This document provides an overview of the architecture, core modules, and key functions of the FastAPI-based time series forecasting application. The application uses FastAPI for the backend API and NiceGUI for the interactive frontend dashboard, leveraging DuckDB for high-performance data storage and Polars/MLForecast for data processing and modeling.

## 1. Architecture Overview

The application follows a modular, service-oriented architecture to separate concerns:

*   **Frontend (NiceGUI/UI)**: Handles user interaction, data visualization, and component state.
*   **Backend (FastAPI/Routes)**: Provides REST and streaming endpoints for data, filters, actions, and the AI agent.
*   **Core Services (`core/`)**: Manages authentication, database connections, application state, and data fetching.
*   **Forecasting Logic (`forecasting/`)**: Contains the business logic for data cleaning, feature engineering, model creation, and validation.
*   **Data Layer (DuckDB)**: The embedded analytical database for fast data retrieval and manipulation.

*(The detailed Mermaid architecture diagram will be provided in the next step.)*

## 2. Core Modules and Responsibilities

| Module | Directory | Key Responsibilities |
| :--- | :--- | :--- |
| **Core Services** | `core/` | Authentication, credential management, DuckDB connection pooling, application state management, and utility functions. |
| **Database** | `core/db_service.py` | Multi-user database session management, query execution, and data retrieval (actuals, filter options). |
| **Forecasting** | `forecasting/` | Data cleaning, feature engineering, model configuration, neural/statistical model creation, ensemble forecasting, and model validation. |
| **API Routes** | `routes/` | Defines all FastAPI endpoints for UI updates, filter changes, action handling (clustering, forecasting), and the AI agent. |
| **UI Components** | `ui/` | NiceGUI components for the dashboard, filters, charts, action buttons, and validation results dialogs. |
| **Data Models** | `models/` | Pydantic schemas for API request/response validation and database entity definitions. |

## 3. Key Functions and Their Uses

This is a curated list of the most critical functions in the codebase:

### Authentication and State Management

| Function | Module | Description |
| :--- | :--- | :--- |
| [`AuthService.handle_callback()`](core/auth_service.py:59) | `core/auth_service.py` | Completes the Microsoft OAuth2 flow and processes user information. |
| [`AuthMiddleware.dispatch()`](core/auth_service.py:86) | `core/auth_service.py` | Middleware to enforce authentication on protected routes. |
| [`DataState.get_global_state()`](core/state_manager.py:400) | `core/state_manager.py` | Retrieves the client-specific session state for the UI. |
| [`DataState.set_loading_state()`](core/state_manager.py:57) | `core/state_manager.py` | Sets the loading status and message for a UI component. |

### Data and Database Operations

| Function | Module | Description |
| :--- | :--- | :--- |
| [`DatabaseService.execute_query()`](core/db_service.py:74) | `core/db_service.py` | Executes a SQL query for a specific user and returns a Polars DataFrame. |
| [`DatabaseService.get_filter_options()`](core/db_service.py:400) | `core/db_service.py` | Retrieves available filter options from hierarchy tables with caching. |
| [`DuckDBConnectionManager.create_user_connection()`](core/duckdb_connection_manager.py:26) | `core/duckdb_connection_manager.py` | Creates a new, isolated DuckDB connection for a specific user session. |
| [`fetch_and_save_sales_actuals()`](core/fetchdata.py:62) | `core/fetchdata.py` | Fetches sales actuals from an external ODBC source and saves them to DuckDB. |
| [`DataUtils.prepare_data_for_ui()`](core/utils.py:70) | `core/utils.py` | Cleans and prepares data (e.g., casting, mapping) for display in the UI. |

### Forecasting and Modeling

| Function | Module | Description |
| :--- | :--- | :--- |
| [`run_mlforecast_pipeline()`](core/data_service.py:355) | `core/data_service.py` | Executes the full MLForecast pipeline, including feature engineering and saving results. |
| [`create_enhanced_clusters()`](core/data_service.py:133) | `core/data_service.py` | Performs data segmentation/clustering for improved model performance. |
| [`EnsembleForecaster.generate_forecasts()`](forecasting/model_factory.py:204) | `forecasting/model_factory.py` | Main entry point for generating ensemble forecasts across all data clusters. |
| [`ModelValidator.validate_last_3_months()`](forecasting/model_validator.py:36) | `forecasting/model_validator.py` | Validates all available models (neural and statistical) against recent actuals. |
| [`ValidationReportGenerator.generate_text_report()`](forecasting/model_validator.py:512) | `forecasting/model_validator.py` | Generates a human-readable summary report of the model validation results. |

### API and UI Interaction

| Function | Module | Description |
| :--- | :--- | :--- |
| [`update_filters()`](routes/api.py:26) | `routes/api.py` | FastAPI endpoint to process filter changes and return updated UI components (HTMX). |
| [`handle_action()`](routes/api.py:620) | `routes/api.py` | FastAPI endpoint to trigger long-running actions like Clustering, Model Creation, and Validation. |
| [`run_agent_stream_api()`](routes/api.py:1077) | `routes/api.py` | FastAPI endpoint for the AI agent, providing a streaming response with web search and summarization capabilities. |
| [`create_dashboard()`](ui/dashboard.py:94) | `ui/dashboard.py` | The main NiceGUI function that composes all UI components (filters, charts, tables). |
| [`ActionButtons._run_create_models()`](ui/components.py:591) | `ui/components.py` | NiceGUI handler for the "Create Models" button, initiating the forecasting process. |