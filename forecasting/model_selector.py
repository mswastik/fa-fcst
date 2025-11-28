"""
Model Selection and Ensemble Forecasting Service

This module provides intelligent model selection and ensemble creation for forecasts.
Evaluates multiple forecasting models and selects the best one or creates an ensemble.
"""
import polars as pl
import numpy as np
from typing import Dict, List, Tuple, Optional
from scipy import stats
import warnings


class ModelSelector:
    """Service for evaluating forecast quality and selecting best models."""
    
    def __init__(self):
        """Initialize the model selector with default weights."""
        self.weights = {
            'level_consistency': 0.30,
            'trend_reasonableness': 0.40,
            'seasonality': 0.20,
            'stability': 0.10,
            'non_negativity': 0
        }
        
        # Model parameter counts for BIC calculation (optional)
        self.model_params = {
            'xgb': 10,
            'AutoARIMA': 5,
            'MSTL': 8,
            'AutoCES': 4,
            'AutoMFLES': 6,
            'AutoTBATS': 7
        }
    
    def evaluate_forecast_quality(
        self, 
        forecast_values: np.ndarray, 
        historical_values: np.ndarray,
        model_name: str
    ) -> Dict[str, float]:
        """
        Evaluate forecast quality based on multiple criteria.
        
        Args:
            forecast_values: Array of forecast values
            historical_values: Array of historical actual values
            model_name: Name of the model
            
        Returns:
            Dictionary with scores for each criterion and total weighted score
        """
        scores = {}
        
        # 1. Level Consistency Score (30%)
        scores['level_consistency'] = self._calculate_level_consistency(
            forecast_values, historical_values
        )
        
        # 2. Trend Reasonableness Score (25%)
        scores['trend_reasonableness'] = self._calculate_trend_score(forecast_values)
        
        # 3. Seasonality Preservation Score (25%)
        scores['seasonality'] = self._calculate_seasonality_score(
            forecast_values, historical_values
        )
        
        # 4. Forecast Stability Score (15%)
        scores['stability'] = self._calculate_stability_score(forecast_values)
        
        # 5. Non-negativity Score (5%)
        scores['non_negativity'] = self._calculate_non_negativity_score(forecast_values)
        
        # Calculate weighted total score
        total_score = sum(
            scores[criterion] * self.weights[criterion] 
            for criterion in scores.keys()
        )
        
        scores['total'] = total_score
        scores['model_name'] = model_name
        
        return scores
    
    def _calculate_level_consistency(
        self, 
        forecast_values: np.ndarray, 
        historical_values: np.ndarray
    ) -> float:
        """
        Compare first 3 months of forecast to last 3 months of actuals.
        
        Returns score between 0 and 1 (higher is better).
        """
        if len(historical_values) < 3 or len(forecast_values) < 3:
            return 0.5  # Neutral score if insufficient data
        
        # Get last 3 months of historical and first 3 months of forecast
        recent_actuals = historical_values[-3:]
        forecast_start = forecast_values[:3]
        
        # Calculate average levels
        avg_actual = np.mean(recent_actuals)
        avg_forecast = np.mean(forecast_start)
        
        # Avoid division by zero
        if avg_actual == 0:
            if avg_forecast == 0:
                return 1.0  # Both zero, perfect match
            return 0.0  # Forecast has value when actual is zero
        
        # Calculate percentage deviation
        deviation = abs(avg_forecast - avg_actual) / avg_actual
        
        # Convert to score: 0% deviation = 1.0, 50%+ deviation = 0.0
        if deviation <= 0.5:
            score = 1.0 - (deviation / 0.5)
        else:
            score = 0.0
        
        return max(0.0, min(1.0, score))
    
    def _calculate_trend_score(self, forecast_values: np.ndarray) -> float:
        """
        Evaluate trend reasonableness - penalize unrealistic steep trends.
        
        Returns score between 0 and 1 (higher is better).
        """
        if len(forecast_values) < 12:
            return 0.5  # Neutral score for short forecasts
        
        # Calculate overall growth rate
        start_avg = np.mean(forecast_values[:6])
        end_avg = np.mean(forecast_values[-6:])
        
        # Avoid division by zero
        if start_avg == 0:
            if end_avg == 0:
                growth_rate = 0.0
            else:
                return 0.0  # Unrealistic: goes from 0 to positive
        else:
            growth_rate = (end_avg - start_avg) / start_avg
        
        # Check for flat forecasts (very low variance)
        std = np.std(forecast_values)
        mean = np.mean(forecast_values)
        cv = std / mean if mean > 0 else 0
        
        # Penalize flat forecasts
        if cv < 0.02:  # Coefficient of variation < 2%
            return 0.3
        
        # Penalize excessive growth (>200% over forecast horizon)
        horizon_years = len(forecast_values) / 12
        annualized_growth = growth_rate / horizon_years if horizon_years > 0 else 0
        
        if abs(annualized_growth) > 2.0:  # >200% annual growth
            return 0.2
        elif abs(annualized_growth) > 1.0:  # >100% annual growth
            return 0.5
        elif abs(annualized_growth) > 0.5:  # >50% annual growth
            return 0.7
        else:
            return 1.0
    
    def _calculate_seasonality_score(
        self, 
        forecast_values: np.ndarray, 
        historical_values: np.ndarray
    ) -> float:
        """
        Evaluate seasonality preservation compared to historical data.
        
        Returns score between 0 and 1 (higher is better).
        """
        if len(historical_values) < 24 or len(forecast_values) < 12:
            return 0.5  # Neutral score if insufficient data for seasonality
        
        # Calculate coefficient of variation for forecast
        forecast_cv = np.std(forecast_values) / np.mean(forecast_values) if np.mean(forecast_values) > 0 else 0
        
        # Calculate coefficient of variation for historical (monthly seasonality)
        if len(historical_values) >= 24:
            # Use last 24 months for comparison
            historical_cv = np.std(historical_values[-24:]) / np.mean(historical_values[-24:]) if np.mean(historical_values[-24:]) > 0 else 0
        else:
            historical_cv = np.std(historical_values) / np.mean(historical_values) if np.mean(historical_values) > 0 else 0
        
        # Compare forecast CV to historical CV
        # Good forecasts should have similar seasonality amplitude
        if historical_cv == 0:
            if forecast_cv < 0.05:
                return 1.0  # Both flat, good match
            return 0.5  # Historical flat, forecast has variation
        
        cv_ratio = forecast_cv / historical_cv
        
        # Score based on how close the ratio is to 1.0
        if 0.5 <= cv_ratio <= 1.5:
            # Close to historical seasonality
            score = 1.0 - abs(cv_ratio - 1.0)
        elif 0.2 <= cv_ratio <= 2.0:
            # Somewhat different
            score = 0.5
        else:
            # Very different seasonality
            score = 0.2
        
        return max(0.0, min(1.0, score))
    
    def _calculate_stability_score(self, forecast_values: np.ndarray) -> float:
        """
        Evaluate forecast stability - penalize erratic jumps.
        
        Returns score between 0 and 1 (higher is better).
        """
        if len(forecast_values) < 2:
            return 1.0
        
        # Calculate month-to-month changes
        changes = np.diff(forecast_values)
        
        # Calculate percentage changes (relative to current value)
        pct_changes = []
        for i in range(len(forecast_values) - 1):
            if forecast_values[i] > 0:
                pct_changes.append(abs(changes[i]) / forecast_values[i])
        
        if not pct_changes:
            return 1.0
        
        # Calculate volatility (standard deviation of percentage changes)
        volatility = np.std(pct_changes)
        
        # Score based on volatility
        # Low volatility (< 10%) = high score
        # High volatility (> 50%) = low score
        if volatility < 0.1:
            score = 1.0
        elif volatility < 0.3:
            score = 0.8
        elif volatility < 0.5:
            score = 0.5
        else:
            score = 0.2
        
        return score
    
    def _calculate_non_negativity_score(self, forecast_values: np.ndarray) -> float:
        """
        Check if all forecast values are non-negative.
        
        Returns 1.0 if all non-negative, 0.0 otherwise.
        """
        return 1.0 if np.all(forecast_values >= 0) else 0.0
    
    def select_best_model(
        self, 
        all_forecasts: Dict[str, np.ndarray],
        historical_values: np.ndarray
    ) -> Tuple[str, Dict[str, float]]:
        """
        Select the best model from all available forecasts.
        
        Args:
            all_forecasts: Dictionary mapping model names to forecast arrays
            historical_values: Array of historical actual values
            
        Returns:
            Tuple of (best_model_name, scores_dict)
        """
        if not all_forecasts:
            raise ValueError("No forecasts provided for selection")
        
        # Evaluate all models
        all_scores = {}
        for model_name, forecast_values in all_forecasts.items():
            if forecast_values is None or len(forecast_values) == 0:
                continue
            
            scores = self.evaluate_forecast_quality(
                forecast_values, historical_values, model_name
            )
            all_scores[model_name] = scores
        
        if not all_scores:
            raise ValueError("No valid forecasts to evaluate")
        
        # Find model with highest total score
        best_model = max(all_scores.items(), key=lambda x: x[1]['total'])
        
        return best_model[0], best_model[1]
    
    def create_ensemble_forecast(
        self,
        all_forecasts: Dict[str, np.ndarray],
        historical_values: np.ndarray,
        top_n: int = 3
    ) -> Tuple[np.ndarray, Dict[str, any]]:
        """
        Create weighted ensemble forecast from top N models.
        
        Args:
            all_forecasts: Dictionary mapping model names to forecast arrays
            historical_values: Array of historical actual values
            top_n: Number of top models to include in ensemble
            
        Returns:
            Tuple of (ensemble_forecast_array, metadata_dict)
        """
        if not all_forecasts:
            raise ValueError("No forecasts provided for ensemble")
        
        # Evaluate all models
        all_scores = {}
        for model_name, forecast_values in all_forecasts.items():
            if forecast_values is None or len(forecast_values) == 0:
                continue
            
            scores = self.evaluate_forecast_quality(
                forecast_values, historical_values, model_name
            )
            all_scores[model_name] = scores
        
        if not all_scores:
            raise ValueError("No valid forecasts to evaluate")
        
        # Sort models by total score (descending)
        sorted_models = sorted(
            all_scores.items(), 
            key=lambda x: x[1]['total'], 
            reverse=True
        )
        
        # Select top N models
        top_models = sorted_models[:min(top_n, len(sorted_models))]
        
        # Calculate weights proportional to scores
        total_score = sum(score_dict['total'] for _, score_dict in top_models)
        
        if total_score == 0:
            # If all scores are zero, use equal weights
            weights = [1.0 / len(top_models)] * len(top_models)
        else:
            weights = [score_dict['total'] / total_score for _, score_dict in top_models]
        
        # Create ensemble forecast as weighted average
        forecast_length = len(all_forecasts[top_models[0][0]])
        ensemble_forecast = np.zeros(forecast_length)
        
        for (model_name, _), weight in zip(top_models, weights):
            ensemble_forecast += weight * all_forecasts[model_name]
        
        # Create metadata
        metadata = {
            'models_used': [model_name for model_name, _ in top_models],
            'weights': weights,
            'scores': {model_name: score_dict['total'] for model_name, score_dict in top_models},
            'ensemble_method': 'weighted_average'
        }
        
        return ensemble_forecast, metadata
    
    def evaluate_and_select(
        self,
        all_forecasts: Dict[str, np.ndarray],
        historical_values: np.ndarray,
        mode: str = "ensemble"
    ) -> Tuple[np.ndarray, Dict[str, any]]:
        """
        Main entry point: evaluate models and return selected/ensemble forecast.
        
        Args:
            all_forecasts: Dictionary mapping model names to forecast arrays
            historical_values: Array of historical actual values
            mode: "best" for single best model, "ensemble" for weighted ensemble
            
        Returns:
            Tuple of (selected_forecast_array, metadata_dict)
        """
        if mode == "best":
            best_model, scores = self.select_best_model(all_forecasts, historical_values)
            return all_forecasts[best_model], {
                'selected_model': best_model,
                'selection_method': 'best_model',
                'scores': scores
            }
        elif mode == "ensemble":
            return self.create_ensemble_forecast(all_forecasts, historical_values, top_n=3)
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'best' or 'ensemble'")
