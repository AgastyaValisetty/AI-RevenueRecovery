// API client for People Service and simulation ecosystem

export async function fetchSimulationStatus() {
  const res = await fetch('/api/simulation/status');
  if (!res.ok) {
    throw new Error(`Failed to fetch simulation status: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function runSimulation(peopleCount = 100, days = 1, seed = null) {
  const res = await fetch('/api/simulation/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      people_count: Number(peopleCount),
      days: Number(days),
      seed: seed ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run simulation: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchPeople() {
  const res = await fetch('/api/people');
  if (!res.ok) {
    throw new Error(`Failed to fetch people: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchPersonDetail(personId) {
  const res = await fetch(`/api/people/${personId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch person details: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMerchants() {
  const res = await fetch('/api/merchants');
  if (!res.ok) {
    throw new Error(`Failed to fetch merchants: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchLedgerEntries(limit = 500) {
  try {
    const res = await fetch(`/api/ledger?limit=${limit}`);
    if (res.ok) {
      const data = await res.json();
      return data.entries || [];
    }
  } catch (err) {
    console.warn('Ledger fetch error:', err);
  }
  return null;
}

export async function fetchSubscriptions(limit = 500) {
  try {
    const res = await fetch(`/api/subscriptions?limit=${limit}`);
    if (res.ok) {
      const data = await res.json();
      return data.subscriptions || [];
    }
  } catch (err) {
    console.warn('Subscriptions fetch error:', err);
  }
  return null;
}

export async function fetchFailures() {
  const res = await fetch('/api/payments/failures');
  if (!res.ok) {
    throw new Error(`Failed to fetch failures: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecoveryActions(limit = 500, outcome, action_type, engine_type) {
  const params = new URLSearchParams();
  if (limit) params.set('limit', limit);
  if (outcome) params.set('outcome', outcome);
  if (action_type) params.set('action_type', action_type);
  if (engine_type) params.set('engine_type', engine_type);
  const res = await fetch(`/api/recovery/actions?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch recovery actions: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecoveryHistory(intentId) {
  const res = await fetch(`/api/recovery/actions/intent/${intentId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch recovery history: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecoveryMetrics(runId = null, engine_type = null) {
  const params = new URLSearchParams();
  if (runId) params.set('run_id', runId);
  if (engine_type) params.set('engine_type', engine_type);
  const url = `/api/recovery/metrics${params.toString() ? `?${params.toString()}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch recovery metrics: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchRecoveryRuns(limit = 50) {
  const res = await fetch(`/api/recovery/runs?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch recovery runs: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Smart Recovery Agent (SARA) API endpoints
// ---------------------------------------------------------------------------

export async function fetchSmartCases(limit = 100) {
  const res = await fetch(`/api/recovery/smart/cases?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch smart cases: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSmartCase(caseId) {
  const res = await fetch(`/api/recovery/smart/cases/${caseId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch smart case: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function runSmartRecovery(intentIds = null, seed = null) {
  const res = await fetch('/api/recovery/smart/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ intent_ids: intentIds, seed }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run smart recovery: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function simulateCounterfactuals(caseId, scenarios = null) {
  const res = await fetch(`/api/recovery/smart/cases/${caseId}/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenarios }),
  });
  if (!res.ok) {
    throw new Error(`Failed to simulate counterfactuals: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function approveSmartAction(caseId) {
  const res = await fetch(`/api/recovery/smart/cases/${caseId}/approve`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Failed to approve action: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function runExperimentComparison(peopleCount = 200, hours = 72, seed = 42) {
  const res = await fetch('/api/recovery/experiments/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      people_count: peopleCount,
      days: 0,
      hours: hours,
      seed: seed,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run experiment: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAuditTrail(caseId) {
  const res = await fetch(`/api/recovery/audit/${caseId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch audit trail: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Parallel Experiment API endpoints — baseline + Smart Agent run simultaneously
// on separate PostgreSQL schemas with identical seed data.
// ---------------------------------------------------------------------------

export async function runParallelExperiment(peopleCount = 200, hours = 72, seed = 42) {
  const res = await fetch('/api/recovery/experiments/parallel/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      people_count: peopleCount,
      days: 0,
      hours: hours,
      seed: seed,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to run parallel experiment: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchParallelExperimentCases(experimentId, engine = 'smart', limit = 100, status = null) {
  const params = new URLSearchParams();
  params.set('engine', engine);
  if (limit) params.set('limit', limit);
  if (status) params.set('status', status);
  const res = await fetch(`/api/recovery/experiments/parallel/${experimentId}/cases?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch parallel experiment cases: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchParallelExperimentMetrics(experimentId, engine = 'smart') {
  const res = await fetch(`/api/recovery/experiments/parallel/${experimentId}/metrics?engine=${engine}`);
  if (!res.ok) throw new Error(`Failed to fetch ${engine} experiment metrics: ${res.status}`);
  return res.json();
}

export async function fetchParallelExperimentRetries(experimentId, engine = 'smart', limit = 5000, status = null) {
  const params = new URLSearchParams({ engine, limit: String(limit) });
  if (status) params.set('status', status);
  const res = await fetch(`/api/recovery/experiments/parallel/${experimentId}/retries?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch ${engine} experiment retries: ${res.status}`);
  return res.json();
}

export async function fetchParallelExperimentCaseDetail(experimentId, caseId, engine = 'smart') {
  const res = await fetch(`/api/recovery/experiments/parallel/${experimentId}/cases/${caseId}?engine=${engine}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch parallel experiment case detail: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function listParallelExperiments(limit = 20) {
  const res = await fetch(`/api/recovery/experiments/parallel/list?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`Failed to list parallel experiments: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function fetchParallelExperimentAudit(experimentId, engine = 'smart', limit = 200) {
  const res = await fetch(`/api/recovery/experiments/parallel/${experimentId}/audit?engine=${engine}&limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to fetch ${engine} audit trail: ${res.status}`);
  return res.json();
}


export async function fetchRailHealth(method = null) {
  const url = method
    ? `/api/recovery/insights/rail-health?method=${method}`
    : '/api/recovery/insights/rail-health';
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch rail health: ${res.status} ${res.statusText}`);
  }
  return res.json();
}
