"""
Model validation and comparison module for forecasting accuracy assessment.
Calculates forecast accuracy for the last 3 months using data only up to 3 months 
before each validation month to simulate real-world 3-month ahead forecasting.
"""
import polars as pl
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
#from forecasting.model_factory import EnsembleForecaster
#from forecasting.simple_forecaster import SimpleModelPipeline
#from forecasting.data_processor import DataCleaner


@dataclass
class ValidationMetrics:
    """Container for validation metrics."""
    mae: float
    mape: float
    rmse: float
    accuracy_percentage: float
    forecast_bias: float
    month: str
    model_name: str


class ModelValidator:
    """Main class for model validation and comparison."""
    
    def __init__(self):
        self.validation_results = []
        self.comparison_results = {}
    
    def validate_last_3_months(self, df_dict: dict) -> Dict[str, List[ValidationMetrics]]:
        """
        Validate forecast accuracy for the last 3 months.
        For each validation month, uses only data up to 3 months before that month.
        """
        print("Starting 3-month validation process...")
        
        # Convert dictionary back to DataFrame
        df = pl.DataFrame(df_dict)
        
        # Get the last 3 months for validation
        today = datetime.today()
        validation_months = []
        
        for i in range(1, 4):  # Last 3 months
            validation_month = today.replace(day=1) - relativedelta(months=i)
            validation_months.append(validation_month)
        
        validation_results = {
            'ensemble': [],
            'nhits': [],
            'lstm': [],
            'autoarima': [],
            'autoets': [],
            'seasonalnaive': [],
            'comparison': []
        }
        
        for validation_month in validation_months:
            print(f"\nValidating for month: {validation_month.strftime('%Y-%m')}")
            
            # Calculate training cutoff (3 months before validation month)
            training_cutoff = validation_month - relativedelta(months=3)
            
            # Get training data (up to 3 months before validation month)
            training_data = df.filter(pl.col('sales_date').dt.date() <= training_cutoff.date())
            
            # Get actual values for the validation month
            actual_data = df.filter(pl.col('sales_date').dt.date() == validation_month.date())
            
            if training_data.height == 0 or actual_data.height == 0:
                print(f"Insufficient data for validation month {validation_month.strftime('%Y-%m')}")
                continue
            
            # Validate all models
            model_results = self._validate_all_models(
                training_data, actual_data, validation_month, file_path
            )
            
            # Store results for each model
            for model_name, metrics in model_results.items():
                if metrics and model_name in validation_results:
                    validation_results[model_name].append(metrics)
        
        # Generate comparison results
        validation_results['comparison'] = self._compare_all_models(validation_results)
        
        self.validation_results = validation_results
        return validation_results
    
    def _validate_all_models(self, training_data: pl.DataFrame, actual_data: pl.DataFrame,
                            validation_month: datetime, file_path: str) -> Dict[str, Optional[ValidationMetrics]]:
        """Validate all available models for a specific month."""
        results = {}
        
        # Prepare training data
        try:
            dft = DataCleaner.prepare_training_data(training_data)
            dft = DataCleaner.prepare_data_for_forecasting(dft)
            df_fr = dft.rename({'sales_date': 'ds', 'Act Orders Rev': 'y'})
            df_fr = df_fr[['unique_id', 'ds', 'y', 'cluster']]
        except Exception as e:
            print(f"  Error preparing training data: {e}")
            return results
        
        # Validate ensemble model
        results['ensemble'] = self._validate_ensemble_model(df_fr, actual_data, validation_month)
        
        # Validate individual neural models
        results['nhits'] = self._validate_individual_neural_model(
            df_fr, actual_data, validation_month, 'NHITS'
        )
        results['lstm'] = self._validate_individual_neural_model(
            df_fr, actual_data, validation_month, 'LSTM'
        )
        
        # Validate individual statistical models
        results['autoarima'] = self._validate_individual_statistical_model(
            df_fr, actual_data, validation_month, 'AutoARIMA'
        )
        results['autoets'] = self._validate_individual_statistical_model(
            df_fr, actual_data, validation_month, 'AutoETS'
        )
        results['seasonalnaive'] = self._validate_individual_statistical_model(
            df_fr, actual_data, validation_month, 'SeasonalNaive'
        )
        
        return results
    
    def _validate_ensemble_model(self, df_fr: pl.DataFrame, actual_data: pl.DataFrame,
                                validation_month: datetime) -> Optional[ValidationMetrics]:
        """Validate ensemble model."""
        try:
            print(f"  Validating ensemble model...")
            
            # Create forecaster and generate forecasts
            forecaster = EnsembleForecaster(horizon=60)
            forecasts = forecaster.generate_forecasts(df_fr)
            
            if forecasts is None or forecasts.height == 0:
                print("    No ensemble forecasts generated")
                return None
            
            # Extract forecasts for validation month
            validation_forecasts = self._extract_validation_forecasts(
                forecasts, validation_month, 3
            )
            
            if validation_forecasts.height == 0:
                print("    No validation forecasts found for ensemble model")
                return None
            
            # Calculate metrics
            return self._calculate_metrics(
                validation_forecasts, actual_data, validation_month, "Ensemble"
            )
            
        except Exception as e:
            print(f"    Error validating ensemble model: {e}")
            return None
    
    def _validate_individual_neural_model(self, df_fr: pl.DataFrame, actual_data: pl.DataFrame,
                                         validation_month: datetime, model_name: str) -> Optional[ValidationMetrics]:
        """Validate individual neural model."""
        try:
            print(f"  Validating {model_name} model...")
            
            from forecasting.model_factory import NeuralModelFactory, ModelConfiguration
            from neuralforecast import NeuralForecast
            
            # Prepare data without cluster column for individual models
            df_model = df_fr[['unique_id', 'ds', 'y']]
            
            # Create model configuration
            config = ModelConfiguration(horizon=60)
            factory = NeuralModelFactory(config)
            
            # Calculate batch sizes
            n_series = len(df_model['unique_id'].unique())
            batch_size, windows_batch_size = config.calculate_batch_sizes(n_series)
            
            # Create specific model
            if model_name == 'NHITS':
                model = factory.create_nhits_model(batch_size, windows_batch_size)
            elif model_name == 'LSTM':
                model = factory.create_lstm_model(batch_size)
            else:
                print(f"    Unknown neural model: {model_name}")
                return None
            
            # Train and predict
            nf = NeuralForecast(models=[model], freq='M')
            nf.fit(df=df_model.fill_nan(0).fill_null(0))
            forecasts = nf.predict()
            
            if forecasts is None or forecasts.height == 0:
                print(f"    No {model_name} forecasts generated")
                return None
            
            # Extract forecasts for validation month
            validation_forecasts = self._extract_validation_forecasts(
                forecasts, validation_month, 3
            )
            
            if validation_forecasts.height == 0:
                print(f"    No validation forecasts found for {model_name}")
                return None
            
            # Calculate metrics
            return self._calculate_metrics(
                validation_forecasts, actual_data, validation_month, model_name
            )
            
        except Exception as e:
            print(f"    Error validating {model_name} model: {e}")
            return None
    
    def _validate_individual_statistical_model(self, df_fr: pl.DataFrame, actual_data: pl.DataFrame,
                                              validation_month: datetime, model_name: str) -> Optional[ValidationMetrics]:
        """Validate individual statistical model."""
        try:
            print(f"  Validating {model_name} model...")
            
            from forecasting.model_factory import StatisticalModelFactory
            from statsforecast import StatsForecast
            from statsforecast.models import AutoARIMA, AutoETS, SeasonalNaive
            
            # Prepare data without cluster column
            df_model = df_fr[['unique_id', 'ds', 'y']]
            
            # Create specific model
            if model_name == 'AutoARIMA':
                model = AutoARIMA(season_length=12)
            elif model_name == 'AutoETS':
                model = AutoETS(season_length=12)
            elif model_name == 'SeasonalNaive':
                model = SeasonalNaive(season_length=12)
            else:
                print(f"    Unknown statistical model: {model_name}")
                return None
            
            # Train and predict
            sf = StatsForecast(models=[model], freq='MS')
            sf.fit(df=df_model.fill_nan(0).fill_null(0))
            forecasts = sf.predict(h=60)
            
            if forecasts is None or forecasts.height == 0:
                print(f"    No {model_name} forecasts generated")
                return None
            
            # Extract forecasts for validation month
            validation_forecasts = self._extract_validation_forecasts(
                forecasts, validation_month, 3
            )
            
            if validation_forecasts.height == 0:
                print(f"    No validation forecasts found for {model_name}")
                return None
            
            # Calculate metrics
            return self._calculate_metrics(
                validation_forecasts, actual_data, validation_month, model_name
            )
            
        except Exception as e:
            print(f"    Error validating {model_name} model: {e}")
            return None
    
    def _extract_validation_forecasts(self, forecasts: pl.DataFrame, 
                                    validation_month: datetime, months_ahead: int) -> pl.DataFrame:
        """Extract forecasts for the validation month (3 months ahead from training cutoff)."""
        try:
            # Convert validation month to the format used in forecasts
            if 'ds' in forecasts.columns:
                date_col = 'ds'
            elif 'sales_date' in forecasts.columns:
                date_col = 'sales_date'
            else:
                print("    No date column found in forecasts")
                return pl.DataFrame()
            
            # Filter forecasts for the validation month
            validation_forecasts = forecasts.filter(
                pl.col(date_col).dt.date() == validation_month.date()
            )
            
            return validation_forecasts
            
        except Exception as e:
            print(f"    Error extracting validation forecasts: {e}")
            return pl.DataFrame()
    
    def _calculate_metrics(self, forecasts: pl.DataFrame, actuals: pl.DataFrame,
                          validation_month: datetime, model_name: str) -> ValidationMetrics:
        """Calculate validation metrics comparing forecasts to actuals."""
        try:
            # Merge forecasts with actuals on unique_id
            if 'unique_id' not in forecasts.columns:
                # Create unique_id if not present
                if 'country' in forecasts.columns and 'catalog_number' in forecasts.columns:
                    forecasts = forecasts.with_columns(
                        unique_id=pl.col('country') + "," + pl.col('catalog_number')
                    )
                else:
                    print(f"    Cannot create unique_id for {model_name}")
                    return None
            
            if 'unique_id' not in actuals.columns:
                actuals = actuals.with_columns(
                    unique_id=pl.col('country') + "," + pl.col('catalog_number')
                )
            
            # Get forecast values (try different column names based on model)
            forecast_cols = ['ensemble', 'NHITS', 'LSTM', 'AutoARIMA', 'AutoETS', 'SeasonalNaive', 'y', 'forecast']
            forecast_col = None
            
            # First try to match the model name exactly
            if model_name in forecasts.columns:
                forecast_col = model_name
            else:
                # Fall back to common column names
                for col in forecast_cols:
                    if col in forecasts.columns:
                        forecast_col = col
                        break
            
            if forecast_col is None:
                print(f"    No forecast column found for {model_name}")
                print(f"    Available columns: {forecasts.columns}")
                return None
            
            # Merge data
            merged = forecasts.select(['unique_id', forecast_col]).join(
                actuals.select(['unique_id', 'act_orders_rev']),
                on='unique_id',
                how='inner'
            )
            
            if merged.height == 0:
                print(f"    No matching data found for {model_name}")
                return None
            
            # Extract values
            forecast_values = merged[forecast_col].to_numpy()
            actual_values = merged['act_orders_rev'].to_numpy()
            
            # Remove any null/nan values
            valid_mask = ~(np.isnan(forecast_values) | np.isnan(actual_values))
            forecast_values = forecast_values[valid_mask]
            actual_values = actual_values[valid_mask]
            
            if len(forecast_values) == 0:
                print(f"    No valid data points for {model_name}")
                return None
            
            # Calculate metrics
            mae = np.mean(np.abs(forecast_values - actual_values))
            rmse = np.sqrt(np.mean((forecast_values - actual_values) ** 2))
            
            # MAPE (handle division by zero)
            mape_values = np.abs((actual_values - forecast_values) / np.where(actual_values == 0, 1, actual_values))
            mape = np.mean(mape_values) * 100
            
            # Accuracy percentage (1 - MAPE/100)
            accuracy_percentage = max(0, 100 - mape)
            
            # Forecast bias
            forecast_bias = np.mean(forecast_values - actual_values)
            
            print(f"    {model_name} - MAE: {mae:.2f}, MAPE: {mape:.2f}%, Accuracy: {accuracy_percentage:.2f}%")
            
            return ValidationMetrics(
                mae=mae,
                mape=mape,
                rmse=rmse,
                accuracy_percentage=accuracy_percentage,
                forecast_bias=forecast_bias,
                month=validation_month.strftime('%Y-%m'),
                model_name=model_name
            )
            
        except Exception as e:
            print(f"    Error calculating metrics for {model_name}: {e}")
            return None
    
    def _compare_all_models(self, validation_results: Dict[str, List[ValidationMetrics]]) -> List[Dict]:
        """Compare performance between all models."""
        comparison = []
        
        # Get all model names (excluding comparison)
        model_names = [key for key in validation_results.keys() if key != 'comparison']
        
        # Create month-wise results dictionary
        results_by_month = {}
        for model_name in model_names:
            for result in validation_results.get(model_name, []):
                if result:
                    if result.month not in results_by_month:
                        results_by_month[result.month] = {}
                    results_by_month[result.month][model_name] = result
        
        # Create comparison for each month
        for month in sorted(results_by_month.keys()):
            month_results = results_by_month[month]
            
            comparison_item = {'month': month}
            
            # Add metrics for each model
            for model_name in model_names:
                if model_name in month_results:
                    result = month_results[model_name]
                    comparison_item[f'{model_name}_accuracy'] = result.accuracy_percentage
                    comparison_item[f'{model_name}_mae'] = result.mae
                    comparison_item[f'{model_name}_mape'] = result.mape
                else:
                    comparison_item[f'{model_name}_accuracy'] = None
                    comparison_item[f'{model_name}_mae'] = None
                    comparison_item[f'{model_name}_mape'] = None
            
            # Determine best model for this month
            best_model = None
            best_accuracy = -1
            
            for model_name in model_names:
                if model_name in month_results:
                    accuracy = month_results[model_name].accuracy_percentage
                    if accuracy > best_accuracy:
                        best_accuracy = accuracy
                        best_model = model_name
            
            comparison_item['best_model'] = best_model
            comparison.append(comparison_item)
        
        return comparison
    
    def get_summary_statistics(self) -> Dict:
        """Get summary statistics across all validation results."""
        if not self.validation_results:
            return {}
        
        summary = {}
        
        # Add summary stats for all models
        model_names = [key for key in self.validation_results.keys() if key != 'comparison']
        for model_name in model_names:
            summary[model_name] = self._calculate_summary_stats(self.validation_results.get(model_name, []))
        
        summary['overall_comparison'] = self._get_overall_comparison()
        
        return summary
    
    def _calculate_summary_stats(self, metrics_list: List[ValidationMetrics]) -> Dict:
        """Calculate summary statistics for a list of metrics."""
        if not metrics_list:
            return {
                'avg_accuracy': 0,
                'min_accuracy': 0,
                'max_accuracy': 0,
                'avg_mae': 0,
                'avg_mape': 0,
                'num_validations': 0
            }
        
        accuracies = [m.accuracy_percentage for m in metrics_list]
        maes = [m.mae for m in metrics_list]
        mapes = [m.mape for m in metrics_list]
        
        return {
            'avg_accuracy': np.mean(accuracies),
            'min_accuracy': np.min(accuracies),
            'max_accuracy': np.max(accuracies),
            'avg_mae': np.mean(maes),
            'avg_mape': np.mean(mapes),
            'num_validations': len(metrics_list)
        }
    
    def _get_overall_comparison(self) -> Dict:
        """Get overall comparison between all models."""
        comparison_results = self.validation_results.get('comparison', [])
        
        if not comparison_results:
            return {}
        
        # Count wins for each model
        model_wins = {}
        total_comparisons = len(comparison_results)
        
        for comp in comparison_results:
            best_model = comp.get('best_model')
            if best_model:
                model_wins[best_model] = model_wins.get(best_model, 0) + 1
        
        # Calculate win rates
        win_rates = {}
        for model, wins in model_wins.items():
            win_rates[f'{model}_wins'] = wins
            win_rates[f'{model}_win_rate'] = (wins / total_comparisons * 100) if total_comparisons > 0 else 0
        
        win_rates['total_comparisons'] = total_comparisons
        return win_rates


class ValidationReportGenerator:
    """Generate validation reports and summaries."""
    
    @staticmethod
    def generate_text_report(validation_results: Dict) -> str:
        """Generate a text-based validation report."""
        report = []
        report.append("=" * 60)
        report.append("FORECAST VALIDATION REPORT - LAST 3 MONTHS")
        report.append("=" * 60)
        report.append("")
        
        # Ensemble results
        ensemble_results = validation_results.get('ensemble', [])
        if ensemble_results:
            report.append("ENSEMBLE MODEL RESULTS:")
            report.append("-" * 30)
            for result in ensemble_results:
                report.append(f"Month: {result.month}")
                report.append(f"  Accuracy: {result.accuracy_percentage:.2f}%")
                report.append(f"  MAE: {result.mae:.2f}")
                report.append(f"  MAPE: {result.mape:.2f}%")
                report.append(f"  RMSE: {result.rmse:.2f}")
                report.append("")
        
        # Simple model results
        simple_results = validation_results.get('simple_nhits', [])
        if simple_results:
            report.append("SIMPLE NHITS MODEL RESULTS:")
            report.append("-" * 30)
            for result in simple_results:
                report.append(f"Month: {result.month}")
                report.append(f"  Accuracy: {result.accuracy_percentage:.2f}%")
                report.append(f"  MAE: {result.mae:.2f}")
                report.append(f"  MAPE: {result.mape:.2f}%")
                report.append(f"  RMSE: {result.rmse:.2f}")
                report.append("")
        
        # Comparison results
        comparison_results = validation_results.get('comparison', [])
        if comparison_results:
            report.append("MODEL COMPARISON:")
            report.append("-" * 30)
            for comp in comparison_results:
                report.append(f"Month: {comp['month']}")
                if comp['ensemble_accuracy'] and comp['simple_accuracy']:
                    report.append(f"  Ensemble: {comp['ensemble_accuracy']:.2f}% accuracy")
                    report.append(f"  Simple NHITS: {comp['simple_accuracy']:.2f}% accuracy")
                    report.append(f"  Winner: {comp['better_model']}")
                report.append("")
        
        return "\n".join(report)
    
    @staticmethod
    def generate_summary_table(validation_results: Dict) -> pl.DataFrame:
        """Generate a summary table for display."""
        comparison_results = validation_results.get('comparison', [])
        
        if not comparison_results:
            return pl.DataFrame()
        
        # Convert to DataFrame
        summary_data = []
        for comp in comparison_results:
            summary_data.append({
                'Month': comp['month'],
                'Ensemble_Accuracy': f"{comp['ensemble_accuracy']:.1f}%" if comp['ensemble_accuracy'] else "N/A",
                'Simple_Accuracy': f"{comp['simple_accuracy']:.1f}%" if comp['simple_accuracy'] else "N/A",
                'Ensemble_MAE': f"{comp['ensemble_mae']:.2f}" if comp['ensemble_mae'] else "N/A",
                'Simple_MAE': f"{comp['simple_mae']:.2f}" if comp['simple_mae'] else "N/A",
                'Better_Model': comp['better_model'] or "N/A"
            })
        
        return pl.DataFrame(summary_data)
