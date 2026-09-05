"""
infer.py — load the XGBoost model trained by train.py and serve predictions.

Used by the people_service backend to enrich the SARA retries ledger with
predicted probability of recovery and expected net profit value (ENPV).

ENPV is computed at inference time as:
    ENPV = P(recovery) * amount - RETRY_COST
matching how SARA itself calculates expected net value (plans/sara.md §3 step 5).

Public API:
    from infer import predict
    out = predict({"amount": 234.82, "retry_number": 1, ...})
    out -> {"p_recovery": 0.83, "enpv": 192.35, "has_model": True}

If the model file isn't trained yet, predict() returns:
    {"p_recovery": None, "enpv": None, "has_model": False}
so the caller can render '—' rather than crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import xgboost as xgb

HERE = Path(__file__).parent
MODEL_DIR = HERE / "model"
MODEL_PATH = MODEL_DIR / "model.json"
META_PATH = MODEL_DIR / "meta.json"

_FEATURE_COLUMNS: list[str] = []
_RETRY_COST: float = 2.50
_BOOSTER: xgb.Booster | None = None
_LOADED = False
_LOAD_ERROR: str | None = None


def _ensure_loaded() -> bool:
    """Lazy-load the model on first call. Returns True if model is ready."""
    global _LOADED, _BOOSTER, _FEATURE_COLUMNS, _RETRY_COST, _LOAD_ERROR
    if _LOADED:
        return True
    if not MODEL_PATH.exists() or not META_PATH.exists():
        _LOAD_ERROR = f"model files missing at {MODEL_DIR} — run train.py first"
        return False
    try:
        meta = json.loads(META_PATH.read_text())
        _FEATURE_COLUMNS = list(meta["feature_columns"])
        _RETRY_COST = float(meta.get("retry_cost_inr", 2.50))
        _BOOSTER = xgb.Booster()
        _BOOSTER.load_model(str(MODEL_PATH))
        _LOADED = True
    except Exception as e:  # pragma: no cover — defensive
        _LOAD_ERROR = f"failed to load model: {e}"
        _BOOSTER = None
        return False
    return True


def is_ready() -> bool:
    return _ensure_loaded()


def load_error() -> str | None:
    _ensure_loaded()
    return _LOAD_ERROR


def _row_to_features(features: dict[str, Any]) -> pd.DataFrame:
    """Translate an API-shaped feature dict into the model's input frame.

    Mirrors the engineering in train.py. Unknown / missing keys default to 0.
    """
    amount = float(features.get("amount") or 0.0)
    retry_number = int(features.get("retry_number") or 0)
    customer_declined = 1 if str(features.get("customer_declined", "")).lower() == "true" else 0

    action = str(features.get("action_type") or "")
    method = str(features.get("payment_method") or "")
    fc = str(features.get("failure_code") or "")

    row = {
        "amount": amount,
        "retry_number": retry_number,
        "customer_declined": customer_declined,
        "is_retry": int(action == "RETRY"),
        "is_payment_link": int(action == "SEND_PAYMENT_LINK"),
        "is_notification": int(action == "SEND_NOTIFICATION"),
        "is_stop": int(action == "STOP"),
        "is_upi": int(method == "UPI"),
        "is_card": int(method == "CARD"),
        "is_netbanking": int(method == "NETBANKING"),
        "fc_INSUFFICIENT_FUNDS": int(fc == "INSUFFICIENT_FUNDS"),
        "fc_NETWORK_ERROR": int(fc == "NETWORK_ERROR"),
        "fc_INVALID_DETAILS": int(fc == "INVALID_DETAILS"),
        "fc_BANK_DECLINE": int(fc == "BANK_DECLINE"),
        "fc_AUTHENTICATION": int(fc == "AUTHENTICATION"),
        "fc_OTHER": int(fc not in (
            "INSUFFICIENT_FUNDS", "NETWORK_ERROR", "INVALID_DETAILS",
            "BANK_DECLINE", "AUTHENTICATION", "",
        )),
    }
    return pd.DataFrame([row], columns=_FEATURE_COLUMNS)


def predict(features: dict[str, Any]) -> dict[str, Any]:
    """Predict P(recovery) and ENPV for a single recovery action.

    Args:
        features: dict with at least amount, retry_number, action_type,
                  payment_method, failure_code, customer_declined.

    Returns:
        {"p_recovery": float|None, "enpv": float|None, "has_model": bool}
    """
    if not _ensure_loaded():
        return {"p_recovery": None, "enpv": None, "has_model": False}

    amount = float(features.get("amount") or 0.0)
    X = _row_to_features(features)
    # Booster.predict needs a DMatrix; raw output for binary:logistic is
    # already in [0, 1].  XGBClassifier.predict_proba (sklearn API) would
    # also work but adds an extra wrapper layer for no benefit at inference.
    dmatrix = xgb.DMatrix(X)
    raw = _BOOSTER.predict(dmatrix)
    p = float(raw[0]) if hasattr(raw, "__len__") else float(raw)
    if p < 0.0:
        p = 0.0
    elif p > 1.0:
        p = 1.0
    enpv = p * amount - _RETRY_COST
    return {"p_recovery": p, "enpv": enpv, "has_model": True}


def predict_batch(feature_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Vectorised batch prediction. Same return shape as predict().

    Empty input → empty list. If the model isn't loaded, every row gets
    {p_recovery: None, enpv: None, has_model: False} so the caller doesn't
    need to special-case the "model missing" path.
    """
    if not feature_list:
        return []
    if not _ensure_loaded():
        return [
            {"p_recovery": None, "enpv": None, "has_model": False}
            for _ in feature_list
        ]

    frames = [_row_to_features(f) for f in feature_list]
    X = pd.concat(frames, ignore_index=True)
    amounts = [float(f.get("amount") or 0.0) for f in feature_list]
    dmatrix = xgb.DMatrix(X)
    raw = _BOOSTER.predict(dmatrix)
    out: list[dict[str, Any]] = []
    for p, amt in zip(raw, amounts):
        p = float(p)
        if p < 0.0:
            p = 0.0
        elif p > 1.0:
            p = 1.0
        out.append({
            "p_recovery": p,
            "enpv": p * amt - _RETRY_COST,
            "has_model": True,
        })
    return out


if __name__ == "__main__":
    # Smoke check when invoked directly: requires the model to already exist.
    import sys
    if not is_ready():
        print(f"infer.py: model not ready ({load_error()})", file=sys.stderr)
        sys.exit(1)
    sample = {
        "amount": 234.82,
        "retry_number": 1,
        "action_type": "RETRY",
        "payment_method": "UPI",
        "failure_code": "INSUFFICIENT_FUNDS",
        "customer_declined": "False",
    }
    print(predict(sample))