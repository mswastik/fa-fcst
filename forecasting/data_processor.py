"""
Data processing utilities for forecasting pipeline.
Extracted from data_service.py for better separation of concerns.
"""
import polars as pl
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List


class DataCleaner:
    """Handles data cleaning and preprocessing operations."""
    
    @staticmethod
    def prepare_data_for_forecasting(df: pl.DataFrame) -> pl.DataFrame:
        """Prepare data with proper handling of missing values and outliers."""
        # Remove outliers using IQR method
        df = df.with_columns(
            q1=pl.col('act_orders_rev').quantile(0.25).over('unique_id'),
            q3=pl.col('act_orders_rev').quantile(0.75).over('unique_id')
        )
        df = df.with_columns(iqr=pl.col('q3') - pl.col('q1'))
        df = df.with_columns(lower_bound=pl.col('q1') - 1.5 * pl.col('iqr'))
        df = df.with_columns(upper_bound=pl.col('q3') + 1.5 * pl.col('iqr'))
        
        # Cap outliers instead of removing them
        df = df.with_columns(
            pl.when(pl.col('act_orders_rev') < pl.col('lower_bound'))
            .then(pl.col('lower_bound'))
            .when(pl.col('act_orders_rev') > pl.col('upper_bound'))
            .then(pl.col('upper_bound'))
            .otherwise(pl.col('act_orders_rev'))
            .alias('act_orders_rev')
        )
        
        return df.drop(['q1', 'q3', 'iqr', 'lower_bound', 'upper_bound'])
    
    @staticmethod
    def filter_last_n_months(df: pl.DataFrame, months: int = 36) -> pl.DataFrame:
        """Filter data to last N months."""
        today = datetime.today()
        last_full_month = datetime(today.year, today.month, 1) - relativedelta(months=1)
        start_date = last_full_month - relativedelta(months=months-1)
        
        return df.filter(
            (pl.col('sales_date').dt.date() >= start_date.date()) &
            (pl.col('sales_date').dt.date() <= last_full_month.date())
        )
    
    @staticmethod
    def prepare_training_data(df: pl.DataFrame) -> pl.DataFrame:
        """Prepare data for training by cleaning and filtering."""
        columns_to_drop = [
            'UOM', 'NPI Flag', 'Pack Content', '`L0 ASP Final Rev', 'Act Orders Rev Val', 
            'L2 DF Final Rev', 'L1 DF Final Rev', 'L0 DF Final Rev', 'L2 Stat Final Rev', 
            '`Fcst DF Final Rev', '`Fcst Stat Final Rev', '`Fcst Stat Prelim Rev', 
            'Fcst DF Final Rev Val'
        ]
        
        clean_df = df.drop([col for col in columns_to_drop if col in df.columns])
        clean_df = clean_df.fill_nan(0)
        
        # Add unique_id if not present
        if 'unique_id' not in clean_df.columns:
            clean_df = clean_df.with_columns(
                unique_id=pl.col('country') + "," + pl.col('catalog_number')
            )
        
        return DataCleaner.filter_last_n_months(clean_df)

    @staticmethod
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
            # Check if column is string type before converting
            if prepared_df.schema['ds'] == pl.Utf8:
                prepared_df = prepared_df.with_columns(
                    pl.col('ds').str.to_datetime(strict=False).alias('ds')
                )
            else:
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


class ForecastDataProcessor:
    """Processes forecast data for integration with original dataset."""
    
    def __init__(self):
        # self.hierarchy_loader = HierarchyLoader() removed as it is an unused class
        pass
    
    def process_forecasts(self, forecasts: pl.DataFrame, original_df: pl.DataFrame, 
                         file_path: str = None) -> pl.DataFrame:
        """Process and integrate forecasts with original data."""
        if forecasts is None:
            return None
        
        # Rename columns and split unique_id
        forecasts = forecasts.rename({'ds': 'sales_date'})
        forecasts = self._split_unique_id(forecasts)
        
        # Join with hierarchy data
        forecasts = self._join_hierarchy_data(forecasts)
        
        # Get model columns (forecast predictions only)
        hierarchy_cols = ['Country', 'CatalogNumber', 'Area', 'Stryker Group Region', 
                         'Region', 'Business Sector', 'Business Unit', 'Franchise', 
                         'Product Line', 'IBP Level 5', 'IBP Level 6', 'IBP Level 7']
        model_cols = [col for col in forecasts.columns 
                     if col not in ['unique_id', 'sales_date'] + hierarchy_cols]
        
        # Add missing model columns to original data
        if 'NHITS' not in original_df.columns:
            original_df = original_df.with_columns(
                [pl.lit(0).alias(col_name) for col_name in model_cols]
            )
        
        # Merge with original data
        merged_df = self._merge_with_original(original_df, forecasts, model_cols)
        
        return merged_df
    
    def _split_unique_id(self, forecasts: pl.DataFrame) -> pl.DataFrame:
        """Split unique_id into Country and CatalogNumber columns."""
        unique_id_columns = ["Country", "CatalogNumber"]
        return forecasts.with_columns(
            pl.col('unique_id').str.split_exact(",", 1)
            .struct.rename_fields(unique_id_columns)
            .alias("fields")
        ).unnest("fields")
    
    def _join_hierarchy_data(self, forecasts: pl.DataFrame) -> pl.DataFrame:
        """Join forecasts with product and location hierarchy data."""
        # ph = self.hierarchy_loader.load_product_hierarchy() # removed as HierarchyLoader is unused
        # lh = self.hierarchy_loader.load_location_hierarchy() # removed as HierarchyLoader is unused
        
        # forecasts = forecasts.join(ph, on='CatalogNumber', how='left') # removed as HierarchyLoader is unused
        # forecasts = forecasts.join(lh, on='Country', how='left') # removed as HierarchyLoader is unused
        
        return forecasts # Return original forecasts as join operations are removed
    
    def _merge_with_original(self, original_df: pl.DataFrame, forecasts: pl.DataFrame, 
                           model_cols: List[str]) -> pl.DataFrame:
        """Merge forecasts with original dataframe."""
        # Define potential join columns
        potential_join_columns = [
            'sales_date', 'CatalogNumber', 'Country', 'Area', 'Stryker Group Region', 
            'Region', 'Business Sector', 'Business Unit', 'Franchise', 'Product Line', 
            'IBP Level 5', 'IBP Level 6', 'IBP Level 7', 'unique_id'
        ]
        
        # Filter join columns to only include those present in both dataframes
        original_cols = set(original_df.columns)
        forecast_cols = set(forecasts.columns)
        join_columns = [col for col in potential_join_columns 
                       if col in original_cols and col in forecast_cols]
        
        # Ensure we have at least unique_id for joining
        if 'unique_id' not in join_columns:
            join_columns = ['unique_id']
        
        # Filter model columns to only include those that exist in original_df
        existing_model_cols = [col for col in model_cols if col in original_cols]
        
        try:
            # Get forecast-specific columns (model predictions)
            forecast_specific_cols = [col for col in forecasts.columns 
                                    if col not in original_cols or col in model_cols]
            
            # Select only join columns + forecast-specific columns from forecasts
            forecast_subset = forecasts.select(join_columns + 
                [col for col in forecast_specific_cols if col not in join_columns])
            
            filtered_original = original_df.filter(
                pl.col('unique_id').is_in(forecasts['unique_id'].unique())
            )
            
            # Drop existing model columns if they exist
            if existing_model_cols:
                filtered_original = filtered_original.drop(existing_model_cols)
            
            # Perform the join with only necessary columns
            merged_df = filtered_original.join(
                forecast_subset, on=join_columns, how='outer', coalesce=True
            )
            
            return merged_df
        except Exception as e:
            print(f"Error in merge operation: {e}")
            print(f"Available join columns: {join_columns}")
            print(f"Original columns: {original_df.columns}")
            print(f"Forecast columns: {forecasts.columns}")
            # Fallback: select only model columns from forecasts for basic merge
            forecast_model_cols = ['unique_id'] + [col for col in forecasts.columns 
                                                  if col in model_cols]
            forecast_subset = forecasts.select(forecast_model_cols)
            return original_df.join(forecast_subset, on='unique_id', how='outer', coalesce=True)
