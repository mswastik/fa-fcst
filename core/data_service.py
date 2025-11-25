"""
Simplified Data service module for FCST application.
Provides data loading, processing, and forecasting functionality using MLForecast.
"""
import polars as pl
from typing import Optional, Dict, Any, List, Tuple
from core.state_manager import DataState, get_global_state
from core.utils import DataUtils, ErrorHandler
from datetime import datetime
from dateutil.relativedelta import relativedelta
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from forecasting.service import ForecastingService
from dateutil.relativedelta import relativedelta
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import warnings
from core.db_service import get_database_service
from utilsforecast.preprocessing import fill_gaps


def calculate_seasonal_strength(ts, period):
    """Calculate seasonal strength using STL decomposition approach"""
    if len(ts) < 2 * period:
        return 0

    try:
        # Simple seasonal strength calculation
        seasonal_vals = []
        for i in range(period):
            seasonal_vals.append(np.mean([ts[j] for j in range(i, len(ts), period)]))

        seasonal_var = np.var(seasonal_vals)
        total_var = np.var(ts)

        return seasonal_var / total_var if total_var != 0 else 0
    except:
        return 0

def extract_ts_features(df):
    """Extract comprehensive time series features for clustering"""
    features = []

    for unique_id in df['unique_id'].unique():
        ts_data = df.filter(pl.col('unique_id') == unique_id).sort('SALES_DATE')
        values = ts_data['Act Orders Rev'].to_numpy()

        if len(values) < 12:  # Skip if insufficient data
            continue

        # Basic statistics
        mean_val = np.mean(values)
        std_val = np.std(values)
        cv = std_val / mean_val if mean_val != 0 else 0

        # Trend analysis
        x = np.arange(len(values))
        trend_slope = np.polyfit(x, values, 1)[0] if len(values) > 1 else 0

        # Seasonality strength (12-month seasonality)
        if len(values) >= 24:
            seasonal_strength = calculate_seasonal_strength(values, 12)
        else:
            seasonal_strength = 0

        # Autocorrelation features
        lag1_corr = pearsonr(values[:-1], values[1:])[0] if len(values) > 1 else 0
        lag12_corr = pearsonr(values[:-12], values[12:])[0] if len(values) > 12 else 0

        # Volatility
        volatility = np.std(np.diff(values)) if len(values) > 1 else 0

        # Zero proportion
        zero_prop = np.sum(values == 0) / len(values)

        # Growth characteristics
        if len(values) >= 12:
            recent_growth = np.mean(values[-6:]) / np.mean(values[:6]) if np.mean(values[:6]) != 0 else 1
        else:
            recent_growth = 1

        features.append({
            'unique_id': unique_id,
            'mean': mean_val,
            'std': std_val,
            'cv': cv,
            'trend_slope': trend_slope,
            'seasonal_strength': seasonal_strength,
            'lag1_corr': lag1_corr,
            'lag12_corr': lag12_corr,
            'volatility': volatility,
            'zero_prop': zero_prop,
            'recent_growth': recent_growth
        })

    return pl.DataFrame(features)

def optimize_clusters(features_df, max_clusters=10):
    """Find optimal number of clusters using silhouette score"""
    feature_cols = [col for col in features_df.columns if col != 'unique_id']
    X = features_df[feature_cols].to_numpy()

    # Handle NaN and infinite values
    X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

    # Standardize features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    best_score = -1
    best_k = 2

    for k in range(2, min(max_clusters + 1, len(X) // 2)):
        try:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X_scaled)

            if len(np.unique(labels)) > 1:
                score = silhouette_score(X_scaled, labels)
                if score > best_score:
                    best_score = score
                    best_k = k
        except:
            continue

    return best_k, best_score

def create_enhanced_clusters(df: pl.DataFrame, state: DataState = None) -> pl.DataFrame:
    """Enhanced clustering with proper feature engineering"""
    if state is None:
        state = get_global_state()

    if 'unique_id' not in df.columns:
        df = df.with_columns(unique_id = pl.col('country') + "," + pl.col('catalog_number'))
    # Filter to training data with timezone-safe comparison
    cutoff_date = datetime.today() - relativedelta(months=1)
    df1 = df.filter(pl.col('sales_date').dt.date() <= cutoff_date.date())
    # Extract time series features
    features_df = extract_ts_features(df1)

    if len(features_df) < 4:
        print("Insufficient data for clustering")
        return df
    # Optimize cluster number
    optimal_k, silhouette = optimize_clusters(features_df)
    print(f"Optimal clusters: {optimal_k}, Silhouette score: {silhouette:.3f}")

    # Perform clustering
    feature_cols = [col for col in features_df.columns if col != 'unique_id']
    X = features_df[feature_cols].to_numpy()
    X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    features_df = features_df.with_columns(cluster=kmeans.fit_predict(X_scaled))
    print(features_df)
    # Join back to original data
    df = df.drop(['cluster','cluster_right'], strict=False)
    df = df.join(features_df[['unique_id', 'cluster']], on='unique_id', how='left')

    # Save results
    print(df)
    df = df.with_columns(cluster=pl.col("cluster").forward_fill().backward_fill().over("unique_id"))
    df = df.with_columns(cluster=pl.col('cluster').cast(pl.Utf8))

    # Save clusters to database instead of parquet
    db_service = get_database_service()
    if db_service:
        db_service.upsert_clusters(df)

    # Update state
    state.df = df

    return df

def tdays(dates: pd.DatetimeIndex) -> pd.Series:
    """Calculate the number of days since the reference date (2022-01-01)."""
    reference_date = pd.Timestamp('2022-01-01')
    return pd.Series((dates - reference_date).days, index=dates, name='tdays')

def prepare_data_for_mlforecast(df: pl.DataFrame) -> pl.DataFrame:
    """Prepare data for MLForecast with required column names"""
    # Make a copy to avoid modifying original
    prepared_df = df.clone()

    # Ensure we have the required columns with proper names
    if 'SALES_DATE' in prepared_df.columns:
        prepared_df = prepared_df.rename({'SALES_DATE': 'ds'})
    if 'sales_date' in prepared_df.columns:
        prepared_df = prepared_df.rename({'sales_date': 'ds'})
    if 'Act Orders Rev' in prepared_df.columns:
        prepared_df = prepared_df.rename({'Act Orders Rev': 'y'})
    if 'act_orders_rev' in prepared_df.columns:
        prepared_df = prepared_df.rename({'act_orders_rev': 'y'})

    # Ensure 'ds' column is datetime
    if 'ds' in prepared_df.columns:
        prepared_df = prepared_df.with_columns(
            pl.col('ds').cast(pl.Datetime).alias('ds')
        )

    # Ensure 'y' column is numeric
    if 'y' in prepared_df.columns:
        prepared_df = prepared_df.with_columns(
            pl.col('y').cast(pl.Float64).alias('y')
        )
        # Remove null or infinite values
        prepared_df = prepared_df.filter(
            pl.col('y').is_not_null() &
            pl.col('y').is_finite()
        )

    # Ensure we have unique_id
    if 'unique_id' not in prepared_df.columns:
        if 'item_skey' in prepared_df.columns and 'location_skey' in prepared_df.columns:
            prepared_df = prepared_df.with_columns(
                (pl.col('item_skey').cast(pl.Utf8) + "_" +
                 pl.col('location_skey').cast(pl.Utf8)).alias('unique_id')
            )
        elif 'Country' in prepared_df.columns and 'CatalogNumber' in prepared_df.columns:
            prepared_df = prepared_df.with_columns(
                (pl.col('Country') + "," + pl.col('CatalogNumber')).alias('unique_id')
            )
        else:
            prepared_df = prepared_df.with_columns(
                unique_id=pl.lit("UNKNOWN")
            )

    return prepared_df


def create_mlforecast_models(df: pl.DataFrame, horizon: int = 60) -> pl.DataFrame:
    """Create forecasts for each unique_id using MLForecast with parallel processing

    Args:
        df: Polars DataFrame with sales data
        horizon: Number of periods to forecast ahead

    Returns:
        Polars DataFrame with forecasts including columns: unique_id, forecast_date, Fcst Ensemble Rev
    """
    if df.is_empty():
        return pl.DataFrame()

    try:
        # Prepare data for MLForecast
        prepared_df = prepare_data_for_mlforecast(df)

        if prepared_df.is_empty() or 'unique_id' not in prepared_df.columns or 'ds' not in prepared_df.columns or 'y' not in prepared_df.columns:
            print("Required columns missing for MLForecast")
            return pl.DataFrame()

        # Ensure we have enough data points for each unique_id
        min_data_points = 10  # Minimum data points required for forecasting
        valid_ids = (
            prepared_df
            .group_by('unique_id')
            .agg(pl.len().alias('count'))
            .filter(pl.col('count') >= min_data_points)
            .get_column('unique_id')
        )

        if len(valid_ids) == 0:
            print(f"No unique_ids have sufficient data (minimum {min_data_points} points)")
            return pl.DataFrame()

        # Filter to only valid IDs
        filtered_df = prepared_df.filter(pl.col('unique_id').is_in(valid_ids))

        if filtered_df.is_empty():
            print("No sufficient data after filtering by unique_id")
            return pl.DataFrame()

        # Before passing to MLForecast, ensure the data is complete with 0s for missing values
        # Fill NaN/missing values with 0s to prevent the model from forecasting for historical periods
        filtered_df = filtered_df.with_columns(
            pl.col('y').fill_null(0).fill_nan(0)
        )

        # Determine the date range for each series and ensure no missing dates within that range
        # This will help prevent the model from seeing gaps as periods to forecast
        
        # 1. Get min date per unique_id
        ranges = filtered_df.group_by('unique_id').agg(
            pl.col('ds').min().alias('min_date')
        )
        
        # 2. Define max_date (last complete month)
        max_date = datetime.today() - relativedelta(months=1)
        
        # 3. Generate date ranges for all series at once
        # This creates a grid of (unique_id, ds) covering min_date to max_date for each series
        # 3. Generate date ranges using cross join to avoid "non-scalar start" error
        # Create a global date range from the absolute minimum date to max_date
        global_min_date = ranges['min_date'].min()
        all_dates = pl.date_range(
            start=global_min_date,
            end=max_date,
            interval='1mo',
            eager=True
        ).cast(pl.Datetime('us')).to_frame('ds')
        
        # Cross join unique_ids with all dates
        # Then filter to keep only dates >= min_date for each series
        grid = (
            ranges.select(['unique_id', 'min_date'])
            .join(all_dates, how='cross')
            .filter(pl.col('ds') >= pl.col('min_date'))
            .select(['unique_id', 'ds'])
        )
        
        # 4. Join with actual data to fill gaps with 0
        filtered_df = grid.join(
            filtered_df.select(['unique_id', 'ds', 'y']),
            on=['unique_id', 'ds'],
            how='left'
        ).with_columns(
            pl.col('y').fill_null(0).fill_nan(0)
        )

        # For each series, determine the last date in the historical data
        # This is the cutoff date for forecasting (forecast should only be for future periods)
        last_date_by_id = filtered_df.group_by('unique_id').agg(
            pl.col('ds').max().alias('max_date')
        )

        print(f"Processing {len(valid_ids)} series with last data dates from: {last_date_by_id['max_date'].min()} to {last_date_by_id['max_date'].max()}")

        # Use ForecastingService
        service = ForecastingService()
        forecasts_pl = service.run_forecasts(filtered_df, horizon=horizon)

        print("=" * 50)
        print(f"=== Forecasting completed ===")

        # Check if forecasts were generated
        if forecasts_pl.is_empty():
            print("No forecasts were generated")
            return pl.DataFrame()

        # Rename forecast column to match expected format
        # Apply the negative-to-zero logic here as well, after the model generates forecasts
        if 'ensemble' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.with_columns(
                pl.when(pl.col('ensemble') < 0)
                .then(0)
                .otherwise(pl.col('ensemble'))
                .alias('NHITS')
            )
            forecasts_pl = forecasts_pl.drop('ensemble')  # Remove the original column
        elif 'rf' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.with_columns(
                pl.when(pl.col('rf') < 0)
                .then(0)
                .otherwise(pl.col('rf'))
                .alias('NHITS')
            )
            forecasts_pl = forecasts_pl.drop('rf')  # Remove the original column
        elif 'xgb' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.with_columns(
                pl.when(pl.col('xgb') < 0)
                .then(0)
                .otherwise(pl.col('xgb'))
                .alias('NHITS')
            )
            forecasts_pl = forecasts_pl.drop('xgb')  # Remove the original column
        elif 'NHITS' in forecasts_pl.columns:
             # Just ensure non-negative
             forecasts_pl = forecasts_pl.with_columns(
                pl.when(pl.col('NHITS') < 0)
                .then(0)
                .otherwise(pl.col('NHITS'))
                .alias('NHITS')
            )
        else:
            # Use the first available forecast column and rename it to 'NHITS' after applying negative check
            forecast_cols = [col for col in forecasts_pl.columns if col not in ['unique_id', 'ds', 'y']]
            if forecast_cols:
                col_name = forecast_cols[0]
                forecasts_pl = forecasts_pl.with_columns(
                    pl.when(pl.col(col_name) < 0)
                    .then(0)
                    .otherwise(pl.col(col_name))
                    .alias('NHITS')
                )
                forecasts_pl = forecasts_pl.drop(col_name)  # Remove the original column

        # Ensure proper column names for database integration
        if 'ds' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.rename({'ds': 'forecast_date'})

        return forecasts_pl

    except Exception as e:
        print(f"Error in MLForecast: {e}")
        import traceback
        traceback.print_exc()
        return pl.DataFrame()


def run_mlforecast_pipeline(df: pl.DataFrame, state: DataState = None, forecast_version: Optional[str] = None) -> Tuple[Optional[pl.DataFrame], Dict[str, Any]]:
    """Run the forecasting pipeline using MLForecast and save results to database

    Args:
        df: Polars DataFrame with sales data
        state: Optional DataState instance
        forecast_version: Optional string to identify the forecast version

    Returns:
        Tuple of (combined_df, validation_results_dict)
    """
    if state is None:
        state = get_global_state()

    try:
        # Make a copy of the original dataframe to preserve original column names
        original_df = df.clone()

        # Generate forecasts with MLForecast - returns polars DataFrame
        forecast_df = create_mlforecast_models(df, horizon=60)

        print(f"DEBUG: Generated forecast DataFrame with {len(forecast_df)} records")
        if not forecast_df.is_empty():
            print(f"DEBUG: Forecast DataFrame schema: {forecast_df.schema}")
            print(f"DEBUG: Unique IDs in forecast: {forecast_df['unique_id'].n_unique() if 'unique_id' in forecast_df.columns else 0}")
            print(f"DEBUG: Forecast date range: {forecast_df['forecast_date'].min() if 'forecast_date' in forecast_df.columns else 'N/A'} to {forecast_df['forecast_date'].max() if 'forecast_date' in forecast_df.columns else 'N/A'}")

        if forecast_df is not None and not forecast_df.is_empty():
            # Cast NHITS to Float32 to match other numeric columns
            if 'NHITS' in forecast_df.columns:
                forecast_df = forecast_df.with_columns(pl.col('NHITS').cast(pl.Float32))

            # Save forecasts to database if service is available
            db_service = get_database_service()
            saved_count = 0

            if db_service:
                try:
                    # Ensure forecast_df has necessary columns for database insertion
                    if 'unique_id' in forecast_df.columns and 'forecast_date' in forecast_df.columns:
                        # Add item_skey and location_skey if they don't exist by extracting from unique_id
                        if 'item_skey' not in forecast_df.columns or 'location_skey' not in forecast_df.columns:
                            # Extract item_skey and location_skey from unique_id (format: item_skey_location_skey)
                            split_data = forecast_df['unique_id'].str.split('_').to_list()

                            item_skeys = []
                            location_skeys = []

                            unique_ids_list = forecast_df['unique_id'].to_list()
                            for unique_id in unique_ids_list:
                                if isinstance(unique_id, str):
                                    # Check if it's in item_skey_location_skey format
                                    if '_' in unique_id:
                                        parts = unique_id.split('_', 1)  # Split only on first underscore
                                        if len(parts) == 2:
                                            try:
                                                item_skey = int(parts[0])
                                                location_skey = int(parts[1])
                                                item_skeys.append(item_skey)
                                                location_skeys.append(location_skey)
                                                continue  # Move to next unique_id
                                            except (ValueError, TypeError):
                                                pass  # Fall through to handle as other format
                                    # Check if it's in Country,CatalogNumber format
                                    elif ',' in unique_id:
                                        pass  # Let database service handle this format
                                # For any other format or if conversion failed
                                item_skeys.append(None)
                                location_skeys.append(None)

                            # Add columns to polars DataFrame
                            forecast_df = forecast_df.with_columns([
                                pl.Series('item_skey', item_skeys).cast(pl.Int64),
                                pl.Series('location_skey', location_skeys).cast(pl.Int64)
                            ])

                        # Insert forecasts into database
                        print(f"\n>>> Starting database insertion for {len(forecast_df)} forecast records...")
                        print(f">>> DataFrame info: {forecast_df.shape} shape")
                        import time
                        db_start = time.time()
                        saved_count = db_service.insert_forecasts(forecast_df, model_type="MLForecast", forecast_version=forecast_version)
                        db_time = time.time() - db_start
                        print(f">>> Database insertion completed in {db_time:.2f}s")
                        print(f">>> Successfully saved {saved_count} forecast records to database")
                except Exception as save_error:
                    print(f"Error saving forecasts to database: {save_error}")
                    import traceback
                    traceback.print_exc()

            # Combine historical and forecast data for UI
            # 1. Prepare historical data
            hist_df = original_df.clone()
            if 'NHITS' not in hist_df.columns:
                hist_df = hist_df.with_columns(pl.lit(None, dtype=pl.Float32).alias('NHITS'))

            # 2. Prepare forecast data
            fcst_df = forecast_df.rename({'forecast_date': 'SALES_DATE'})

            # Ensure original_df has unique_id for joining dimensions
            if 'unique_id' not in original_df.columns:
                original_df_with_id = prepare_data_for_mlforecast(original_df)
            else:
                original_df_with_id = original_df

            dim_cols = [c for c in original_df_with_id.columns if c not in ['SALES_DATE', 'Act Orders Rev', 'ds', 'y', 'NHITS']]
            if 'unique_id' not in dim_cols:
                dim_cols.append('unique_id')

            dims_df = original_df_with_id[dim_cols].unique(subset=['unique_id'])

            fcst_with_dims = fcst_df.join(dims_df, on='unique_id', how='left')

            if 'Act Orders Rev' not in fcst_with_dims.columns:
                fcst_with_dims = fcst_with_dims.with_columns(pl.lit(None, dtype=pl.Float32).alias('Act Orders Rev'))

            # Align columns for concatenation
            final_cols = hist_df.columns

            for col in final_cols:
                if col not in fcst_with_dims.columns:
                    fcst_with_dims = fcst_with_dims.with_columns(pl.lit(None).alias(col))

            fcst_with_dims = fcst_with_dims.select(final_cols)

            combined_df = pl.concat([hist_df, fcst_with_dims])

            # Update state with combined data
            if state is not None:
                state.df = combined_df

            # Return validation results
            validation_results = {
                'mae': 0.0,
                'mape': 0.0,
                'rmse': 0.0,
                'forecasts_generated': len(forecast_df),
                'forecasts_saved': saved_count
            }

            return combined_df, validation_results
        else:
            print("No forecasts generated")
            return original_df, {'mae': 0.0, 'mape': 0.0, 'rmse': 0.0, 'forecasts_generated': 0, 'forecasts_saved': 0}

    except Exception as e:
        print(f"Error in run_mlforecast_pipeline: {e}")
        import traceback
        traceback.print_exc()
        return df, {'error': str(e), 'forecasts_generated': 0, 'forecasts_saved': 0}


def create_models_action(df: pl.DataFrame, state: DataState = None, forecast_version: Optional[str] = None) -> pl.DataFrame:
    """Business logic for creating forecasting models using MLForecast"""
    if state is None:
        state = get_global_state()

    try:
        # Generate a unique forecast version using the current timestamp
        if forecast_version is None:
            forecast_version = datetime.now().strftime("F-%Y%m%d_%H%M%S")
        print(f"Generated forecast version: {forecast_version}")

        # Run the MLForecast pipeline
        result_df, validation_results = run_mlforecast_pipeline(df, state, forecast_version=forecast_version)

        # Ensure original column structure is preserved for UI compatibility
        if result_df is not None and not result_df.is_empty():
            # Check if result_df is a polars DataFrame
            is_polars_result = isinstance(result_df, pl.DataFrame)
            is_polars_original = isinstance(df, pl.DataFrame)

            # If original df had SALES_DATE, ensure it's still present
            if 'SALES_DATE' in df.columns and 'SALES_DATE' not in result_df.columns:
                if is_polars_result and is_polars_original:
                    result_df = result_df.with_columns(df['SALES_DATE'])
                elif not is_polars_result and not is_polars_original:  # Both are pandas
                    result_df['SALES_DATE'] = df['SALES_DATE']
            # If original df had sales_date, ensure it's still present
            elif 'sales_date' in df.columns and 'sales_date' not in result_df.columns:
                if is_polars_result and is_polars_original:
                    result_df = result_df.with_columns(df['sales_date'])
                elif not is_polars_result and not is_polars_original:  # Both are pandas
                    result_df['sales_date'] = df['sales_date']

        print(f"Models created successfully. Validation results: {validation_results}")
        return result_df
    except Exception as e:
        print(f"Error in create_models_action: {e}")
        import traceback
        traceback.print_exc()
        return df


def apply_filters(filters, state: DataState = None):
    """Apply filters to the dataset by querying database directly"""
    if state is None:
        state = get_global_state()

    # Only fetch data when both location and product filters are set
    if not (filters.get('location2') and filters.get('location1') and
            filters.get('product2') and filters.get('product1')):
        # Return empty result if filters are not complete
        return {
            'fdf': '{}',
            'filtered_df': pl.DataFrame(),
            'filtered_products': [],
            'filtered_models': []
        }

    try:
        # Import database service
        db_service = get_database_service()
        if db_service is None:
            return {
                'fdf': '{}',
                'filtered_df': pl.DataFrame(),
                'filtered_products': [],
                'filtered_models': []
            }

        # Query database directly with filters
        df = db_service.get_filtered_sales_actuals(
            location_col=filters.get('location1'),
            location_val=filters.get('location2'),
            product_col=filters.get('product1'),
            product_val=filters.get('product2')
        )

        # Apply standard data preparation
        df = DataUtils.prepare_data_for_ui(df)

        # Update state with fresh data
        state.df = df.clone()
        state.full_df = df.clone()
        state.filtered_df = df.clone()

        # Prepare filtered result for UI display
        if filters.get('level'):
            fdf = df.clone()
            # Use level + location1 if location1 is set, otherwise just level
            level_col = 'Business Unit'  # Default level column
            if filters.get('level') in ['Franchise', 'IBP Level 5', 'IBP Level 6']:
                level_col = filters['level']

            if level_col in df.columns:
                group_cols = ['sales_date', level_col]
                if filters.get('location1') and filters.get('location1') != 'level':
                    location_col = filters['location1']
                    if location_col in df.columns:
                        group_cols.append(location_col)

                fdf = fdf.group_by(group_cols).sum()
        else:
            fdf = df.clone()

        # Get filtered products for dropdown
        try:
            if filters.get('product1') and filters['product1'] in df.columns:
                filtered_products = df[filters['product1']].unique().to_list()
            else:
                filtered_products = []
        except Exception:
            filtered_products = []

        filtered_models = [f"Model for {product}" for product in filtered_products if product]

        return {
            'fdf': fdf.write_json(),
            'filtered_df': fdf,
            'filtered_products': filtered_products,
            'filtered_models': filtered_models
        }

    except Exception as e:
        print(f"Error in apply_filters: {e}")
        return {
            'fdf': '{}',
            'filtered_df': pl.DataFrame(),
            'filtered_products': [],
            'filtered_models': []
        }


def change_fc_action():
    """Business logic for changing forecast settings"""
    return "Changing forecast settings"

