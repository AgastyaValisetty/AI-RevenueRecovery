import type {
  SimulationState,
  ParallelExperimentResult,
  SmartCase,
  PaymentIntent,
  LedgerEntry,
  Person,
  PersonRecoverySummary,
  Merchant,
  MerchantRevenueSummary,
  FailureSummary,
  FailureMethodBreakdown,
  RailHealth,
  RailMetrics,
  ServiceHealth,
  Experiment,
  ExperimentReport,
  PaginatedResponse,
  SimulationRunRequest,
  RunMetrics,
  RecoveryAction,
} from './types';

const API_BASE = '/api';

class ApiError extends Error {
  constructor(message: string, public status: number, public body?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

async function apiRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(
      `API request failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }

  const text = await response.text();
  if (!text || text === 'null' || text === 'undefined') return null as T;
  return JSON.parse(text) as T;
}

async function apiPost<T>(path: string, data?: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: 'POST',
    body: data ? JSON.stringify(data) : undefined,
  });
}

async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: 'GET' });
}

// ─── Simulation ────────────────────────────────────────

export const simulationApi = {
  getState(): Promise<SimulationState> {
    return apiGet<SimulationState>('/simulation/status');
  },

  start(params?: SimulationRunRequest): Promise<{ message: string; run_id: string }> {
    return apiPost('/simulation/run', params);
  },

  stop(): Promise<{ message: string }> {
    return apiPost('/simulation/stop');
  },

  runParallelExperiment(
    params?: { people_count?: number; hours?: number; seed?: number },
  ): Promise<ParallelExperimentResult> {
    return apiPost('/simulation/parallel', params);
  },

  getParallelResults(): Promise<ParallelExperimentResult[]> {
    return apiGet<ParallelExperimentResult[]>('/simulation/parallel-results');
  },

  clear(): Promise<{ message: string }> {
    return apiPost('/simulation/clear');
  },
};

// ─── Recovery Actions ──────────────────────────────────

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

export interface RecoveryActionsResponse {
  actions: RecoveryAction[];
  count: number;
  recovery_enabled: boolean;
}

export const recoveryApi = {
  getActions(params?: {
    run_id?: string;
    intent_id?: string;
    action_type?: string;
    status?: string;
    limit?: number;
    offset?: number;
    engine_type?: string;
  }): Promise<RecoveryActionsResponse> {
    const search = new URLSearchParams();
    if (params?.run_id) search.set('run_id', params.run_id);
    if (params?.intent_id) search.set('intent_id', params.intent_id);
    if (params?.action_type) search.set('action_type', params.action_type);
    if (params?.status) search.set('status', params.status);
    if (params?.engine_type) search.set('engine_type', params.engine_type);
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());

    const qs = search.toString();
    return apiGet<RecoveryActionsResponse>(`/recovery/actions${qs ? `?${qs}` : ''}`);
  },

  getMetrics(params?: {
    run_id?: string;
    engine_type?: string;
  }): Promise<RecoveryMetrics> {
    const search = new URLSearchParams();
    if (params?.run_id) search.set('run_id', params.run_id);
    if (params?.engine_type) search.set('engine_type', params.engine_type);
    const qs = search.toString();
    return apiGet<RecoveryMetrics>(`/recovery/metrics${qs ? `?${qs}` : ''}`);
  },
};

// ─── Smart Cases ───────────────────────────────────────

export const smartAgentApi = {
  getCases(params?: {
    status?: string;
    limit?: number;
    offset?: number;
    sort?: string;
  }): Promise<PaginatedResponse<SmartCase>> {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());
    if (params?.sort) search.set('sort', params.sort);

    const qs = search.toString();
    return apiGet<PaginatedResponse<SmartCase>>(`/smart-agent/cases${qs ? `?${qs}` : ''}`);
  },

  getCase(caseId: string): Promise<SmartCase> {
    return apiGet<SmartCase>(`/smart-agent/case/${caseId}`);
  },

  getRecoveryMetrics(): Promise<{
    total_cases: number;
    recovered_cases: number;
    recovery_rate: number;
    total_value: string;
    recovered_value: string;
    avg_recovery_time: number | null;
  }> {
    return apiGet<{
    total_cases: number;
    recovered_cases: number;
    recovery_rate: number;
    total_value: string;
    recovered_value: string;
    avg_recovery_time: number | null;
  }>(`/smart-agent/metrics`);
  },

  getPolicyChecks(caseId: string): Promise<{
    policy_checks: Array<{ name: string; passed: boolean; detail: string }>;
    decision: string;
    reason: string;
    confidence: number;
  }> {
    return apiGet<{
    policy_checks: Array<{ name: string; passed: boolean; detail: string }>;
    decision: string;
    reason: string;
    confidence: number;
  }>(`/smart-agent/case/${caseId}/policy-checks`);
  },

  runCounterfactual(caseId: string): Promise<{
    original_outcome: string;
    counterfactual_outcome: string;
    counterfactual_recovery: number;
    action_sequence: Array<{
      action_type: string;
      scheduled_for: string;
      outcome: string;
      reason: string;
    }>;
    explanation: string;
  }> {
    return apiPost<{
    original_outcome: string;
    counterfactual_outcome: string;
    counterfactual_recovery: number;
    action_sequence: Array<{
      action_type: string;
      scheduled_for: string;
      outcome: string;
      reason: string;
    }>;
    explanation: string;
  }>(`/smart-agent/case/${caseId}/counterfactual`);
  },
};

// ─── Payments ──────────────────────────────────────────

export const paymentApi = {
  getIntents(params?: {
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<PaginatedResponse<PaymentIntent>> {
    const search = new URLSearchParams();
    if (params?.status) search.set('status', params.status);
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());

    const qs = search.toString();
    return apiGet<PaginatedResponse<PaymentIntent>>(
      `/payments/intents${qs ? `?${qs}` : ''}`,
    );
  },

  getIntent(id: string): Promise<PaymentIntent> {
    return apiGet<PaymentIntent>(`/payments/intents/${id}`);
  },
};

// ─── Ledger ─�──────────────────────────────────────────

export const ledgerApi = {
  getEntries(params?: {
    account?: string;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  }): Promise<PaginatedResponse<LedgerEntry>> {
    const search = new URLSearchParams();
    if (params?.account) search.set('account', params.account);
    if (params?.from) search.set('from', params.from);
    if (params?.to) search.set('to', params.to);
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());

    const qs = search.toString();
    return apiGet<PaginatedResponse<LedgerEntry>>(
      `/ledger/entries${qs ? `?${qs}` : ''}`,
    );
  },

  getAccounts(): Promise<Array<{ name: string; type: string; balance: number }>> {
    return apiGet<Array<{ name: string; type: string; balance: number }>>(`/ledger/accounts`);
  },

  getBalances(): Promise<Record<string, number>> {
    return apiGet<Record<string, number>>(`/ledger/balances`);
  },
};

// ─── People ─�──────────────────────────────────────────

export const peopleApi = {
  getPeople(params?: {
    limit?: number;
    offset?: number;
    search?: string;
  }): Promise<PaginatedResponse<Person>> {
    const search = new URLSearchParams();
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());
    if (params?.search) search.set('search', params.search);

    const qs = search.toString();
    return apiGet<PaginatedResponse<Person>>(`/people${qs ? `?${qs}` : ''}`);
  },

  getPerson(id: string): Promise<Person> {
    return apiGet<Person>(`/people/${id}`);
  },

  getPersonRecoverySummary(id: string): Promise<PersonRecoverySummary> {
    return apiGet<PersonRecoverySummary>(`/people/${id}/recovery-summary`);
  },
};

// ─── Merchants ─�───────────────────────────────────────

export const merchantApi = {
  getMerchants(params?: {
    limit?: number;
    offset?: number;
  }): Promise<PaginatedResponse<Merchant>> {
    const search = new URLSearchParams();
    if (params?.limit) search.set('limit', params.limit.toString());
    if (params?.offset) search.set('offset', params.offset.toString());

    const qs = search.toString();
    return apiGet<PaginatedResponse<Merchant>>(`/merchants${qs ? `?${qs}` : ''}`);
  },

  getMerchant(id: string): Promise<Merchant> {
    return apiGet<Merchant>(`/merchants/${id}`);
  },

  getRevenueSummary(id: string): Promise<MerchantRevenueSummary> {
    return apiGet<MerchantRevenueSummary>(`/merchants/${id}/revenue`);
  },
};

// ─── Failures ─�────────────────────────────────────────

export const failureApi = {
  getFailureStats(): Promise<{
    total_failures: number;
    total_amount: number;
    recovery_rate: number;
    avg_retries: number;
    by_code: FailureSummary[];
    by_method: FailureMethodBreakdown[];
  }> {
    return apiGet<{
    total_failures: number;
    total_amount: number;
    recovery_rate: number;
    avg_retries: number;
    by_code: FailureSummary[];
    by_method: FailureMethodBreakdown[];
  }>('/failures/stats');
  },
};

// ─── Rail Health ──────────────────────────────────────

export const railHealthApi = {
  getRailHealth(): Promise<RailHealth[]> {
    return apiGet<RailHealth[]>('/rail-health/all');
  },

  getRailMetrics(railName: string): Promise<RailMetrics[]> {
    return apiGet<RailMetrics[]>(`/rail-health/${railName}/metrics`);
  },
};

// ─── Experiments ──────────────────────────────────────

export const experimentApi = {
  getExperiments(): Promise<Experiment[]> {
    return apiGet<Experiment[]>('/experiments');
  },

  getExperiment(id: number): Promise<Experiment> {
    return apiGet<Experiment>(`/experiments/${id}`);
  },

  getExperimentReport(id: number): Promise<ExperimentReport> {
    return apiGet<ExperimentReport>(`/experiments/${id}/report`);
  },
};

// ─── Health ─�──────────────────────────────────────────

export const healthApi = {
  check(): Promise<ServiceHealth> {
    return apiGet<ServiceHealth>('/health');
  },
};

export { ApiError };
export type {
  SimulationState,
  ParallelExperimentResult,
  SmartCase,
  PaymentIntent,
  LedgerEntry,
  Person,
  PersonRecoverySummary,
  Merchant,
  MerchantRevenueSummary,
  FailureSummary,
  FailureMethodBreakdown,
  RailHealth,
  RailMetrics,
  ServiceHealth,
  Experiment,
  ExperimentReport,
  PaginatedResponse,
  SimulationRunRequest,
  RunMetrics,
  RecoveryAction,
  RecoveryMetrics,
  RecoveryActionsResponse,
};
