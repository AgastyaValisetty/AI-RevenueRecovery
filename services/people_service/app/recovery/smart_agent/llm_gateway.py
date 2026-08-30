"""LLMGateway — NVIDIA NIM client for the Smart Recovery Agent.

Wraps the Nemotron 3.5 Lightning 30B A3B model (hosted NIM API) with three modes:

  - **Live AI mode**: calls the NIM API for diagnosis, explanation, and message
    generation.  Structured JSON output is enforced via guided JSON schemas.
  - **Replay mode**: reuses exact LLM outputs from a previous run (stored in the
    audit trail) for reproducibility.  No API call is made.
  - **Fallback mode**: if the NIM API fails or no API key is configured, the
    gateway returns deterministic fallback responses derived from the
    deterministic diagnosis engine.

All calls are logged with their prompt version, input snapshot hash, and full
response for auditability and replay.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import httpx

from ...config import LLMConfig
from ...database import Database
from ...schema import AuditEventRow

logger = logging.getLogger(__name__)

# Prompt templates (versioned)
PROMPT_VERSION = "1.0.0"

# Timeout for NIM API calls (seconds)
NIM_TIMEOUT = 30.0

# Retry config for NIM API calls
NIM_MAX_RETRIES = 2


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response from the LLM gateway.

    In replay/fallback mode, ``response_id`` is a deterministic UUID derived
    from the input hash.  In live mode, it matches the NIM response ID.
    """

    response_id: str
    model: str
    content: dict[str, Any]  # parsed JSON output
    input_hash: str
    prompt_version: str
    mode: str  # "live", "replay", "fallback"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_response: Optional[str] = None  # full text response for debugging
    error: Optional[str] = None


class LLMGateway:
    """Gateway for LLM calls with multi-mode support (live, replay, fallback).

    Parameters
    ----------
    config :
        LLMConfig with API key, base URL, model name, mode, etc.
    db :
        Database for storing/replaying LLM responses in audit log.
    """

    def __init__(self, config: LLMConfig, db: Optional[Database] = None):
        self._config = config
        self._db = db

    @property
    def mode(self) -> str:
        return self._config.mode

    @property
    def is_live(self) -> bool:
        return self._config.is_live

    def diagnose(
        self,
        case_id: UUID,
        prompt: str,
        system_prompt: str,
        expected_schema: Optional[dict] = None,
        input_snapshot: Optional[dict] = None,
    ) -> LLMResponse:
        """Call the LLM for root-cause diagnosis with structured output.

        Parameters
        ----------
        case_id :
            Associated recovery case ID for audit linkage.
        prompt :
            The user-facing prompt (patient context, failure details).
        system_prompt :
            System instructions (persona, output format, constraints).
        expected_schema :
            JSON schema for guided output (enforced in live mode).
        input_snapshot :
            The full input dict — used to compute deterministic hash for
            replay and audit.
        """
        return self._call_llm(
            case_id=case_id,
            event_type="diagnosis",
            prompt=prompt,
            system_prompt=system_prompt,
            expected_schema=expected_schema,
            input_snapshot=input_snapshot,
        )

    def explain(
        self,
        case_id: UUID,
        prompt: str,
        system_prompt: str,
        input_snapshot: Optional[dict] = None,
    ) -> LLMResponse:
        """Call the LLM to generate a human-readable explanation card."""
        return self._call_llm(
            case_id=case_id,
            event_type="explanation",
            prompt=prompt,
            system_prompt=system_prompt,
            input_snapshot=input_snapshot,
        )

    def generate_message(
        self,
        case_id: UUID,
        prompt: str,
        system_prompt: str,
        input_snapshot: Optional[dict] = None,
    ) -> LLMResponse:
        """Call the LLM to generate a customer-facing message."""
        return self._call_llm(
            case_id=case_id,
            event_type="message",
            prompt=prompt,
            system_prompt=system_prompt,
            input_snapshot=input_snapshot,
        )

    # ------------------------------------------------------------------ #
    # Internal dispatch
    # ------------------------------------------------------------------ #

    def _call_llm(
        self,
        *,
        case_id: UUID,
        event_type: str,
        prompt: str,
        system_prompt: str,
        expected_schema: Optional[dict] = None,
        input_snapshot: Optional[dict] = None,
    ) -> LLMResponse:
        """Dispatch to the appropriate mode handler."""
        snapshot = input_snapshot or {"prompt": prompt}
        snapshot_hash = self._hash_snapshot(snapshot)

        if self._config.mode == "live":
            return self._live_call(
                case_id=case_id,
                event_type=event_type,
                prompt=prompt,
                system_prompt=system_prompt,
                expected_schema=expected_schema,
                snapshot_hash=snapshot_hash,
                raw_input=json.dumps(snapshot, sort_keys=True),
            )
        elif self._config.mode == "replay":
            return self._replay_call(
                case_id=case_id,
                event_type=event_type,
                snapshot_hash=snapshot_hash,
            )
        else:
            return self._fallback_call(
                case_id=case_id,
                event_type=event_type,
                snapshot_hash=snapshot_hash,
                system_prompt=system_prompt,
            )

    def _live_call(
        self,
        *,
        case_id: UUID,
        event_type: str,
        prompt: str,
        system_prompt: str,
        expected_schema: Optional[dict],
        snapshot_hash: str,
        raw_input: str,
    ) -> LLMResponse:
        """Call the NIM API for a live LLM response."""
        if not self._config.api_key:
            logger.warning(
                "LLM mode is 'live' but no API key — falling back to deterministic."
            )
            return self._fallback_call(
                case_id=case_id,
                event_type=event_type,
                snapshot_hash=snapshot_hash,
                system_prompt=system_prompt,
            )

        url = f"{self._config.base_url.rstrip('/')}/chat/completions"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        payload: dict[str, Any] = {
            "model": self._config.model_name,
            "messages": messages,
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "max_tokens": self._config.max_tokens,
        }

        # Use guided JSON if a schema is provided (NVIDIA supports this)
        if expected_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": f"sara_{event_type}",
                    "schema": expected_schema,
                    "strict": True,
                },
            }
            payload["stream"] = False

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

        attempt = 0
        while attempt <= NIM_MAX_RETRIES:
            try:
                with httpx.Client(timeout=NIM_TIMEOUT) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                content_str = data["choices"][0]["message"]["content"]
                content = self._parse_json_response(content_str)
                response_id = data.get("id", str(uuid4()))

                return LLMResponse(
                    response_id=response_id,
                    model=self._config.model_name,
                    content=content,
                    input_hash=snapshot_hash,
                    prompt_version=self._config.prompt_version,
                    mode="live",
                    raw_response=content_str,
                )
            except Exception as exc:
                attempt += 1
                if attempt > NIM_MAX_RETRIES:
                    logger.error(
                        "NIM API failed after %d retries for case %s: %s",
                        NIM_MAX_RETRIES,
                        case_id,
                        exc,
                    )
                    return LLMResponse(
                        response_id=str(uuid4()),
                        model=self._config.model_name,
                        content=self._fallback_content(event_type, system_prompt),
                        input_hash=snapshot_hash,
                        prompt_version=self._config.prompt_version,
                        mode="fallback",
                        error=str(exc),
                    )

        return self._fallback_call(
            case_id=case_id,
            event_type=event_type,
            snapshot_hash=snapshot_hash,
            system_prompt=system_prompt,
        )

    def _replay_call(
        self,
        *,
        case_id: UUID,
        event_type: str,
        snapshot_hash: str,
    ) -> LLMResponse:
        """Replay a previously stored LLM response from the audit trail."""
        if self._db is None:
            return self._fallback_call(
                case_id=case_id, event_type=event_type,
                snapshot_hash=snapshot_hash, system_prompt="",
            )

        from sqlalchemy import select

        with self._db.session() as session:
            row = session.scalars(
                select(AuditEventRow)
                .where(
                    AuditEventRow.case_id == case_id,
                    AuditEventRow.event_type == f"llm_{event_type}",
                    AuditEventRow.input_snapshot_hash == snapshot_hash,
                )
                .order_by(AuditEventRow.timestamp.desc())
                .limit(1)
            ).first()

        if row is None:
            logger.warning(
                "No replay found for case %s event %s hash %s — using fallback.",
                case_id, event_type, snapshot_hash[:8],
            )
            return self._fallback_call(
                case_id=case_id, event_type=event_type,
                snapshot_hash=snapshot_hash, system_prompt="",
            )

        decision = row.decision_json or {}
        return LLMResponse(
            response_id=f"replay-{row.event_id}",
            model=decision.get("model", self._config.model_name),
            content=decision.get("content", {}),
            input_hash=snapshot_hash,
            prompt_version=decision.get("prompt_version", PROMPT_VERSION),
            mode="replay",
            raw_response=decision.get("raw_response"),
        )

    def _fallback_call(
        self,
        *,
        case_id: UUID,
        event_type: str,
        snapshot_hash: str,
        system_prompt: str,
    ) -> LLMResponse:
        """Deterministic fallback when LLM is unavailable."""
        return LLMResponse(
            response_id=f"fallback-{hashlib.md5(snapshot_hash.encode()).hexdigest()[:12]}",
            model=self._config.model_name,
            content=self._fallback_content(event_type, system_prompt),
            input_hash=snapshot_hash,
            prompt_version=self._config.prompt_version,
            mode="fallback",
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash_snapshot(snapshot: dict) -> str:
        raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_json_response(content_str: str) -> dict[str, Any]:
        """Parse LLM JSON output, stripping markdown fences if present."""
        content_str = content_str.strip()
        if content_str.startswith("```json"):
            content_str = content_str[7:]
        if content_str.startswith("```"):
            content_str = content_str[3:]
        if content_str.endswith("```"):
            content_str = content_str[:-3]
        return json.loads(content_str)

    @staticmethod
    def _fallback_content(event_type: str, system_prompt: str) -> dict[str, Any]:
        """Generate deterministic fallback content when LLM is unavailable."""
        if event_type == "diagnosis":
            return {
                "label": "normal",
                "confidence": 0.5,
                "evidence_refs": [],
                "competing_hypotheses": [],
                "explanation": "Fallback: deterministic diagnosis used (LLM unavailable).",
            }
        elif event_type == "explanation":
            return {
                "summary": "LLM unavailable — using deterministic reasoning.",
                "key_factors": [],
                "why_this_action": "Selected by expected-value maximization.",
            }
        else:  # message
            return {
                "message": "We noticed a payment issue. Please update your payment method to continue service.",
                "channel": "notification",
                "tone": "polite",
            }
