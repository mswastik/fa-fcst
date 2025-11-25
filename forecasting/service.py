"""
Forecasting service module.
Handles the execution of forecasting models, including per-series logic and short-series handling.
"""
import polars as pl
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Union
from mlforecast import MLForecast
from mlforecast.lag_transforms import RollingMean
from sklearn.ensemble import VotingRegressor
import xgboost as xgb
import warnings
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

class ForecastingService:
    """Service for running forecasting models."""
    
    def __init__(self):
        pass

    def _get_short_series_forecast(self, group_df: pd.DataFrame, horizon: int, uid: str) -> pd.DataFrame:
        """
        Generate forecast for short series using simple moving average.
        """
        # Simple Moving Average of last 3 points (or fewer if not available)
        last_n = 3
        if len(group_df) < last_n:
            last_n = len(group_df)
        
        if last_n == 0:
            return None
            
        # Calculate mean of last n values
        # group_df is pandas DataFrame with 'ds' and 'y'
        mean_val = group_df['y'].tail(last_n).mean()
        
        # Create future dates
        last_date = group_df['ds'].max()
        future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=horizon, freq='MS')
        
        forecast_df = pd.DataFrame({
            'ds': future_dates,
            'NHITS': [mean_val] * horizon, # Using NHITS as the column name for consistency
            'unique_id': uid
        })
        
        return forecast_df

    def ml_one_series(self, uid, group_df, models, horizon, freq, lags, lag_transforms, date_features, min_obs=12):
        """
        Fit MLForecast on one series (unique_id == uid), predict horizon ahead.
        """
        # Check length
        if len(group_df) < min_obs:
            print(f"[{uid}] Short series ({len(group_df)} < {min_obs}). Using Simple Moving Average.")
            return self._get_short_series_forecast(group_df, horizon, uid)
            
        # Check positive values
        positive_count = (group_df['y'] > 0).sum()
        if positive_count < min_obs:
             print(f"[{uid}] Low positive count ({positive_count} < {min_obs}). Using Simple Moving Average.")
             return self._get_short_series_forecast(group_df, horizon, uid)

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*series were dropped completely.*')
                warnings.filterwarnings('ignore', category=UserWarning)

                mfh = MLForecast(
                    models=models,
                    freq=freq,
                    lags=lags,
                    lag_transforms=lag_transforms,
                    date_features=date_features,
                )

                # Fit the model
                mfh.fit(group_df, dropna=False)
                
                # Predict
                forecast = mfh.predict(h=horizon)
                
            if forecast is not None and len(forecast) > 0:
                forecast['unique_id'] = uid
                return forecast
            else:
                return None

        except Exception as e:
            print(f"[{uid}] Error in MLForecast: {e}")
            return None

    def run_forecasts(self, df: pl.DataFrame, horizon: int = 60) -> pl.DataFrame:
        """
        Run forecasts for all series in the dataframe.
        """
        # Convert to pandas for MLForecast (it handles pandas groups better for now in this custom loop)
        # Note: User asked to use Polars natively with MLForecast. 
        # However, since we are doing a custom per-series loop, we are slicing the dataframe.
        # Slicing Polars is fast, but MLForecast.fit() on a single series Polars DF might be tricky if it expects specific structure.
        # Let's try to keep it Polars if possible, but for the per-series loop, converting the *group* to pandas might be safer 
        # given the existing logic, OR we can try passing Polars frame to MLForecast.
        # MLForecast supports Polars.
        
        # Let's try to use Polars for the loop if possible, or just convert the chunks.
        # Actually, for the "per series" requirement, we have to iterate.
        
        # Optimization: We can use Polars partition_by to get list of DataFrames
        groups = df.partition_by("unique_id", as_dict=True)
        
        # Define models
        xgb1 = xgb.XGBRegressor(random_state=0, booster='gblinear')
        xgb2 = xgb.XGBRegressor(random_state=0)
        models = {
            'xgb': VotingRegressor([('xgb1', xgb1), ('xgb2', xgb2)])
        }
        
        results = []
        print(f"Processing {len(groups)} series...")
        
        for uid, group_pl in groups.items():
            # Convert to pandas for the single series fit if needed, or pass Polars if MLForecast supports it for single series
            # MLForecast expects 'ds', 'y', 'unique_id'
            # For short series logic, we need to access data.
            
            # Using pandas for the single series interaction is likely fine and robust enough for now, 
            # as the overhead is small per series compared to fitting.
            # But let's try to stick to Polars for the data passing if MLForecast accepts it.
            # MLForecast fit accepts Polars DataFrame.
            
            # However, our _get_short_series_forecast needs to handle it.
            
            # Let's convert to pandas for the *internal* logic of this method to be safe with existing MLForecast usage patterns 
            # in this specific codebase, but the input to this function is Polars.
            # Actually, the user specifically asked to "Use Polars natively".
            # So I should try to use Polars inside `ml_one_series` too.
            
            # Converting the single group to pandas for MLForecast is NOT what they meant by "Use Polars natively". 
            # They meant avoid `idf.to_pandas()` which converts the *entire* dataset at once.
            
            # But `MLForecast` with `fit` on a single series... 
            # If I pass a Polars DF to `fit`, it works.
            
            # So let's try to use Polars in `ml_one_series`.
            
            res = self.ml_one_series_polars(
                uid=str(uid[0]) if isinstance(uid, tuple) else str(uid), 
                group_df=group_pl, 
                models=models, 
                horizon=horizon,
                freq='1mo',
                lags=[3, 6, 12],
                lag_transforms={3: [RollingMean(3)]},
                date_features=['month']
            )
            if res is not None:
                results.append(res)

        if not results:
            return pl.DataFrame()
            
        return pl.concat(results)

    def ml_one_series_polars(self, uid, group_df: pl.DataFrame, models, horizon, freq, lags, lag_transforms, date_features, min_obs=12):
        """
        Polars version of ml_one_series
        """
        # Check length
        if len(group_df) < min_obs:
            # Short series logic
            return self._get_short_series_forecast_polars(group_df, horizon, uid)
            
        # Check positive values
        positive_count = group_df.filter(pl.col('y') > 0).height
        if positive_count < min_obs:
             return self._get_short_series_forecast_polars(group_df, horizon, uid)

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore')
                
                mfh = MLForecast(
                    models=models,
                    freq=freq,
                    lags=lags,
                    lag_transforms=lag_transforms,
                    date_features=date_features,
                )
                
                # MLForecast supports Polars inputs
                mfh.fit(group_df, dropna=False)
                forecast = mfh.predict(h=horizon)
                
                # Forecast is returned as Polars DataFrame if input was Polars (usually, or we convert)
                # MLForecast returns the same type as input? Check docs or assume yes. 
                # Actually MLForecast often returns Pandas unless specified or recent versions.
                # Let's assume it might return Pandas, so we convert to Polars to be safe/consistent.
                
                if isinstance(forecast, pd.DataFrame):
                    forecast = pl.from_pandas(forecast)
                
                if not forecast.is_empty():
                    # Rename model column to NHITS if needed and ensure column order
                    cols = forecast.columns
                    model_col = next((c for c in cols if c not in ['ds', 'unique_id']), None)
                    
                    if model_col:
                        forecast = forecast.rename({model_col: 'NHITS'})
                    
                    forecast = forecast.with_columns(pl.lit(uid).alias('unique_id'))
                    
                    # Ensure consistent column order: unique_id, ds, NHITS
                    return forecast.with_columns(pl.col('NHITS').cast(pl.Float64)).select(['unique_id', 'ds', 'NHITS'])
                return None
                
        except Exception as e:
            print(f"[{uid}] Error: {e}")
            return None

    def _get_short_series_forecast_polars(self, group_df: pl.DataFrame, horizon: int, uid: str) -> pl.DataFrame:
        """
        Polars version of short series forecast (SMA)
        """
        last_n = 3
        if len(group_df) < last_n:
            last_n = len(group_df)
            
        if last_n == 0:
            return None
            
        # Mean of last n
        mean_val = group_df.tail(last_n).select(pl.col('y').mean()).item()
        
        # Future dates
        last_date = group_df.select(pl.col('ds').max()).item()
        # Create date range
        # Polars date_range
        dates = pl.date_range(
            start=last_date + relativedelta(months=1),
            end=last_date + relativedelta(months=horizon),
            interval='1mo',
            eager=True
        ).cast(pl.Datetime)
        
        return pl.DataFrame({
            'unique_id': [uid] * len(dates),
            'ds': dates,
            'NHITS': [mean_val] * len(dates)
        }).with_columns(pl.col('NHITS').cast(pl.Float64)).select(['unique_id', 'ds', 'NHITS'])

