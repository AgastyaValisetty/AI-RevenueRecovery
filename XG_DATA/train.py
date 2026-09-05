"""
train.py — XGBoost model for predicting P(recovery) on a recovery action.

Trains a single XGBClassifier on sara_recovery_actions.csv. ENPV at inference
time is derived as `P(recovery) * amount - RETRY_COST`, matching how SARA
itself computes expected net value.

Reads:   XG_DATA/sara_recovery_actions.csv  (FAILED + SUCCESS rows; PENDING dropped)
Writes:  XG_DATA/model/model.json   — the booster
         XG_DATA/model/meta.json    — feature list, threshold, training stats

Run:  python XG_DATA/train.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

HERE = Path(__file__).parent
DATA_PATH = HERE / "sara_recovery_actions.csv"
MODEL_DIR = HERE / "model"
MODEL_PATH = MODEL_DIR / "model.json"
META_PATH = MODEL_DIR / "meta.json"

# Fixed retry cost in INR — matches SARA's policy.py RETRY_COST (₹2.50).
RETRY_COST = 2.50

# Features we feed the model. All derivable from a single recovery_action row.
# Categoricals become one-hot via get_dummies; we don't depend on SARA's
# runtime CaseFeatures here so the model stays deployable from any endpoint.
FEATURE_COLUMNS = [
    "amount",
    "retry_number",
    "customer_declined",
    "is_retry",
    "is_payment_link",
    "is_notification",
    "is_stop",
    "is_upi",
    "is_card",
    "is_netbanking",
    "fc_INSUFFICIENT_FUNDS",
    "fc_NETWORK_ERROR",
    "fc_INVALID_DETAILS",
    "fc_BANK_DECLINE",
    "fc_AUTHENTICATION",
    "fc_OTHER",
]

TARGET = "recovered"  # 1 if outcome == 'SUCCESS', else 0


def _engineer(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix. Returns a DataFrame with FEATURE_COLUMNS."""
    out = pd.DataFrame(index=df.index)

    out["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    out["retry_number"] = pd.to_numeric(df["retry_number"], errors="coerce").fillna(0)

    # customer_declined is a string boolean like "False"/"True".
    out["customer_declined"] = (
        df["customer_declined"].astype(str).str.lower().eq("true").astype(int)
    )

    action = df["action_type"].fillna("").astype(str)
    out["is_retry"] = (action == "RETRY").astype(int)
    out["is_payment_link"] = (action == "SEND_PAYMENT_LINK").astype(int)
    out["is_notification"] = (action == "SEND_NOTIFICATION").astype(int)
    out["is_stop"] = (action == "STOP").astype(int)

    method = df["payment_method"].fillna("").astype(str)
    out["is_upi"] = (method == "UPI").astype(int)
    out["is_card"] = (method == "CARD").astype(int)
    out["is_netbanking"] = (method == "NETBANKING").astype(int)

    fc = df["failure_code"].fillna("").astype(str)
    out["fc_INSUFFICIENT_FUNDS"] = (fc == "INSUFFICIENT_FUNDS").astype(int)
    out["fc_NETWORK_ERROR"] = (fc == "NETWORK_ERROR").astype(int)
    out["fc_INVALID_DETAILS"] = (fc == "INVALID_DETAILS").astype(int)
    out["fc_BANK_DECLINE"] = (fc == "BANK_DECLINE").astype(int)
    out["fc_AUTHENTICATION"] = (fc == "AUTHENTICATION").astype(int)
    out["fc_OTHER"] = (
        ~fc.isin(["INSUFFICIENT_FUNDS", "NETWORK_ERROR", "INVALID_DETAILS",
                  "BANK_DECLINE", "AUTHENTICATION"])
        & (fc != "")
    ).astype(int)

    return out


def main() -> int:
    if not DATA_PATH.exists():
        raise SystemExit(f"missing data file: {DATA_PATH}")

    print(f"loading {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    print(f"loaded {len(df)} rows total")
    print("outcome counts:")
    print(df["outcome"].value_counts(dropna=False).to_string())

    # Drop PENDING (no decision yet) and missing outcome.
    df = df[df["outcome"].isin(["SUCCESS", "FAILED"])].copy()
    df[TARGET] = (df["outcome"] == "SUCCESS").astype(int)
    print(f"after dropping PENDING/missing: {len(df)} rows, "
          f"positive rate {df[TARGET].mean():.3%}")

    X = _engineer(df)[FEATURE_COLUMNS]
    y = df[TARGET].values

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"train: {len(X_train)}, val: {len(X_val)}")

    # Class imbalance is mild (~12% positives); scale_pos_weight is left at 1.0
    # to keep probabilities well-calibrated for the UI's pct() rendering.
    model = xgb.XGBClassifier(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="binary:logistic",
        eval_metric="auc",
        n_jobs=-1,
        random_state=42,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    val_p = model.predict_proba(X_val)[:, 1]
    auc = roc_auc_score(y_val, val_p)
    print(f"val AUC: {auc:.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "retry_cost_inr": RETRY_COST,
        "val_auc": float(auc),
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "positive_rate": float(y.mean()),
        "model_type": "XGBClassifier",
        "xgboost_version": xgb.__version__,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"saved model to {MODEL_PATH}")
    print(f"saved meta  to {META_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())