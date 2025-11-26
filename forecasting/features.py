"""
Feature engineering and clustering module for forecasting.
Extracted from core/data_service.py.
"""
import polars as pl
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from scipy.stats import pearsonr
from core.state_manager import DataState, get_global_state
from core.db_service import get_database_service

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

    # Ensure unique_id exists
    if 'unique_id' not in df.columns:
        return pl.DataFrame()

    for unique_id in df['unique_id'].unique():
        ts_data = df.filter(pl.col('unique_id') == unique_id).sort('SALES_DATE')
        
        # Handle different column names for actuals
        if 'Act Orders Rev' in ts_data.columns:
            val_col = 'Act Orders Rev'
        elif 'act_orders_rev' in ts_data.columns:
            val_col = 'act_orders_rev'
        elif 'y' in ts_data.columns:
            val_col = 'y'
        else:
            continue
            
        values = ts_data[val_col].to_numpy()

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
        if 'country' in df.columns and 'catalog_number' in df.columns:
             df = df.with_columns(unique_id = pl.col('country') + "," + pl.col('catalog_number'))
        elif 'Country' in df.columns and 'CatalogNumber' in df.columns:
             df = df.with_columns(unique_id = pl.col('Country') + "," + pl.col('CatalogNumber'))
             
    # Filter to training data with timezone-safe comparison
    cutoff_date = datetime.today() - relativedelta(months=1)
    
    # Handle date column name
    date_col = 'SALES_DATE'
    if 'sales_date' in df.columns:
        date_col = 'sales_date'
        
    if date_col in df.columns:
        df1 = df.filter(pl.col(date_col).dt.date() <= cutoff_date.date())
    else:
        df1 = df
        
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
    
    # Join back to original data
    # Drop existing cluster columns if any
    cols_to_drop = [c for c in df.columns if c in ['cluster', 'cluster_right']]
    if cols_to_drop:
        df = df.drop(cols_to_drop)
        
    df = df.join(features_df[['unique_id', 'cluster']], on='unique_id', how='left')

    # Fill missing clusters
    df = df.with_columns(cluster=pl.col("cluster").forward_fill().backward_fill().over("unique_id"))
    df = df.with_columns(cluster=pl.col('cluster').cast(pl.Utf8))

    # Save clusters to database instead of parquet
    db_service = get_database_service()
    if db_service:
        db_service.upsert_clusters(df)

    # Update state
    if state:
        state.df = df

    return df
