import { useState, useEffect, useCallback, useRef } from 'react';
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
  RunMetrics,
  RecoveryAction,
  RecoveryMetrics,
} from '../lib/types';
import * as api from '../lib/api';

/** Generic async state wrapper — matches the existing dummy-frontend polling pattern. */
export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

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
  RunMetrics,
  RecoveryAction,
  RecoveryMetrics,
};

/**
 * Generic polling hook — mirrors the 3s polling pattern from dummy-frontend-2.
 */
function usePolling<T>(
  fetchFn: () => Promise<T>,
  intervalMs: number = 3000,
  immediate: boolean = true,
): AsyncState<T> & { refetch: () => void; isPolling: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const isMounted = useRef(true);
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  const fetch = useCallback(async () => {
    setIsPolling(true);
    setError(null);
    try {
      const result = await fetchFnRef.current();
      if (isMounted.current) {
        setData(result);
        setLoading(false);
      }
    } catch (err) {
      if (isMounted.current) {
        setError(err instanceof Error ? err.message : 'Failed to fetch');
        setLoading(false);
      }
    } finally {
      if (isMounted.current) setIsPolling(false);
    }
  }, []);

  useEffect(() => {
    isMounted.current = true;
    if (immediate) {
      fetch();
    }

    intervalRef.current = setInterval(fetch, intervalMs);

    return () => {
      isMounted.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetch, intervalMs, immediate]);

  return { data, loading, error, refetch: fetch, isPolling };
}

/**
 * Generic one-shot fetch hook.
 */
function useOneShot<T>(
  fetchFn: () => Promise<T>,
  immediate: boolean = true,
): AsyncState<T> & { refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<string | null>(null);
  const isMounted = useRef(true);
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFnRef.current();
      if (isMounted.current) {
        setData(result);
        setLoading(false);
      }
    } catch (err) {
      if (isMounted.current) {
        setError(err instanceof Error ? err.message : 'Failed to fetch');
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    isMounted.current = true;
    if (immediate) {
      void fetch();
    }
    return () => {
      isMounted.current = false;
    };
  }, [fetch, immediate]);

  return { data, loading, error, refetch: fetch };
}

// ── Specific hooks ──────────────────────────────────

export function useSimulation(pollInterval = 3000) {
  return usePolling(() => api.simulationApi.getState(), pollInterval);
}

export function useParallelResults() {
  return useOneShot(() => api.simulationApi.getParallelResults());
}

export function useSmartCases(params?: {
  status?: string;
  limit?: number;
  offset?: number;
  sort?: string;
}) {
  return useOneShot(() => api.smartAgentApi.getCases(params));
}

export function useCaseDetail(caseId: string) {
  return useOneShot(() => api.smartAgentApi.getCase(caseId), !!caseId);
}

export function useRecoveryMetrics(params?: { run_id?: string; engine_type?: string }) {
  const fetchFn = useCallback(() => api.recoveryApi.getMetrics(params), [params]);
  return useOneShot(fetchFn);
}

export function useRecoveryActions(params?: {
  action_type?: string;
  outcome?: string;
  limit?: number;
  run_id?: string;
  engine_type?: string;
}) {
  const fetchFn = useCallback(() => api.recoveryApi.getActions(params), [params]);
  return useOneShot(fetchFn);
}

export function useSaraAttempts(params?: { limit?: number }) {
  return useOneShot(() =>
    api.recoveryApi.getActions({
      action_type: 'RETRY',
      engine_type: 'AI_AGENT',
      limit: params?.limit ?? 5000,
    }),
  );
}

export function usePolicyChecks(caseId: string) {
  return useOneShot(() => api.smartAgentApi.getPolicyChecks(caseId), !!caseId);
}

export function useCounterfactual(caseId: string) {
  return useOneShot<unknown>(() => api.smartAgentApi.runCounterfactual(caseId), false);
}

export function usePaymentIntents(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const fetchFn = useCallback(() => api.paymentApi.getIntents(params), [params]);
  return useOneShot(fetchFn);
}

export function useLedgerEntries(params?: {
  account?: string;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}) {
  const fetchFn = useCallback(() => api.ledgerApi.getEntries(params), [params]);
  return useOneShot(fetchFn);
}

export function useLedgerAccounts() {
  return useOneShot(() => api.ledgerApi.getAccounts());
}

export function useLedgerBalances() {
  return useOneShot(() => api.ledgerApi.getBalances());
}

export function usePeople(params?: {
  limit?: number;
  offset?: number;
  search?: string;
}) {
  const fetchFn = useCallback(() => api.peopleApi.getPeople(params), [params]);
  return useOneShot(fetchFn);
}

export function usePerson(personId: string) {
  return useOneShot(() => api.peopleApi.getPerson(personId), !!personId);
}

export function usePersonRecoverySummary(personId: string) {
  return useOneShot(
    () => api.peopleApi.getPersonRecoverySummary(personId),
    !!personId,
  );
}

export function useMerchants(params?: { limit?: number; offset?: number }) {
  const fetchFn = useCallback(() => api.merchantApi.getMerchants(params), [params]);
  return useOneShot(fetchFn);
}

export function useMerchant(merchantId: string) {
  return useOneShot(() => api.merchantApi.getMerchant(merchantId), !!merchantId);
}

export function useMerchantRevenueSummary(merchantId: string) {
  return useOneShot(
    () => api.merchantApi.getRevenueSummary(merchantId),
    !!merchantId,
  );
}

export function useFailureStats() {
  return useOneShot(() => api.failureApi.getFailureStats());
}

export function useRailHealth() {
  return useOneShot(() => api.railHealthApi.getRailHealth());
}

export function useRailMetrics(railName: string) {
  return useOneShot(
    () => api.railHealthApi.getRailMetrics(railName),
    !!railName,
  );
}

export function useExperiments() {
  return useOneShot(() => api.experimentApi.getExperiments());
}

export function useExperiment(experimentId: number) {
  return useOneShot(
    () => api.experimentApi.getExperiment(experimentId),
    !!experimentId,
  );
}

export function useExperimentReport(experimentId: number) {
  return useOneShot(
    () => api.experimentApi.getExperimentReport(experimentId),
    !!experimentId,
  );
}

export function useHealth() {
  return usePolling(() => api.healthApi.check(), 10000, true);
}

export function useAuditLogs() {
  return usePolling(() => api.simulationApi.getState(), 5000);
}

// ── Mutation hooks ──────────────────────────────────

export function useSimulationRun() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (params?: { people_count?: number; hours?: number; seed?: number }) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.simulationApi.start(params);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start simulation');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { run, loading, error };
}

export function useParallelExperiment() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (params?: { people_count?: number; hours?: number; seed?: number }) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.simulationApi.runParallelExperiment(params);
      return result as ParallelExperimentResult;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run experiment');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { run, loading, error };
}

export function useCounterfactualRun() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (caseId: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.smartAgentApi.runCounterfactual(caseId);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run counterfactual');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { run, loading, error };
}
