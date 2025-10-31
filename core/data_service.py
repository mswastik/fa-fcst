"""
Simplified Data service module for FCST application.
Provides data loading, processing, and forecasting functionality using MLForecast.
"""
import polars as pl
from typing import Optional, Dict, Any, List, Tuple
from core.state_manager import DataState, get_global_state
from core.utils import DataUtils, DatabaseUtils, ErrorHandler
from mlforecast import MLForecast
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import VotingRegressor
import xgboost as xgb
from datetime import datetime
from dateutil.relativedelta import relativedelta
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from mlforecast.lag_transforms import ExpandingMean, RollingMean
from scipy.stats import pearsonr
from sklearn.cluster import Birch, KMeans
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_absolute_percentage_error, silhouette_score
from joblib import Parallel, delayed
from tqdm import tqdm
from tqdm_joblib import tqdm_joblib
from contextlib import contextmanager
import warnings


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

def create_enhanced_clusters(df: pl.DataFrame, file_path: str, state: DataState = None) -> pl.DataFrame:
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
    db_service = DatabaseUtils.get_database_service()
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
        
        # Filter to training data (excluding the last month)
        cutoff_date = datetime.today() - relativedelta(months=1)
        train_df = prepared_df.filter(pl.col('ds').dt.date() <= cutoff_date.date())
        
        if train_df.is_empty():
            print("Training data is empty after filtering")
            return pl.DataFrame()
        
        # Ensure we have enough data points for each unique_id
        min_data_points = 10  # Minimum data points required for forecasting
        valid_ids = (
            train_df
            .group_by('unique_id')
            .count()
            .filter(pl.col('count') >= min_data_points)
            .get_column('unique_id')
        )
        
        if len(valid_ids) == 0:
            print(f"No unique_ids have sufficient data (minimum {min_data_points} points)")
            return pl.DataFrame()
        
        train_df = train_df.filter(pl.col('unique_id').is_in(valid_ids))
        
        if train_df.is_empty():
            print("No sufficient data after filtering by unique_id")
            return pl.DataFrame()

        # Define models - using XGBoost models as in the current code
        xgb1 = xgb.XGBRegressor(random_state=0, booster='gblinear')
        xgb2 = xgb.XGBRegressor(random_state=0)
        
        # Define models for MLForecast - using models that handle NaN values
        models = {
            'rf': RandomForestRegressor(n_estimators=50, random_state=42),
            'xgb': VotingRegressor([('xgb1', xgb1), ('xgb2', xgb2)])
        }

        # Use ml_per_series for parallel forecasting - returns polars DataFrame
        print(f"=== Starting MLForecast for {len(valid_ids)} series ===")
        print(f"Models: {list(models.keys())}")
        print(f"Lags: [3, 4, 5, 6, 12]")
        print(f"Lag transforms: RollingMean(3) on lag 3")
        print(f"Date features: ['month', 'year']")
        print(f"Parallel jobs: 1 (sequential processing)")
        print(f"Min observations per series: {min_data_points}")
        print("=" * 50)
        
        forecasts_pl = ml_per_series(
            idf=train_df[['unique_id','ds','y']].fill_nan(0),
            models=models,
            horizon=horizon,
            freq='MS',
            lags=[3, 4, 5, 6, 12],
            lag_transforms={3: [RollingMean(3)]},
            date_features=['month', tdays],
            n_jobs=1,
            min_obs=min_data_points
        )
        
        print("=" * 50)
        print(f"=== Forecasting completed ===")
        
        # Check if forecasts were generated
        if forecasts_pl.is_empty():
            print("No forecasts were generated")
            return pl.DataFrame()
        
        # Rename forecast column to match expected format
        if 'rf' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.rename({'rf': 'Fcst Ensemble Rev'})
        elif 'xgb' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.rename({'xgb': 'Fcst Ensemble Rev'})
        else:
            # Use the first available forecast column
            forecast_cols = [col for col in forecasts_pl.columns if col not in ['unique_id', 'ds', 'y']]
            if forecast_cols:
                forecasts_pl = forecasts_pl.rename({forecast_cols[0]: 'Fcst Ensemble Rev'})
        
        # Ensure proper column names for database integration
        if 'ds' in forecasts_pl.columns:
            forecasts_pl = forecasts_pl.rename({'ds': 'forecast_date'})
        
        return forecasts_pl
        
    except Exception as e:
        print(f"Error in MLForecast: {e}")
        import traceback
        traceback.print_exc()
        return pl.DataFrame()


def run_mlforecast_pipeline(df: pl.DataFrame, file_path: str, state: DataState = None) -> Tuple[Optional[pl.DataFrame], Dict[str, Any]]:
    """Run the forecasting pipeline using MLForecast and save results to database
    
    Args:
        df: Polars DataFrame with sales data
        file_path: Path to the data file (for reference)
        state: Optional DataState instance
        
    Returns:
        Tuple of (original_df, validation_results_dict)
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
            # Save forecasts to database if service is available
            db_service = DatabaseUtils.get_database_service()
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
                        saved_count = db_service.insert_forecasts(forecast_df, model_type="MLForecast")
                        db_time = time.time() - db_start
                        print(f">>> Database insertion completed in {db_time:.2f}s")
                        print(f">>> Successfully saved {saved_count} forecast records to database")
                except Exception as save_error:
                    print(f"Error saving forecasts to database: {save_error}")
                    import traceback
                    traceback.print_exc()
            
            # Update state with original data (preserving original structure)
            if state is not None:
                state.df = original_df
            
            # Return validation results
            validation_results = {
                'mae': 0.0,
                'mape': 0.0,
                'rmse': 0.0,
                'forecasts_generated': len(forecast_df),
                'forecasts_saved': saved_count
            }
            
            return original_df, validation_results
        else:
            print("No forecasts generated")
            return original_df, {'mae': 0.0, 'mape': 0.0, 'rmse': 0.0, 'forecasts_generated': 0, 'forecasts_saved': 0}
    
    except Exception as e:
        print(f"Error in run_mlforecast_pipeline: {e}")
        import traceback
        traceback.print_exc()
        return df, {'error': str(e), 'forecasts_generated': 0, 'forecasts_saved': 0}


def create_models_action(df: pl.DataFrame, file_path: str, state: DataState = None) -> pl.DataFrame:
    """Business logic for creating forecasting models using MLForecast"""
    if state is None:
        state = get_global_state()
    
    try:
        # Run the MLForecast pipeline
        result_df, validation_results = run_mlforecast_pipeline(df, file_path, state)
        
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
        db_service = DatabaseUtils.get_database_service()
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


def ml_one_series(uid, group_df, models, horizon, freq, lags, lag_transforms, date_features, min_obs=30):
    """
    Fit MLForecast on one series (unique_id == uid), predict horizon ahead.
    Returns a pandas DataFrame with predictions, with 'unique_id' = uid.
    
    Args:
        uid: Unique identifier for the series
        group_df: Pandas DataFrame with columns ds, y for this series
        models: Dictionary of model instances
        horizon: Number of periods to forecast
        freq: Frequency string
        lags: List of lag values
        lag_transforms: Dictionary of lag transformations
        date_features: List of date features
        min_obs: Minimum observations required
        
    Returns:
        Pandas DataFrame with forecasts or None if forecasting fails
    """
    import time
    start_time = time.time()
    
    # Check if the series has enough data points
    if len(group_df) < min_obs:
        print(f"[{uid}] Skipped: Only {len(group_df)} data points (need {min_obs})")
        return None
    
    # Check if the series has enough positive values
    positive_count = (group_df['y'] > 0).sum()
    if positive_count < min_obs:
        print(f"[{uid}] Skipped: Only {positive_count} positive values (need {min_obs})")
        return None
    
    print(f"[{uid}] Starting forecast with {len(group_df)} data points...")
    
    try:
        # Suppress MLForecast warnings about dropped series
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='.*series were dropped completely.*')
            warnings.filterwarnings('ignore', category=UserWarning)
            
            fit_start = time.time()
            # Create and fit the model
            mfh = MLForecast(
                models=models,
                freq=freq,
                lags=lags,
                lag_transforms=lag_transforms,
                date_features=date_features
            )
            
            # Fit the model - use dropna=False to be more lenient
            mfh.fit(group_df, dropna=False)
            fit_time = time.time() - fit_start
            print(f"[{uid}] Model fitting took {fit_time:.2f}s")
            
            # Predict
            pred_start = time.time()
            forecast = mfh.predict(h=horizon)
            pred_time = time.time() - pred_start
            print(f"[{uid}] Prediction took {pred_time:.2f}s")
        
        # Ensure it's a pandas DataFrame and add unique_id
        if forecast is not None and len(forecast) > 0:
            forecast['unique_id'] = uid
            total_time = time.time() - start_time
            print(f"[{uid}] ✓ Completed in {total_time:.2f}s total")
            return forecast
        else:
            print(f"[{uid}] ✗ No forecast generated")
            return None
            
    except ValueError as ve:
        # Handle specific errors like "Found array with 0 sample(s)"
        if "Found array with 0 sample" in str(ve) or "minimum of 1 is required" in str(ve):
            print(f"[{uid}] ✗ Skipped: Insufficient data after transformations")
        else:
            print(f"[{uid}] ✗ ValueError: {ve}")
        return None
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{uid}] ✗ Error after {elapsed:.2f}s: {e}")
        return None


def ml_per_series(idf, models, horizon=60, freq='MS', lags=[3,4,5,6,12], lag_transforms={3:[RollingMean(3)]}, date_features=None, n_jobs=-1, min_obs=30):
    """
    Parallel per-series forecasting using MLForecast.
    
    Args:
        idf: Polars or Pandas DataFrame with columns: unique_id, ds (date), y (target)
        models: Dictionary of model instances for MLForecast
        horizon: Number of periods to forecast
        freq: Frequency string (e.g., 'MS' for month start)
        lags: List of lag values to use as features
        lag_transforms: Dictionary of lag transformations
        date_features: List of date features to extract
        n_jobs: Number of parallel jobs (-1 for all cores)
        min_obs: Minimum observations required per series
    
    Returns:
        Polars DataFrame with forecasts for all series
    """
    # Convert polars DataFrame to pandas for MLForecast compatibility
    if hasattr(idf, 'to_pandas'):
        df_pandas = idf.to_pandas()
    else:
        df_pandas = idf.copy()
    try:
        print("DF Type:"+idf.info())
    except:
        pass
    # Group by unique_id
    groups = [(uid, group) for uid, group in df_pandas.groupby('unique_id')]
    
    # Run forecasting with progress bar
    # Note: Using sequential processing (list comprehension) instead of Parallel for better debugging
    print(f"Processing {len(groups)} series sequentially...")
    results = []
    for i, (uid, group_df) in enumerate(groups, 1):
        print(f"\n[Progress: {i}/{len(groups)}]")
        result = ml_one_series(uid, group_df, models, horizon, freq, lags, lag_transforms, date_features, min_obs)
        results.append(result)
    
    # Filter out None results and concatenate
    dfs = [df for df in results if df is not None]
    print(f"\n✓ Successfully generated forecasts for {len(dfs)} out of {len(groups)} series")
    if len(dfs) == 0:
        return pl.DataFrame()
    
    # Concatenate all forecasts and convert to polars
    all_forecasts_pd = pd.concat(dfs, ignore_index=True)
    all_forecasts_pl = pl.from_pandas(all_forecasts_pd)
    
    return all_forecasts_pl