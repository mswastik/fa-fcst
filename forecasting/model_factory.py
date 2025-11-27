"""
Model factory for creating and configuring forecasting models.
Extracted from data_service.py for better separation of concerns.
"""
from typing import List, Tuple
import polars as pl
from neuralforecast import NeuralForecast
from neuralforecast.models import NHITS, LSTM
from neuralforecast.losses.pytorch import RMSE
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, SeasonalNaive, AutoTBATS


class ModelConfiguration:
    """Configuration class for model parameters."""
    
    def __init__(self, horizon: int = 60, input_size: int = None):
        self.horizon = horizon
        self.input_size = input_size or horizon
        self.max_steps = 10
        self.learning_rate = 1e-3
        self.random_seed = 42
        self.val_check_steps = 25
    
    def calculate_batch_sizes(self, n_series: int) -> Tuple[int, int]:
        """Calculate appropriate batch sizes based on number of series."""
        batch_size = max(1, min(16, n_series // 2))
        windows_batch_size = max(1, min(16, n_series // 2))
        return batch_size, windows_batch_size


class NeuralModelFactory:
    """Factory for creating neural forecasting models."""
    
    def __init__(self, config: ModelConfiguration):
        self.config = config
    
    def create_nhits_model(self, batch_size: int, windows_batch_size: int) -> NHITS:
        """Create and configure NHITS model."""
        return NHITS(
            h=self.config.horizon,
            input_size=self.config.input_size,
            max_steps=self.config.max_steps,
            stack_types=['identity'] * 2,
            n_blocks=[1, 1],
            mlp_units=[[64, 32], [32, 16]],
            n_pool_kernel_size=[2, 2],
            n_freq_downsample=[2, 2],
            interpolation_mode='nearest',
            activation='ReLU',
            dropout_prob_theta=0.1,
            scaler_type='robust',
            loss=RMSE(),
            valid_loss=RMSE(),
            batch_size=batch_size,
            windows_batch_size=windows_batch_size,
            random_seed=self.config.random_seed,
            start_padding_enabled=True,
            learning_rate=self.config.learning_rate,
            val_check_steps=self.config.val_check_steps,
        )
    
    def create_lstm_model(self, batch_size: int) -> LSTM:
        """Create and configure LSTM model."""
        return LSTM(
            h=self.config.horizon,
            input_size=self.config.input_size,
            max_steps=self.config.max_steps,
            encoder_hidden_size=32,
            encoder_n_layers=1,
            encoder_dropout=0.1,
            scaler_type='robust',
            loss=RMSE(),
            valid_loss=RMSE(),
            batch_size=batch_size,
            random_seed=self.config.random_seed,
            learning_rate=self.config.learning_rate,
        )


class StatisticalModelFactory:
    """Factory for creating statistical forecasting models."""
    
    @staticmethod
    def create_statistical_models(season_length: int = 12) -> List:
        """Create statistical forecasting models."""
        return [
            AutoARIMA(season_length=season_length, approximation=False, stepwise=False),
            AutoETS(season_length=season_length),
            SeasonalNaive(season_length=season_length),
            AutoTBATS(season_length=season_length)
        ]


class ForecastProcessor:
    """Handles forecast processing and combination."""
    
    def __init__(self, config: ModelConfiguration):
        self.config = config
        self.neural_factory = NeuralModelFactory(config)
        self.stat_factory = StatisticalModelFactory()
    
    def process_cluster(self, cluster_data: pl.DataFrame, cluster_id: str) -> pl.DataFrame:
        """Process a single cluster and generate forecasts."""
        print(f"Processing cluster {cluster_id} with {len(cluster_data['unique_id'].unique())} series")
        
        # Prepare data - ensure item_skey and location_skey are retained
        # for consistent unique_id generation later if needed.
        # Also, ensure 'ds' and 'y' are present for forecasting models.
        required_cols = ['unique_id', 'ds', 'y']
        if 'item_skey' in cluster_data.columns:
            required_cols.append('item_skey')
        if 'location_skey' in cluster_data.columns:
            required_cols.append('location_skey')

        cluster_data = cluster_data[required_cols]
        n_series = len(cluster_data['unique_id'].unique())
        batch_size, windows_batch_size = self.config.calculate_batch_sizes(n_series)
        
        # Create models
        neural_models = self._create_neural_models(batch_size, windows_batch_size)
        stat_models = self.stat_factory.create_statistical_models()
        
        # Generate forecasts
        neural_forecasts = self._generate_neural_forecasts(neural_models, cluster_data)
        stat_forecasts = self._generate_statistical_forecasts(stat_models, cluster_data)
        
        # Combine forecasts
        combined_forecast = self._combine_forecasts(neural_forecasts, stat_forecasts, cluster_id)
        
        return combined_forecast
    
    def _create_neural_models(self, batch_size: int, windows_batch_size: int) -> List:
        """Create neural models for the cluster."""
        nhits = self.neural_factory.create_nhits_model(batch_size, windows_batch_size)
        lstm = self.neural_factory.create_lstm_model(batch_size)
        return [nhits, lstm]
    
    def _generate_neural_forecasts(self, models: List, data: pl.DataFrame) -> pl.DataFrame:
        """Generate forecasts using neural models with data validation."""
        # Validate data has sufficient length for training
        min_required_length = max(56, self.config.horizon * 2)  # At least 2x horizon or input_size
        
        # Check each unique_id has sufficient data
        data_lengths = data.group_by('unique_id').agg(pl.len().alias('length'))
        insufficient_series = data_lengths.filter(pl.col('length') < min_required_length)
        
        if insufficient_series.height > 0:
            print(f"Warning: {insufficient_series.height} series have insufficient data for neural training")
            # Filter out series with insufficient data
            valid_series = data_lengths.filter(pl.col('length') >= min_required_length)['unique_id']
            if valid_series.len() == 0:
                print("No series have sufficient data for neural forecasting, skipping neural models")
                return pl.DataFrame()
            data = data.filter(pl.col('unique_id').is_in(valid_series))
        
        try:
            nf = NeuralForecast(models=models, freq='M')
            nf.fit(df=data.fill_nan(0).fill_null(0))
            return nf.predict()
        except Exception as e:
            print(f"Neural forecasting failed: {e}")
            print("Falling back to statistical models only")
            return pl.DataFrame()
    
    def _generate_statistical_forecasts(self, models: List, data: pl.DataFrame) -> pl.DataFrame:
        """Generate forecasts using statistical models."""
        sf = StatsForecast(models=models, freq='MS')
        sf.fit(df=data.fill_nan(0).fill_null(0))
        return sf.predict(h=self.config.horizon)
    
    def _combine_forecasts(self, neural_forecasts: pl.DataFrame, 
                          stat_forecasts: pl.DataFrame, cluster_id: str) -> pl.DataFrame:
        """Combine neural and statistical forecasts."""
        # Handle case where neural forecasts are empty
        if neural_forecasts.height == 0:
            print(f"Using statistical forecasts only for cluster {cluster_id}")
            combined_forecast = stat_forecasts
        else:
            combined_forecast = neural_forecasts.join(
                stat_forecasts, on=['unique_id', 'ds'], how='outer', coalesce=True
            )
        
        # Create ensemble (simple average of available models)
        model_cols = [col for col in combined_forecast.columns if col not in ['unique_id', 'ds']]
        
        if model_cols:
            combined_forecast = combined_forecast.with_columns(
                ensemble=pl.concat_list([pl.col(col) for col in model_cols]).list.mean()
            )
            combined_forecast = combined_forecast.with_columns(cluster=pl.lit(str(cluster_id)))
            return combined_forecast
        else:
            print(f"No valid forecasts generated for cluster {cluster_id}")
            return pl.DataFrame()


class EnsembleForecaster:
    """Main class for ensemble forecasting across clusters."""
    
    def __init__(self, horizon: int = 60):
        self.config = ModelConfiguration(horizon=horizon)
        self.processor = ForecastProcessor(self.config)
    
    def generate_forecasts(self, df_fr: pl.DataFrame) -> pl.DataFrame:
        """Generate forecasts for all clusters in the dataset."""
        # Calculate input size based on available data
        available_months = len(df_fr['ds'].unique())
        self.config.input_size = min(self.config.horizon, available_months)
        
        print(f"Forecasting horizon: {self.config.horizon} months")
        print(f"Input size: {self.config.input_size} months")
        
        cluster_forecasts = []
        
        for cluster_id in df_fr['cluster'].unique():
            if cluster_id is None:
                continue
            
            cluster_data = df_fr.filter(pl.col('cluster') == cluster_id)
            combined_forecast = self.processor.process_cluster(cluster_data, cluster_id)
            
            if combined_forecast is not None:
                cluster_forecasts.append(combined_forecast)
        
        print(f"Generated forecasts for {len(cluster_forecasts)} clusters")
        
        # Combine all forecasts
        if cluster_forecasts:
            return pl.concat(cluster_forecasts)
        else:
            print("No successful forecasts generated")
            return None
