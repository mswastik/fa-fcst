"""
Forecasting service module.
Handles the execution of forecasting models, including per-series logic and short-series handling.
"""
import polars as pl
import pandas as pd
from mlforecast import MLForecast
from mlforecast.lag_transforms import RollingMean
from sklearn.ensemble import VotingRegressor
import xgboost as xgb
from statsforecast.core import StatsForecast
from statsforecast.models import AutoARIMA, MSTL, AutoCES, AutoMFLES, AutoTBATS
import warnings
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
            'xgb': [mean_val] * horizon,
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
        Run forecasts for all series in the dataframe using multiple models.
        """
        # Optimization: We can use Polars partition_by to get list of DataFrames
        groups = df.partition_by("unique_id", as_dict=True)

        # Define MLForecast models (XGBoost)
        xgb1 = xgb.XGBRegressor(random_state=0, booster='gblinear')
        xgb2 = xgb.XGBRegressor(random_state=0)
        ml_models = {
            'xgb': VotingRegressor([('xgb1', xgb1), ('xgb2', xgb2)])
        }

        sf_models = [
            # AutoARIMA: stepwise=False and approximation=False are CRITICAL for avoiding flat forecasts on seasonal data
            AutoARIMA(season_length=12, approximation=True, stepwise=True),
            MSTL(season_length=[12]),
            AutoCES(season_length=12),
            AutoMFLES(season_length=12, test_size=12),
            AutoTBATS(season_length=12)
        ]

        results = []
        print(f"Processing {len(groups)} series...")

        for uid, group_pl in groups.items():
            uid_str = str(uid[0]) if isinstance(uid, tuple) else str(uid)

            # 1. Run MLForecast (XGBoost)
            ml_res = self.ml_one_series_polars(
                uid=uid_str,
                group_df=group_pl,
                models=ml_models,
                horizon=horizon,
                freq='1mo',
                lags=[3, 6, 12],
                lag_transforms={3: [RollingMean(3)]},
                date_features=['month']
            )

            # 2. Run StatsForecast (AutoARIMA, MSTL, AutoCES, AutoMFLES)
            # StatsForecast expects pandas DataFrame with unique_id, ds, y
            group_pd = group_pl.to_pandas()
            if 'unique_id' not in group_pd.columns:
                group_pd['unique_id'] = uid_str

            try:
                sf = StatsForecast(
                    models=sf_models,
                    freq='MS',
                    n_jobs=1
                )
                sf.fit(group_pd)
                sf_res = sf.predict(h=horizon)

                # Convert to Polars
                sf_res_pl = pl.from_pandas(sf_res)

                # Rename 'ds' to match if needed (StatsForecast returns 'ds')
                # Rename 'CES' to 'AutoCES' if present
                if 'CES' in sf_res_pl.columns:
                    sf_res_pl = sf_res_pl.rename({'CES': 'AutoCES'})

                # Ensure unique_id is present
                if 'unique_id' not in sf_res_pl.columns:
                    sf_res_pl = sf_res_pl.with_columns(pl.lit(uid_str).alias('unique_id'))

            except Exception as e:
                print(f"[{uid_str}] Error in StatsForecast: {e}")
                sf_res_pl = None

            # 3. Merge results with type casting to Float32
            if ml_res is not None and sf_res_pl is not None:
                # Join on unique_id and ds
                # ml_res has: unique_id, ds, xgb
                # sf_res_pl has: unique_id, ds, AutoARIMA, MSTL, AutoCES, AutoMFLES

                # Ensure ds types match and cast all forecast columns to Float32
                ml_res = ml_res.with_columns(pl.col('ds').cast(pl.Datetime))
                sf_res_pl = sf_res_pl.with_columns(pl.col('ds').cast(pl.Datetime))

                # Cast forecast columns to Float32 for consistency
                for col in [c for c in ml_res.columns if c not in ['unique_id', 'ds']]:
                    ml_res = ml_res.with_columns(pl.col(col).cast(pl.Float32))
                for col in [c for c in sf_res_pl.columns if c not in ['unique_id', 'ds']]:
                    sf_res_pl = sf_res_pl.with_columns(pl.col(col).cast(pl.Float32))

                # Replace negative forecasts with zero for all models
                ml_non_forecast_cols = ['unique_id', 'ds']
                for col in [c for c in ml_res.columns if c not in ml_non_forecast_cols]:
                    ml_res = ml_res.with_columns(
                        pl.when(pl.col(col) < 0).then(0.0).otherwise(pl.col(col)).alias(col)
                    )

                sf_non_forecast_cols = ['unique_id', 'ds']
                for col in [c for c in sf_res_pl.columns if c not in sf_non_forecast_cols]:
                    sf_res_pl = sf_res_pl.with_columns(
                        pl.when(pl.col(col) < 0).then(0.0).otherwise(pl.col(col)).alias(col)
                    )

                combined = ml_res.join(sf_res_pl, on=['unique_id', 'ds'], how='left')
                results.append(combined)

            elif ml_res is not None:
                # Cast to Float32
                for col in [c for c in ml_res.columns if c not in ['unique_id', 'ds']]:
                    ml_res = ml_res.with_columns(pl.col(col).cast(pl.Float32))

                # Replace negative forecasts with zero for ML models
                ml_non_forecast_cols = ['unique_id', 'ds']
                for col in [c for c in ml_res.columns if c not in ml_non_forecast_cols]:
                    ml_res = ml_res.with_columns(
                        pl.when(pl.col(col) < 0).then(0.0).otherwise(pl.col(col)).alias(col)
                    )

                results.append(ml_res)
            elif sf_res_pl is not None:
                # Cast to Float32
                for col in [c for c in sf_res_pl.columns if c not in ['unique_id', 'ds']]:
                    sf_res_pl = sf_res_pl.with_columns(pl.col(col).cast(pl.Float32))

                # Replace negative forecasts with zero for statistical models
                sf_non_forecast_cols = ['unique_id', 'ds']
                for col in [c for c in sf_res_pl.columns if c not in sf_non_forecast_cols]:
                    sf_res_pl = sf_res_pl.with_columns(
                        pl.when(pl.col(col) < 0).then(0.0).otherwise(pl.col(col)).alias(col)
                    )

                results.append(sf_res_pl)

        if not results:
            return pl.DataFrame()

        return pl.concat(results, how='diagonal')

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
                    # Ensure column order
                    cols = forecast.columns

                    forecast = forecast.with_columns(pl.lit(uid).alias('unique_id'))

                    # Ensure consistent column order: unique_id, ds, xgb
                    # We don't rename to NHITS anymore
                    return forecast
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
            'xgb': [mean_val] * len(dates)
        }).with_columns(pl.col('xgb').cast(pl.Float32)).select(['unique_id', 'ds', 'xgb'])

