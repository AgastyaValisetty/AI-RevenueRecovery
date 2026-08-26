"""Recovery subsystem — baseline payment recovery infrastructure.

Provides the shared components (context, decision engine, scheduler, executor,
metrics) so that a future Smart AI Recovery Agent can later swap in ONLY its
decision engine while reusing every other piece.

Baseline strategy: retry failed payments every 12 simulation hours, up to
3 retries.  On explicit customer decline, STOP immediately.
"""

from .domain import (
    RecoveryActionType,
    RecoveryDecision,
    RecoveryOutcome,
    RecoveryAction,
    RecoveryDecisionEngine,
    RecoveryEngineType,
)
from .decision_engine import BaselineRecoveryEngine
from .context import RecoveryContext, AttemptInfo, PersonInfo, MerchantInfo, SubscriptionInfo, BalanceInfo, PriorRecovery
from .context_builder import RecoveryContextBuilder
from .scheduler import RecoveryScheduler
from .executor import RecoveryActionExecutor
from .metrics import RecoveryMetrics, RecoveryMetricsCollector
from .run import RecoveryRunMetadata, RecoveryRunTracker
from .customer_response import CustomerResponse, CustomerResponseSimulator
from .repository import RecoveryActionRepository

__all__ = [
    "RecoveryActionType",
    "RecoveryDecision",
    "RecoveryOutcome",
    "RecoveryAction",
    "RecoveryDecisionEngine",
    "RecoveryEngineType",
    "BaselineRecoveryEngine",
    "RecoveryContext",
    "AttemptInfo",
    "PersonInfo",
    "MerchantInfo",
    "SubscriptionInfo",
    "BalanceInfo",
    "PriorRecovery",
    "RecoveryContextBuilder",
    "RecoveryScheduler",
    "RecoveryActionExecutor",
    "RecoveryMetrics",
    "RecoveryMetricsCollector",
    "RecoveryRunMetadata",
    "RecoveryRunTracker",
    "CustomerResponse",
    "CustomerResponseSimulator",
    "RecoveryActionRepository",
]
