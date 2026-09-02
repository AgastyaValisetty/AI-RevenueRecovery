/**
 * Type definitions for all backend API responses.
 * These mirror the Pydantic schemas in services/people_service/app/api.py
 * exactly. The backend is read-only — types here describe its contracts.
 */

// ────────────────────────────────────────────────
// Simulation / Orchestration
// ────────────────────────────────────────────────

export type SimulationStatus = 'IDLE' | 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface SimulationState {
  status: SimulationStatus;
  current_phase: string;
  people_count: number;
  hours_elapsed: number;
  total_hours: number;
  events: SimulationEvent[];
  latest_experiment: ParallelExperimentResult | null;
}

export interface SimulationEvent {
  timestamp: string;
  phase: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
}

export interface ParallelExperimentResult {
  experiment_id: string;
  public_run_id: string;
  baseline: RunMetrics;
  smart: RunMetrics;
  incremental_recovered_value: string;
  incremental_recovery_rate: number;
  wasted_retry_reduction: number;
  time_to_recovery_improvement: number | null;
  stop_precision_improvement: number;
  total_cost_savings: string;
  notes: string;
  seed: number;
  people_count: number;
  hours: number;
  schemas_preserved: string[];
}

export interface RunMetrics {
  run_id: string;
  engine_type: 'BASELINE' | 'AI_AGENT';
  total_cases: number;
  recovered_cases: number;
  total_recovered_value: string;
  total_retries: number;
  wasted_retries: number;
  total_outreach: number;
  mean_time_to_recovery_hours: number | null;
  stop_count: number;
  correct_stops: number;
  duplicate_risk_incidents: number;
  total_cost: string;
  incentive_cost: string;
  net_recovered_value: string;
  timestamp: string;
}

// ─�─── Recovery Actions ────────────────────────────

export type RecoveryActionType =
  | 'RETRY'
  | 'SEND_PAYMENT_LINK'
  | 'SEND_NOTIFICATION'
  | 'STOP';

export type RecoveryOutcome = 'SUCCESS' | 'FAILED' | 'PENDING' | 'UNKNOWN';

export type RecoveryStatus = 'PENDING' | 'EXECUTED' | 'SKIPPED';

export interface RecoveryAction {
  action_id: string;
  run_id: string;
  intent_id: string;
  payment_intent_id: string | null;
  case_id: string | null;
  action_type: RecoveryActionType;
  scheduled_for: string | null;
  executed_at: string | null;
  outcome: RecoveryOutcome | null;
  amount: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  reason: string | null;
  created_at: string;
  metadata_json: Record<string, unknown> | null;
  retry_number: number | null;
  payment_method: string | null;
  customer_declined: boolean;
  cost: string | null;
  expected_recovery: string | null;
  retry_attempt_id: string | null;
  schedule_reason: string | null;
}

export interface RecoveryMetrics {
  total_recovery_actions: number;
  retry_actions: number;
  stop_actions: number;
  link_actions: number;
  notification_actions: number;
  successful_recoveries: number;
  failed_recoveries: number;
  stopped_recoveries: number;
  unknown_recoveries: number;
  total_recovered_gmv: string;
  total_recovery_cost: string;
  expected_recovery_gmv: string;
  total_retries_attempted: number;
  retries_successful: number;
  retries_failed: number;
  average_retries_per_intent: number;
  average_hours_to_recovery: number | null;
  min_hours_to_recovery: number | null;
  max_hours_to_recovery: number | null;
  by_failure_code: Record<string, number>;
  by_payment_method: Record<string, number>;
  by_merchant: Record<string, number>;
  by_day: Record<string, number>;
  recovery_rate: number;
  retry_success_rate: number;
  recovery_enabled: boolean;
}

// Smart Cases

export type CaseStatus = 'QUEUED' | 'IN_PROGRESS' | 'RECOVERED' | 'STOPPED' | 'EXPIRED';
export interface SmartCase {
  case_id: string;
  intent_id: string;
  action_type: RecoveryActionType;
  status: CaseStatus;
  failure_code: string | null;
  failure_reason: string | null;
  amount: string;
  payment_method: string;
  retry_number: number;
  scheduled_for: string | null;
  executed_at: string | null;
  expected_recovery: number;
  reason: string | null;
  decision: PolicyDecision;
  diagnosis: Diagnosis | null;
  prior_actions: PriorAction[];
  audit_trail: AuditEntry[];
}

export interface PolicyDecision {
  policy_checks: PolicyCheck[];
  decision: string;
  reason: string;
  confidence: number;
}

export interface PolicyCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface Diagnosis {
  root_cause: string;
  confidence: number;
  explanation: string;
  hypotheses: Hypothesis[];
}

export interface Hypothesis {
  hypothesis: string;
  likelihood: number;
  evidence: string;
}

export interface PriorAction {
  action_type: string;
  timestamp: string;
  outcome: string;
  amount: string | null;
}

export interface AuditEntry {
  timestamp: string;
  actor: string;
  action: string;
  detail: string;
}

// ────────────────────────────────────────────────
// Payments & Ledger
// ────────────────────────────────────────────────

export type PaymentStatus =
  | 'succeeded'
  | 'failed'
  | 'requires_payment_method'
  | 'requires_action'
  | 'processing'
  | 'canceled';

export interface PaymentIntent {
  id: string;
  amount: number;
  currency: string;
  status: PaymentStatus;
  created_at: string;
  description: string | null;
  payment_method: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  customer_id: string | null;
  metadata: Record<string, unknown> | null;
}

export interface LedgerEntry {
  entry_id: string;
  timestamp: string;
  account: string;
  account_type: string;
  debit: number;
  credit: number;
  balance: number;
  description: string;
  reference_id: string | null;
  entry_type: string;
}

// ────────────────────────────────────────────────
// People
// ────────────────────────────────────────────────

export type EmploymentStatus = 'employed' | 'self_employed' | 'retired' | 'unemployed';
export type RiskTier = 'low' | 'medium' | 'high';

export interface Person {
  person_id: string;
  settlement_account_id: string;
  name: string;
  email: string;
  phone: string | null;
  employment_status: EmploymentStatus;
  risk_tier: RiskTier;
  created_at: string;
  tags: string[];
}

export interface PersonRecoverySummary {
  person_id: string;
  total_failed: number;
  total_recovered: number;
  total_value_failed: number;
  total_value_recovered: number;
  recovery_rate: number;
  avg_recovery_time_hours: number | null;
}

// ────────────────────────────────────────────────
// Merchants
// ────────────────────────────────────────────────

export interface Merchant {
  merchant_id: string;
  name: string;
  category: string;
  status: 'active' | 'suspended' | 'closed';
  total_volume: number;
  total_failed: number;
  failed_rate: number;
  total_recovered: number;
  created_at: string;
}

export interface MerchantRevenueSummary {
  merchant_id: string;
  name: string;
  category: string;
  gross_volume: number;
  failed_volume: number;
  recovered_value: number;
  recovery_rate: number;
  chargeback_rate: number;
  total_customers: number;
}

// ────────────────────────────────────────────────
// Failures
// ────────────────────────────────────────────────

export interface FailureSummary {
  failure_code: string;
  failure_reason: string;
  count: number;
  total_amount: number;
  recovery_rate: number;
  avg_retries_per_case: number;
}

export interface FailureMethodBreakdown {
  method: string;
  attempted: number;
  succeeded: number;
  failed: number;
  success_rate: number;
}

// ─�───────────────────────────────────────────────
// Rail Health
// ────────────────────────────────────────────────

export interface RailHealth {
  rail_name: string;
  rail_type: 'card_network' | 'bank' | 'wallet';
  status: 'operational' | 'degraded' | 'outage';
  uptime_24h: number;
  success_rate: number;
  failure_count_24h: number;
  latency_ms: number;
}

export interface RailMetrics {
  timestamp: string;
  uptime: number;
  success_rate: number;
  latency_ms: number;
  request_count: number;
}

// ────────────────────────────────────────────────
// Health
// ────────────────────────────────────────────────

export interface ServiceHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: Record<string, { status: string; latency_ms: number | null }>;
}

// ────────────────────────────────────────────────
// Experiments
// ────────────────────────────────────────────────

export interface Experiment {
  experiment_id: number;
  public_run_id: string;
  seed: number;
  people_count: number;
  hours: number;
  status: 'completed' | 'running' | 'failed';
  baseline_run_id: string;
  smart_run_id: string;
  created_at: string;
  completed_at: string | null;
  notes: string | null;
}

export interface ExperimentReport {
  experiment_id: number;
  report_text: string;
  created_at: string;
  metrics: ParallelExperimentResult;
}

// ────────────────────────────────────────────────
// Paginated responses
// ────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
  has_next: boolean;
  has_prev: boolean;
}

// ────────────────────────────────────────────────
// Simulation Run Request
// ────────────────────────────────────────────────

export interface SimulationRunRequest {
  people_count?: number;
  hours?: number;
  seed?: number;
}

export interface ApiResponse<T> {
  data: T;
}
