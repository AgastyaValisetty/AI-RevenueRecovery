"""Step 2 of the XG_DATA pipeline: train XGBoost on the recovery CSV and
write predicted_probability_of_recovery + enpv back into the same data.

Usage (from repo root):

    python XG_DATA/train_xgb_model.py
    #   --input  XG_DATA/sara_recovery_training.csv
    #   --output XG_DATA/sara_recovery_scored.csv
    #   --model-out XG_DATA/xgb_model.json

What this script does:

1. Loads sara_recovery_training.csv (output of build_training_table.py).
2. Drops non-feature columns (identifiers, string columns, the target).
3. Splits 80/20 stratified on ground_truth_recovered.
4. Trains an XGBoost regressor (reg:squarederror) with early stopping.
5. Scores the entire CSV and writes the predictions back as two new columns:
     - predicted_probability_of_recovery
     - enpv  (via enpv.compute_enpv)
6. Saves the trained model as xgb_model.json (portable XGBoost JSON).
7. Prints metrics + top-10 feature importances.

The CSV output is the deliverable the SARA retry ledger will eventually
display. Wiring it into the live UI is a separate task.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from enpv import compute_enpv

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

INPUT_DEFAULT = Path(__file__).resolve().parent / "sara_recovery_training.csv"
OUTPUT_DEFAULT = Path(__file__).resolve().parent / "sara_recovery_scored.csv"
MODEL_DEFAULT = Path(__file__).resolve().parent / "xgb_model.json"

# Columns that we DROP from the feature matrix before training. Anything not
# in this list is treated as a feature.
NON_FEATURE_COLUMNS: tuple[str, ...] = (
    # Identifiers — useless for prediction, just for traceability
    "attempt_id",
    "intent_id",
    "person_id",
    "merchant_id",
    "source_account_id",
    "destination_account_id",
    "correlation_id",
    "bank_id",
    "related_subscription_id",
    "bank_name",
    # Free-text / categorical string columns (kept in the CSV for review but
    # one-hot versions are the actual features)
    "failure_code",
    "failure_reason",
    # Raw timestamp — derived features are in the matrix
    "simulation_timestamp",
    "last_failure_ts",
    # Targets / labels / derived labels (not features)
    "ground_truth_recovered",
    "num_retries_taken",
    "time_to_recover_hours",
    "first_retry_outcome",
    # Per-row scalar fields that are also captured in one-hot variants
    # (kept in CSV for review; not used as numeric features).
    "amount",                 # captured via amount_bucket one-hot
    "payment_method",         # one-hot
    "bank_state",             # one-hot
    "failure_category",       # one-hot
    "merchant_type",          # one-hot
    "amount_bucket",          # one-hot
    "income_bracket",         # one-hot
    "age_group",              # one-hot
    "employment_type",        # one-hot
    "spending_profile_category",  # one-hot
    "subscription_billing_cycle",  # one-hot
    "day_of_week",            # one-hot
    "next_billing_date",      # captured via days_until_next_billing
    "payment_preferences_json",  # expanded into upi_pref/card_pref/netbanking_pref
)

# Columns the user explicitly asked to see in the SARA table (output cols)
PRED_OUTPUT_COL = "predicted_probability_of_recovery"
ENPV_OUTPUT_COL = "enpv"


# --------------------------------------------------------------------------- #
# Training + scoring
# --------------------------------------------------------------------------- #

def load_dataset(csv_path: Path) -> pd.DataFrame:
    """Read the training CSV and force numeric columns."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Training CSV not found at {csv_path}. "
            "Run XG_DATA/build_training_table.py first."
        )
    df = pd.read_csv(csv_path)
    print(f"[xgdata] Loaded {len(df)} rows, {len(df.columns)} columns from {csv_path}")
    if "ground_truth_recovered" not in df.columns:
        raise ValueError(
            "Training CSV is missing `ground_truth_recovered` — did the "
            "build script's SQL query succeed?"
        )
    return df


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Return (X, y, feature_column_names)."""
    y = df["ground_truth_recovered"].astype(int)
    feature_cols = [c for c in df.columns if c not in NON_FEATURE_COLUMNS]
    X = df[feature_cols].copy()
    # Force numeric (any object/str columns leak through here would explode XGBoost).
    for col in feature_cols:
        if X[col].dtype == object:
            X[col] = pd.to_numeric(X[col], errors="coerce")
    X = X.fillna(0.0).astype(float)
    return X, y, feature_cols


def stratified_split(
    X: pd.DataFrame, y: pd.Series, *, eval_frac: float = 0.2, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """80/20 stratified split (numpy-free, deterministic)."""
    from sklearn.model_selection import train_test_split

    return train_test_split(
        X, y, test_size=eval_frac, stratify=y, random_state=seed
    )


def train_xgb(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_eval: pd.DataFrame,
    y_eval: pd.Series,
    *,
    n_estimators: int = 400,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    early_stopping_rounds: int = 20,
    seed: int = 42,
):
    """Train an XGBoost regressor. Returns the fitted model."""
    import xgboost as xgb

    model = xgb.XGBRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        objective="reg:squarederror",
        eval_metric="logloss",
        tree_method="hist",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_eval, y_eval)],
        verbose=False,
    )
    # Apply early stopping manually if available in this xgboost version.
    if early_stopping_rounds and getattr(model, "best_iteration", None) is not None:
        print(
            f"[xgdata] XGBoost best_iteration={model.best_iteration} "
            f"(trained {n_estimators}, stopped early at {early_stopping_rounds})"
        )
    return model


def compute_metrics(
    y_true: pd.Series, y_pred: np.ndarray
) -> dict[str, float]:
    """AUC + log-loss + Brier score. Sklearn is the source of truth."""
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    y_pred_clipped = np.clip(y_pred, 1e-6, 1 - 1e-6)
    metrics: dict[str, float] = {}
    metrics["count"] = int(len(y_true))
    metrics["positive_rate"] = float(y_true.mean())
    metrics["mean_predicted_probability"] = float(y_pred.mean())
    if y_true.nunique() < 2:
        # Degenerate split (all 0s or all 1s); AUC undefined.
        metrics["auc"] = float("nan")
    else:
        metrics["auc"] = float(roc_auc_score(y_true, y_pred))
    metrics["log_loss"] = float(log_loss(y_true, y_pred_clipped))
    metrics["brier_score"] = float(brier_score_loss(y_true, y_pred_clipped))
    return metrics


def top_feature_importance(
    model, feature_cols: list[str], *, top_n: int = 10
) -> list[tuple[str, float]]:
    """Return top-N (feature, importance) pairs from the trained model."""
    importances = model.feature_importances_
    pairs = sorted(
        zip(feature_cols, importances.tolist()),
        key=lambda kv: kv[1],
        reverse=True,
    )
    return pairs[:top_n]


def score_and_enpv(
    df: pd.DataFrame, model, X_all: pd.DataFrame
) -> pd.DataFrame:
    """Add `predicted_probability_of_recovery` + `enpv` columns."""
    y_hat = np.clip(model.predict(X_all), 0.0, 1.0)
    df = df.copy()
    df[PRED_OUTPUT_COL] = y_hat
    df[ENPV_OUTPUT_COL] = [
        float(compute_enpv(p, a))
        for p, a in zip(y_hat, df["amount"].fillna(0.0))
    ]
    return df


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train XGBoost on the SARA recovery CSV and score it.",
    )
    parser.add_argument("--input", type=Path, default=INPUT_DEFAULT,
                        help=f"Input CSV (default {INPUT_DEFAULT}).")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT,
                        help=f"Output scored CSV (default {OUTPUT_DEFAULT}).")
    parser.add_argument("--model-out", type=Path, default=MODEL_DEFAULT,
                        help=f"XGBoost model file (default {MODEL_DEFAULT}).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    df = load_dataset(args.input)
    if df.empty:
        print("[xgdata] ERROR: training CSV is empty.")
        return 1
    if df["ground_truth_recovered"].nunique() < 2:
        print(
            "[xgdata] ERROR: ground_truth_recovered has a single value. "
            "The simulation produced no successful recoveries — train on a "
            "larger / longer simulation."
        )
        return 1

    X, y, feature_cols = split_features_target(df)
    print(f"[xgdata] Feature matrix: {X.shape[0]} rows × {X.shape[1]} cols")
    print(f"[xgdata] Positive rate: {y.mean():.3f} ({int(y.sum())}/{len(y)})")

    X_train, X_eval, y_train, y_eval = stratified_split(
        X, y, eval_frac=0.2, seed=args.seed
    )
    print(f"[xgdata] Train: {len(X_train)} | Eval: {len(X_eval)}")

    model = train_xgb(
        X_train, y_train, X_eval, y_eval,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        seed=args.seed,
    )

    train_metrics = compute_metrics(y_train, model.predict(X_train))
    eval_metrics = compute_metrics(y_eval, model.predict(X_eval))
    print("[xgdata] Train metrics:", json.dumps(train_metrics, indent=2))
    print("[xgdata] Eval  metrics:", json.dumps(eval_metrics, indent=2))

    print("[xgdata] Top-10 feature importances (gain):")
    for name, imp in top_feature_importance(model, feature_cols, top_n=10):
        print(f"   {name:38s}  {imp:.4f}")

    df_scored = score_and_enpv(df, model, X)
    df_scored.to_csv(args.output, index=False)
    print(
        f"[xgdata] Wrote {args.output} — {len(df_scored)} rows, "
        f"{len(df_scored.columns)} cols (added {PRED_OUTPUT_COL}, {ENPV_OUTPUT_COL})."
    )

    # Save the model. Try JSON first (portable across xgboost versions),
    # fall back to the binary JSON format that always works.
    try:
        model.save_model(str(args.model_out))
        print(f"[xgdata] Saved XGBoost model to {args.model_out}")
    except Exception as exc:
        # Fall back: xgboost's `save_model` writes JSON for json files,
        # binary for others. We use .json explicitly.
        import xgboost as xgb
        booster = model.get_booster()
        booster.save_model(str(args.model_out))
        print(f"[xgdata] Saved XGBoost model (fallback) to {args.model_out}: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())