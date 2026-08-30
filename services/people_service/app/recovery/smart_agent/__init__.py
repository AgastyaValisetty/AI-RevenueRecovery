"""Smart Recovery Agent (SARA) — AI-powered revenue recovery.

Hybrid architecture: deterministic code enforces all financial decisions,
policy gates, stopping rules, and idempotency.  The LLM (NVIDIA Nemotron via
NIM) is used only for diagnosis, explanation, and selecting from a controlled
action menu.

The SmartRecoveryEngine implements the existing RecoveryDecisionEngine protocol
and plugs into the orchestrator as a drop-in replacement for BaselineRecoveryEngine.
"""

from .feature_store import FeatureStore, CaseFeatures
from .diagnosis import RootCauseDiagnoser, Diagnosis
from .action_value import ActionValueCalculator, CandidateAction, ExpectedValue
from .rail_health import RailHealthMonitor, RailHealth
from .memory import RecoveryMemoryRepository, CustomerRecoveryMemory
from .promise_tracker import PromiseTracker, PromiseToPay
from .policy import PolicyValidator, PolicyResult, STOP_RULES
from .planner import ActionPlanner, PlannedAction
from .llm_gateway import LLMGateway
from .explainer import Explainer
from .audit import AuditEvent, AuditEventWriter
from .counterfactual import CounterfactualSimulator
from .scenarios import ScenarioLibrary
from .evaluation import ExperimentEvaluator, LiftReport, RunMetrics
from .agent import SmartRecoveryEngine
from .experiment_runner import ExperimentRunner, ExperimentConfig
from .parallel_runner import ParallelExperimentRunner, ParallelRunResult, ParallelExperimentConfig

__all__ = [
    # Feature extraction
    "FeatureStore",
    "CaseFeatures",
    # Diagnosis
    "RootCauseDiagnoser",
    "Diagnosis",
    # Action value
    "ActionValueCalculator",
    "CandidateAction",
    "ExpectedValue",
    # Rail health
    "RailHealthMonitor",
    "RailHealth",
    # Memory
    "RecoveryMemoryRepository",
    "CustomerRecoveryMemory",
    # Promise tracking
    "PromiseTracker",
    "PromiseToPay",
    # Policy
    "PolicyValidator",
    "PolicyResult",
    "STOP_RULES",
    # Planner
    "ActionPlanner",
    "PlannedAction",
    # LLM
    "LLMGateway",
    # Explainer
    "Explainer",
    # Audit
    "AuditEvent",
    "AuditEventWriter",
    # Counterfactual
    "CounterfactualSimulator",
    # Scenarios
    "ScenarioLibrary",
    # Evaluation
    "ExperimentEvaluator",
    "LiftReport",
    "RunMetrics",
    # Experiment runner
    "ExperimentRunner",
    "ExperimentConfig",
    # Parallel experiment runner
    "ParallelExperimentRunner",
    "ParallelRunResult",
    "ParallelExperimentConfig",
    # Main engine
    "SmartRecoveryEngine",
]
