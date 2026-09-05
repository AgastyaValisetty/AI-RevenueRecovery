"""Train + score an XGBoost model on sara_recovery_actions.csv and write
predicted_probability_of_recovery + enpv back into the same data.

Usage (from repo root):
    python XG_DATA/train_xgb_model.py
    #   --input  XG_DATA/sara_recovery_actions.csv
    #   --output XG_DATA/sara_recovery_scored.csv
    #   --model-out XG_DATA/xgb_model.json

What this script does:
1. Loads sara_recovery_actions.csv.
2. Derives the binary target from the `outcome` column
       (1 if outcome == 'SUCCESS', else 0).
3. Engineers a numeric feature matrix from the columns we trust as
   predictors (amount, retry_number, action_type, payment_method,
   failure_code, customer_declined).
4. Splits 80/20 stratified, trains XGBClassifier, evaluates AUC +
   logloss + Brier.
5. Scores the entire CSV and writes the predictions back as two new
   columns:
     - predicted_probability_of_recovery
     - enpv  (via enpv.compute_enpv)
6. Saves the trained model as xgb_model.json.
7. Prints metrics + top-10 feature importances.

Companion files:
  - XG_DATA/train.py     : minimal trainer that writes model/meta.json
                            for the live UI inference path (infer.py).
  - XG_DATA/infer.py     : loads model + meta + serves predict().
  - XG_DATA/enpv.py      : ENPV formula used both here and in SARA.
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

INPUT_DEFAULT = Path(__file__).resolve().parent / "sara_recovery_actions.csv"
OUTPUT_DEFAULT = Path(__file__).resolve().parent / "sara_recovery_scored.csv"
MODEL_DEFAULT = Path(__file__).resolve().parent / "xgb_model.json"

# Categorical predictors kept compact for the UI's infer.py consumer.
# (Matches the feature_columns list in model/meta.json so the produced
# model file is interchangeable with the trainer in train.py.)
ACTION_TYPES = ("RETRY", "SEND_PAYMENT_LINK", "SEND_NOTIFICATION", "STOP")
PAYMENT_METHODS = ("UPI", "CARD", "NETBANKING")
FAILURE_CODES = (
    "INSUFFICIENT_FUNDS",
    "NETWORK_ERROR",
    "INVALID_DETAILS",
    "BANK_DECLINE",
    "AUTHENTICATION",
)

PRED_OUTPUT_COL = "predicted_probability_of_recovery"
ENPV_OUTPUT_COL = "enpv"


# --------------------------------------------------------------------------- #
# IO + feature engineering
# --------------------------------------------------------------------------- #

def load_dataset(csv_path: Path) -> pd.DataFrame:
    """Read the recovery-actions CSV; error out clearly if missing."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Training CSV not found at {csv_path}. "
            "Generate it with XG_DATA/extract_sara_recovery.py first."
        )
    df = pd.read_csv(csv_path)
    print(f"[xgdata] Loaded {len(df)} rows, {len(df.columns)} columns from {csv_path}")
    if "outcome" not in df.columns:
        raise ValueError(
            "Training CSV is missing `outcome` — "
            "is this really a SARA recovery-actions export?"
        )
    return df


def _str_lower(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col].fillna("").astype(str).str.lower()


def _one_hot(series: pd.Series, choices: tuple[str, ...]) -> pd.DataFrame:
    """Return a DataFrame with one column per choice (0/1 ints)."""
    s = series.astype(str)
    return pd.DataFrame(
        {f"{series.name}_{c}": (s == c).astype(int) for c in choices},
        index=series.index,
    )


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer the feature matrix used for training + scoring.

    Output columns (stable order):
      amount, retry_number, customer_declined,
      is_retry, is_payment_link, is_notification, is_stop,
      is_upi, is_card, is_netbanking,
      fc_INSUFFICIENT_FUNDS, fc_NETWORK_ERROR, fc_INVALID_DETAILS,
      fc_BANK_DECLINE, fc_AUTHENTICATION, fc_OTHER.
    """
    out = pd.DataFrame(index=df.index)

    out["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    out["retry_number"] = pd.to_numeric(df["retry_number"], errors="coerce").fillna(0)

    out["customer_declined"] = (
        _str_lower(df, "customer_declined").eq("true").astype(int)
    )

    action = _str_lower(df, "action_type")
    out = pd.concat([out, _one_hot(action.rename("is"), ACTION_TYPES)], axis=1)

    method = _str_lower(df, "payment_method")
    out = pd.concat([out, _one_hot(method.rename("is"), PAYMENT_METHODS)], axis=1)

    fc = _str_lower(df, "failure_code")
    fc_oh = _one_hot(fc.rename("fc"), FAILURE_CODES)
    fc_oh["fc_OTHER"] = (
        ~fc.isin(FAILURE_CODES) & (fc != "")
    ).astype(int)
    out = pd.concat([out, fc_oh], axis=1)

    # Stable column order
    cols = [
        "amount", "retry_number", "customer_declined",
        *[f"is_{a}" for a in ACTION_TYPES],
        *[f"is_{m}" for m in PAYMENT_METHODS],
        *[f"fc_{c}" for c in FAILURE_CODES],
        "fc_OTHER",
    ]
    return out[cols].astype(float)


# --------------------------------------------------------------------------- #
# Training + scoring
# --------------------------------------------------------------------------- #

def derive_target(df: pd.DataFrame) -> pd.Series:
    """Binary target: 1 if outcome == 'SUCCESS', else 0.

    Rows with outcome in {PENDING, STOPPED, missing} are kept as 0
    (negative examples) — only true settlement outcomes count as
    positive.
    """
    return (_str_lower(df, "outcome") == "success").astype(int)


def stratified_split(
    X: pd.DataFrame, y: pd.Series, *, eval_frac: float = 0.2, seed: int = 42
):
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
    max_depth: int = 4,
    learning_rate: float = 0.05,
    seed: int = 42,
):
    import xgboost as xgb

    model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="binary:logistic",
        eval_metric="auc",
        tree_method="hist",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_eval, y_eval)], verbose=False)
    return model


def compute_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    y_pred_clipped = np.clip(y_pred, 1e-6, 1 - 1e-6)
    metrics: dict[str, float] = {
        "count": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "mean_predicted_probability": float(y_pred.mean()),
    }
    if y_true.nunique() < 2:
        metrics["auc"] = float("nan")
    else:
        metrics["auc"] = float(roc_auc_score(y_true, y_pred))
    metrics["log_loss"] = float(log_loss(y_true, y_pred_clipped))
    metrics["brier_score"] = float(brier_score_loss(y_true, y_pred_clipped))
    return metrics


def top_feature_importance(model, feature_cols: list[str], *, top_n: int = 10):
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
    """Add predicted_probability_of_recovery + enpv columns to df."""
    y_hat = np.clip(model.predict_proba(X_all)[:, 1], 0.0, 1.0)
    df = df.copy()
    df[PRED_OUTPUT_COL] = y_hat
    df[ENPV_OUTPUT_COL] = [
        float(compute_enpv(p, a))
        for p, a in zip(y_hat, pd.to_numeric(df["amount"], errors="coerce").fillna(0.0))
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
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    df = load_dataset(args.input)
    if df.empty:
        print("[xgdata] ERROR: training CSV is empty.")
        return 1

    y = derive_target(df)
    if y.nunique() < 2:
        print(
            "[xgdata] ERROR: outcome column has only a single value "
            "(only SUCCESS or only FAILED). No recoverable signal — "
            "train on a longer / larger simulation."
        )
        return 1

    X = build_features(df)
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

    train_metrics = compute_metrics(y_train, model.predict_proba(X_train)[:, 1])
    eval_metrics = compute_metrics(y_eval, model.predict_proba(X_eval)[:, 1])
    print("[xgdata] Train metrics:", json.dumps(train_metrics, indent=2))
    print("[xgdata] Eval  metrics:", json.dumps(eval_metrics, indent=2))

    print("[xgdata] Top-10 feature importances (gain):")
    for name, imp in top_feature_importance(model, list(X.columns), top_n=10):
        print(f"   {name:38s}  {imp:.4f}")

    df_scored = score_and_enpv(df, model, X)
    df_scored.to_csv(args.output, index=False)
    print(
        f"[xgdata] Wrote {args.output} — {len(df_scored)} rows, "
        f"{len(df_scored.columns)} cols (added {PRED_OUTPUT_COL}, {ENPV_OUTPUT_COL})."
    )

    model.save_model(str(args.model_out))
    print(f"[xgdata] Saved XGBoost model to {args.model_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())