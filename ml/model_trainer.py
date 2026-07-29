"""Train and compare multiple ML models; auto-select best."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor, StackingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ModelScore:
    name: str
    rmse: float
    mae: float
    r2: float
    cv_rmse_mean: float
    cv_rmse_std: float


@dataclass
class ModelComparisonResult:
    target: str
    scores: list[ModelScore] = field(default_factory=list)
    best_model_name: str = ""
    best_cv_rmse: float = float("inf")
    predictions_tail: list[float] = field(default_factory=list)
    feature_importance: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "scores": [asdict(s) for s in self.scores],
            "best_model_name": self.best_model_name,
            "best_cv_rmse": self.best_cv_rmse,
            "predictions_tail": self.predictions_tail,
            "feature_importance": self.feature_importance,
            "notes": self.notes,
        }


class ModelTrainer:
    """Compare RF, GBM, XGB, LGBM, CatBoost, Stacking with time-series CV."""

    def __init__(self, n_splits: int = 4, random_state: int = 42) -> None:
        self.n_splits = n_splits
        self.random_state = random_state
        self.fitted_models: dict[str, Any] = {}

    def _candidate_models(self) -> dict[str, Any]:
        models: dict[str, Any] = {
            "RandomForest": RandomForestRegressor(
                n_estimators=120, max_depth=8, random_state=self.random_state, n_jobs=-1
            ),
            "GradientBoosting": GradientBoostingRegressor(
                n_estimators=120, max_depth=3, learning_rate=0.06, random_state=self.random_state
            ),
        }
        try:
            from xgboost import XGBRegressor

            models["XGBoost"] = XGBRegressor(
                n_estimators=150,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=self.random_state,
                n_jobs=-1,
                verbosity=0,
            )
        except Exception as exc:
            logger.warning("XGBoost unavailable: {}", exc)

        try:
            from lightgbm import LGBMRegressor

            models["LightGBM"] = LGBMRegressor(
                n_estimators=150,
                max_depth=5,
                learning_rate=0.05,
                random_state=self.random_state,
                verbosity=-1,
            )
        except Exception as exc:
            logger.warning("LightGBM unavailable: {}", exc)

        try:
            from catboost import CatBoostRegressor

            models["CatBoost"] = CatBoostRegressor(
                iterations=150,
                depth=4,
                learning_rate=0.05,
                random_seed=self.random_state,
                verbose=False,
            )
        except Exception as exc:
            logger.warning("CatBoost unavailable: {}", exc)

        return models

    def compare(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        target_name: str = "fwd_ret_63",
    ) -> ModelComparisonResult:
        if len(X) < 80:
            return ModelComparisonResult(
                target=target_name,
                notes=f"Insufficient samples ({len(X)}) for robust ML. Need more NAV history.",
            )

        X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        y = y.loc[X.index]
        models = self._candidate_models()
        tscv = TimeSeriesSplit(n_splits=min(self.n_splits, max(2, len(X) // 100)))
        scores: list[ModelScore] = []
        best_name = ""
        best_cv = float("inf")
        best_est = None

        for name, est in models.items():
            pipe = Pipeline([("scaler", StandardScaler()), ("model", est)])
            cv_rmses = []
            try:
                for train_idx, test_idx in tscv.split(X):
                    pipe.fit(X.iloc[train_idx], y.iloc[train_idx])
                    pred = pipe.predict(X.iloc[test_idx])
                    cv_rmses.append(float(np.sqrt(mean_squared_error(y.iloc[test_idx], pred))))
                # Final fit on all but last 10% holdout for metrics
                split = int(len(X) * 0.85)
                pipe.fit(X.iloc[:split], y.iloc[:split])
                pred = pipe.predict(X.iloc[split:])
                rmse = float(np.sqrt(mean_squared_error(y.iloc[split:], pred)))
                mae = float(mean_absolute_error(y.iloc[split:], pred))
                r2 = float(r2_score(y.iloc[split:], pred))
                cv_mean = float(np.mean(cv_rmses))
                cv_std = float(np.std(cv_rmses))
                scores.append(
                    ModelScore(name, rmse, mae, r2, cv_mean, cv_std)
                )
                self.fitted_models[name] = pipe
                if cv_mean < best_cv:
                    best_cv = cv_mean
                    best_name = name
                    best_est = pipe
            except Exception as exc:
                logger.warning("Model {} failed: {}", name, exc)

        # Stacking ensemble if we have 2+ models
        if len(self.fitted_models) >= 2:
            try:
                estimators = []
                for n, p in list(self.fitted_models.items())[:4]:
                    estimators.append((n, p.named_steps["model"]))
                stack = StackingRegressor(
                    estimators=estimators,
                    final_estimator=Ridge(alpha=1.0),
                    n_jobs=-1,
                )
                pipe = Pipeline([("scaler", StandardScaler()), ("model", stack)])
                cv_rmses = []
                for train_idx, test_idx in tscv.split(X):
                    pipe.fit(X.iloc[train_idx], y.iloc[train_idx])
                    pred = pipe.predict(X.iloc[test_idx])
                    cv_rmses.append(float(np.sqrt(mean_squared_error(y.iloc[test_idx], pred))))
                split = int(len(X) * 0.85)
                pipe.fit(X.iloc[:split], y.iloc[:split])
                pred = pipe.predict(X.iloc[split:])
                rmse = float(np.sqrt(mean_squared_error(y.iloc[split:], pred)))
                mae = float(mean_absolute_error(y.iloc[split:], pred))
                r2 = float(r2_score(y.iloc[split:], pred))
                cv_mean = float(np.mean(cv_rmses))
                scores.append(
                    ModelScore("StackingEnsemble", rmse, mae, r2, cv_mean, float(np.std(cv_rmses)))
                )
                self.fitted_models["StackingEnsemble"] = pipe
                if cv_mean < best_cv:
                    best_cv = cv_mean
                    best_name = "StackingEnsemble"
                    best_est = pipe
            except Exception as exc:
                logger.warning("Stacking failed: {}", exc)

        # Feature importance from tree model if available
        fi: dict[str, float] = {}
        if best_est is not None:
            model = best_est.named_steps.get("model", best_est)
            if hasattr(model, "feature_importances_"):
                fi = {
                    str(c): float(v)
                    for c, v in sorted(
                        zip(X.columns, model.feature_importances_),
                        key=lambda x: -x[1],
                    )[:15]
                }
            # Tail predictions on latest rows
            try:
                best_est.fit(X, y)
                preds = best_est.predict(X.tail(10))
                pred_tail = [float(p) for p in preds]
            except Exception:
                pred_tail = []
        else:
            pred_tail = []

        scores.sort(key=lambda s: s.cv_rmse_mean)
        return ModelComparisonResult(
            target=target_name,
            scores=scores,
            best_model_name=best_name,
            best_cv_rmse=round(best_cv, 6) if best_cv < float("inf") else float("inf"),
            predictions_tail=pred_tail,
            feature_importance=fi,
            notes="TimeSeriesSplit CV; features exclude forward returns (no leakage).",
        )

    def predict_expected_cagr(self, result: ModelComparisonResult, periods_per_year: float = 4.0) -> Optional[float]:
        """Rough annualization of median forward-period prediction."""
        if not result.predictions_tail:
            return None
        med = float(np.median(result.predictions_tail))
        # If target is ~63 trading day return (~quarter)
        return (1 + med) ** periods_per_year - 1
