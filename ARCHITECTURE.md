# FastAPI Forecasting Application Architecture Diagrams

This document contains Mermaid diagrams illustrating the high-level and module-level architecture of the application.

## 1. High-Level System Architecture

This diagram shows the main components and their interactions, highlighting the flow from the user interface to the data and modeling layers.

```mermaid
graph TD
    subgraph Frontend["Frontend (HTMX JS)"]
        A[User Interface] -- Filter/Action --> B(FastAPI Routes)
        B -- HTML/Data --> A
    end

    subgraph Backend["Backend (FastAPI)"]
        B -- State/DB Access --> C(Core Services)
        B -- Forecasting Logic --> D(Forecasting Module)
    end

    subgraph Enhancement["Enhancement"]
        B -- AI Agent --> E(Local LLM/ Web Search)
    end

    subgraph CoreServices["Core Services"]
        C -- Connection Mgmt --> F(DuckDB Connection Manager)
        C -- Data Access --> G(Database Service)
        C -- State Mgmt --> H(DataState)
    end

    subgraph DataLayer["Data Layer"]
        G -- SQL Query --> I[DuckDB Database]
    end

    subgraph ForecastingModule["Forecasting Module"]
        D -- Data Prep --> K(Data Processor)
        D -- Features --> L(Features)
        D -- Model Creation --> M(Model Factory)
        D -- Validation --> N(Model Validator)
    end

    D -- Read/Write --> I

    subgraph Database["Database"]
        J[Envision DB] -- Fetch Data --> I
    end

    style Frontend fill:#aaf,stroke:#333,stroke-width:2px
    style Backend fill:#ccf,stroke:#333,stroke-width:2px
    style CoreServices fill:#ddf,stroke:#333,stroke-width:2px
    style ForecastingModule fill:#cfc,stroke:#333,stroke-width:2px
    style DataLayer fill:#ffc,stroke:#333,stroke-width:2px
    style Enhancement fill:#ffd,stroke:#333,stroke-width:2px
    style Database fill:#ffe,stroke:#333,stroke-width:2px
```

## 2. Module Dependency Diagram

This diagram illustrates the dependencies between the main Python modules.

```mermaid
graph TD
    A[app.py] --> B(routes/)
    B --> C(core/state_manager.py)
    B --> D(core/db_service.py)
    B --> E(templates/)
    B --> F(static/)

    C --> D
    C --> G(core/data_service.py)
    C --> H(core/duckdb_connection_manager.py)

    D --> H
    D --> I(models/schemas.py)
    D --> J(core/credentials.py)

    G --> D
    G --> K(forecasting/data_processor.py)
    G --> L(forecasting/features.py)
    G --> M(forecasting/service.py)

    E --> C
    E --> G

    K --> D
    L --> K
    M --> K
```

## 3. Forecasting Pipeline Flow

This sequence diagram details the steps involved when a user triggers a forecasting action from the UI.

```mermaid
sequenceDiagram
    participant UI as HTMX Dashboard
    participant API as FastAPI /api/actions
    participant State as DataState
    participant DB as DatabaseService
    participant DS as DataService
    participant FM as ModelFactory
    participant MV as ModelValidator

    UI->>API: POST /api/actions (ActionRequest: 'Create Models')
    API->>State: set_loading_state('charts', True)
    API->>DS: run_mlforecast_pipeline(filtered_df)
    DS->>DS: DataCleaner.prepare_data_for_mlforecast()
    DS->>DS: create_mlforecast_models()
    DS->>FM: ForecastingService.run_forecasts()
    FM-->>DS: Forecasts (pl.DataFrame)
    DS->>DB: insert_forecasts(forecast_df)
    DB-->>DS: Success
    DS-->>API: Forecasts/Metadata
    API->>State: update_filtered_data(forecast_df)
    API->>State: set_loading_state('charts', False)
    API->>UI: UpdateResponse (HTML for charts/table)

    alt Validation Action
        UI->>API: POST /api/actions (ActionRequest: 'Validation')
        API->>MV: validate_last_3_months()
        MV->>DB: get_sales_actuals()
        MV-->>API: ValidationMetrics
        API->>UI: UpdateResponse (HTML for Validation Dialog)
    end
```