import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  RefreshCw, Activity, BarChart3, Shield, Zap,
  ChevronLeft, ChevronRight, GitBranch, TrendingUp,
  CheckCircle2, Clock, XCircle, PauseCircle, AlertOctagon,
  FileText, Search, ExternalLink, History, Faders,
} from './ui/icons';
import {
  fetchSmartCases, fetchSmartCase, runSmartRecovery,
  simulateCounterfactuals, approveSmartAction,
  runExperimentComparison, fetchAuditTrail, fetchRailHealth,
  runParallelExperiment, fetchParallelExperimentCases,
  fetchParallelExperimentCaseDetail, listParallelExperiments,
} from '../api';
import './SmartAgentView.css';
import ScrollFade from './ui/ScrollFade';
import { money, pct } from '../utils/format';

const SUB_TABS = [
  { key: 'cases', label: 'Action Queue', icon: BarChart3 },
  { key: 'parallel', label: 'Parallel Experiment', icon: GitBranch },
  { key: 'experiment', label: 'Experiment Compare (Legacy)', icon: GitBranch },
  { key: 'rail-health', label: 'Rail Health', icon: Shield },
];

const ACTION_TYPE_LABELS = {
  RETRY: 'Retry',
  SEND_PAYMENT_LINK: 'Payment Link',
  SEND_NOTIFICATION: 'Notification',
  STOP: 'Stop',
};

const ACTION_TYPE_COLORS = {
  RETRY: 'tag-retry',
  SEND_PAYMENT_LINK: 'tag-link',
  SEND_NOTIFICATION: 'tag-notification',
  STOP: 'tag-stop',
};

const OUTCOME_LABELS = {
  PENDING: 'Pending',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  STOPPED: 'Stopped',
  UNKNOWN: 'Unknown',
};

const OUTCOME_COLORS = {
  PENDING: 'tag-pending',
  SUCCESS: 'tag-success',
  FAILED: 'tag-failed',
  STOPPED: 'tag-stopped',
  UNKNOWN: 'tag-unknown',
};

const formatTimestamp = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return '—'; }
};

// ---------- Sub-views ----------

function CasesQueue({ onCaseSelect, refreshTrigger }) {
  const [cases, setCases] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('all');

  const loadCases = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchSmartCases(200);
      setCases(data.cases ?? []);
      setCount(data.count ?? 0);
    } catch (e) {
      console.error('Failed to load smart cases:', e);
    } finally {
      setLoading(false);
    }
  }, [refreshTrigger]);

  useEffect(() => {
    loadCases();
  }, [loadCases]);

  const filtered = useMemo(() => {
    let f = cases;
    if (search.trim()) {
      const q = search.toLowerCase();
      f = f.filter((c) =>
        (c.intent_id && c.intent_id.toLowerCase().includes(q)) ||
        (c.action_type && c.action_type.toLowerCase().includes(q)) ||
        (c.failure_code && c.failure_code.toLowerCase().includes(q))
      );
    }
    if (priorityFilter !== 'all') {
      f = f.filter((c) => (c.priority || 'normal') === priorityFilter);
    }
    return f;
  }, [cases, search, priorityFilter]);

  const handleRunSmart = async () => {
    const ok = window.confirm('Run Smart Recovery Agent on all failed payment intents?');
    if (!ok) return;
    try {
      const data = await runSmartRecovery(null, null);
      alert(`Smart recovery run completed. ${data.count} decisions made.`);
      loadCases();
    } catch (e) {
      alert('Smart recovery failed: ' + e.message);
    }
  };

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="smart-cases-queue">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BarChart3 size={18} />
              <span className="panel-title">Ranked Action Queue</span>
              <span className="badge-count">{count} cases</span>
            </div>
            <div className="controls-bar">
              <button className="btn btn-primary btn-sm" onClick={handleRunSmart}>
                <Zap size={14} />
                <span>Run Smart Agent</span>
              </button>
              <button className="btn btn-secondary btn-sm" onClick={loadCases} disabled={loading}>
                <RefreshCw size={14} className={loading ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="panel-body">
            <div className="controls-bar" style={{ marginBottom: '12px' }}>
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search intent, failure code, action type..."
                  className="search-input"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                className="select-filter"
                value={priorityFilter}
                onChange={(e) => setPriorityFilter(e.target.value)}
              >
                <option value="all">All Priorities</option>
                <option value="high">High Priority Only</option>
                <option value="normal">Normal Priority Only</option>
              </select>
            </div>

            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Intent</th>
                    <th>Action</th>
                    <th>Priority</th>
                    <th>Failure</th>
                    <th>Expected Recovery</th>
                    <th>Scheduled</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan="7">
                        <div className="empty-state">
                          <Activity size={32} />
                          <p>{loading ? 'Loading cases...' : 'No pending recovery cases.'}</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    filtered.map((c) => (
                      <tr key={c.action_id} onClick={() => onCaseSelect(c.action_id)}>
                        <td className="mono-cell" title={c.intent_id}>{c.intent_id.slice(0, 12)}…</td>
                        <td>
                          <span className={`tag-badge ${ACTION_TYPE_COLORS[c.action_type] || 'tag-default'}`}>
                            {ACTION_TYPE_LABELS[c.action_type] || c.action_type}
                          </span>
                        </td>
                        <td>
                          <span className={`tag-badge ${c.priority === 'high' ? 'tag-failed' : 'tag-unknown'}`}>
                            {c.priority || 'normal'}
                          </span>
                        </td>
                        <td>
                          <span className="tag-badge tag-run">{c.failure_code || '—'}</span>
                        </td>
                        <td className="currency">{money(c.expected_recovery)}</td>
                        <td className="mono-cell timestamp-cell">{formatTimestamp(c.scheduled_for)}</td>
                        <td className="text-secondary">{c.reason || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </ScrollFade>
  );
}

function CaseDetail({ caseId, onBack, refreshTrigger }) {
  const [caseData, setCaseData] = useState(null);
  const [auditEvents, setAuditEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cfOutcomes, setCfOutcomes] = useState(null);
  const [cfLoading, setCfLoading] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [detail, audit] = await Promise.all([
        fetchSmartCase(caseId),
        fetchAuditTrail(caseId),
      ]);
      setCaseData(detail);
      setAuditEvents(audit.events ?? []);
    } catch (e) {
      console.error('Failed to load case:', e);
    } finally {
      setLoading(false);
    }
  }, [caseId, refreshTrigger]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSimulate = async () => {
    setCfLoading(true);
    setCfOutcomes(null);
    try {
      const data = await simulateCounterfactuals(caseId, null);
      setCfOutcomes(data);
    } catch (e) {
      console.error('Simulation failed:', e);
    } finally {
      setCfLoading(false);
    }
  };

  const handleApprove = async () => {
    const ok = window.confirm('Approve this recommended action?');
    if (!ok) return;
    try {
      const data = await approveSmartAction(caseId);
      alert(data.status === 'approved' ? 'Action approved.' : 'Approval: ' + (data.message || 'done'));
    } catch (e) {
      alert('Approval failed: ' + e.message);
    }
  };

  const diagnosis = caseData?.diagnosis;
  const decision = caseData?.decision;

  const renderDiag = (diag) => {
    if (!diag) return <span className="text-muted">—</span>;
    return (
      <div className="smart-diagnosis">
        {diag.root_cause && (
          <div className="diag-row">
            <span className="diag-label">Root Cause:</span>
            <span className="diag-value">{diag.root_cause}</span>
          </div>
        )}
        {diag.confidence !== undefined && (
          <div className="diag-row">
            <span className="diag-label">Confidence:</span>
            <span className="diag-value">{(diag.confidence * 100).toFixed(1)}%</span>
          </div>
        )}
        {diag.explanation && (
          <div className="diag-row">
            <span className="diag-label">Explanation:</span>
            <span className="diag-value">{diag.explanation}</span>
          </div>
        )}
        {diag.hypotheses && Array.isArray(diag.hypotheses) && (
          <div className="diag-row">
            <span className="diag-label">Hypotheses:</span>
            <div className="hypotheses-list">
              {diag.hypotheses.map((h, i) => (
                <div key={i} className="hypothesis-item">
                  <span className="hyp-label">{h.label || h.hypothesis || h.name}</span>
                  <span className="hyp-confidence">{h.confidence !== undefined ? `${(h.confidence * 100).toFixed(0)}%` : ''}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderPolicyChecks = (checks) => {
    if (!checks) return <span className="text-muted">—</span>;
    return (
      <table className="data-table policy-checks-table">
        <thead>
          <tr><th>Check</th><th>Passed</th><th>Detail</th></tr>
        </thead>
        <tbody>
          {checks.map((c, i) => (
            <tr key={i}>
              <td className="mono-cell">{c.name}</td>
              <td>
                <span className={`tag-badge ${c.passed ? 'tag-success' : 'tag-failed'}`}>
                  {c.passed ? 'PASS' : 'BLOCK'}
                </span>
              </td>
              <td className="text-secondary">{c.detail || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  return (
    <div className="smart-case-detail">
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <button className="btn btn-outline btn-sm" onClick={onBack}>
              <ChevronLeft size={14} /> Back
            </button>
            <FileText size={18} />
            <span className="panel-title">Case Detail</span>
          </div>
          <div className="controls-bar">
            <button className="btn btn-secondary btn-sm" onClick={handleSimulate} disabled={cfLoading}>
              <GitBranch size={14} />
              <span>{cfLoading ? 'Simulating...' : 'Simulate Counterfactuals'}</span>
            </button>
            {caseData?.action_type !== 'STOP' && (
              <button className="btn btn-secondary btn-sm" onClick={handleApprove}>
                <CheckCircle2 size={14} />
                <span>Approve Action</span>
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="panel-body">
            <p className="text-secondary">Loading case…</p>
          </div>
        ) : !caseData ? (
          <div className="panel-body">
            <p className="text-secondary">Case not found.</p>
          </div>
        ) : (
          <div className="panel-body">
            {/* Case overview */}
            <div className="smart-case-grid">
              <div className="smart-case-field">
                <span className="field-label">Intent ID</span>
                <span className="field-value mono-cell">{caseData.intent_id}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Action Type</span>
                <span className="field-value">
                  <span className={`tag-badge ${ACTION_TYPE_COLORS[caseData.action_type] || 'tag-default'}`}>
                    {ACTION_TYPE_LABELS[caseData.action_type] || caseData.action_type}
                  </span>
                </span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Failure Code</span>
                <span className="field-value">{caseData.failure_code || '—'}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Amount</span>
                <span className="field-value currency">{money(caseData.amount)}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Status</span>
                <span className="field-value">
                  <span className={`tag-badge ${OUTCOME_COLORS[caseData.status] || 'tag-unknown'}`}>
                    {OUTCOME_LABELS[caseData.status] || caseData.status}
                  </span>
                </span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Reason</span>
                <span className="field-value text-secondary">{caseData.reason || '—'}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Scheduled For</span>
                <span className="field-value mono-cell">{formatTimestamp(caseData.scheduled_for)}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Expected Recovery</span>
                <span className="field-value currency">{money(caseData.expected_recovery)}</span>
              </div>
              <div className="smart-case-field">
                <span className="field-label">Cost</span>
                <span className="field-value currency">{money(caseData.cost)}</span>
              </div>
              <div className="smart-case-field full-width">
                <span className="field-label">Reason</span>
                <span className="field-value text-secondary">{caseData.reason || '—'}</span>
              </div>
            </div>

            {/* Diagnosis */}
            <h3 className="smart-section-title">Root Cause Diagnosis</h3>
            <div className="smart-section-body">{renderDiag(diagnosis)}</div>

            {/* Policy Checks */}
            <h3 className="smart-section-title">Policy Checks</h3>
            <div className="smart-section-body">
              {decision?.policy_checks ? renderPolicyChecks(decision.policy_checks) : <span className="text-muted">—</span>}
            </div>

            {/* Counterfactual simulation results */}
            {cfOutcomes && (
              <>
                <h3 className="smart-section-title">Counterfactual Simulation</h3>
                <div className="smart-section-body">
                  <p className="text-muted" style={{ marginBottom: '12px' }}>
                    Best scenario: <strong>{cfOutcomes.best_scenario}</strong>
                  </p>
                  <div className="table-responsive">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Scenario</th>
                          <th>Action</th>
                          <th>Delay (hrs)</th>
                          <th>ENPV</th>
                          <th>P(Recovery)</th>
                          <th>Risk Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cfOutcomes.scenarios.map((s, i) => (
                          <tr key={i}>
                            <td>{s.name}</td>
                            <td>{s.action_type}</td>
                            <td className="mono-cell">{s.delay_hours}</td>
                            <td className="currency">{money(s.expected_net_value)}</td>
                            <td>{Math.round(s.recovery_probability * 100)}%</td>
                            <td className="text-secondary">{s.risk_notes || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Audit Trail */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Activity size={18} />
              <span className="panel-title">Audit Trail</span>
              <span className="badge-count">{auditEvents.length} events</span>
            </div>
          </div>
          <div className="panel-body">
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Event Type</th>
                    <th>Actor</th>
                    <th>Input Hash</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {auditEvents.length === 0 ? (
                    <tr>
                      <td colSpan="5">
                        <div className="empty-state">
                          <FileText size={24} />
                          <p>No audit events recorded.</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    auditEvents.map((evt) => (
                      <tr key={evt.event_id}>
                        <td className="mono-cell timestamp-cell">{formatTimestamp(evt.timestamp)}</td>
                        <td>
                          <span className="tag-badge tag-run">{evt.event_type}</span>
                        </td>
                        <td>{evt.actor || '—'}</td>
                        <td className="mono-cell">{evt.input_snapshot_hash.slice(0, 12)}…</td>
                        <td className="text-secondary">{evt.outcome || '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </ScrollFade>
    </div>
  );
}

function ExperimentComparison({ onBack, refreshTrigger }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ people: 200, hours: 72, seed: 42 });

  const runExperiment = async () => {
    const ok = window.confirm(
      `Run experiment: ${form.people} people, ${form.hours} hours, seed=${form.seed}? ` +
      'This resets the database and runs both baseline + smart engines.'
    );
    if (!ok) return;

    setLoading(true);
    setReport(null);
    try {
      const data = await runExperimentComparison(form.people, form.hours, form.seed);
      setReport(data);
    } catch (e) {
      alert('Experiment failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const summaryCards = useMemo(() => {
    if (!report) return [];

    const baseline = report.baseline?.metrics;
    const smart = report.smart?.metrics;
    const lift = report.lift;

    return [
      { title: 'Recovery Rate Lift', value: lift ? `${((lift.recovery_rate_lift || 0) * 100).toFixed(1)}%` : '—', desc: 'Improvement in recovery rate', colorClass: 'stat-green' },
      { title: 'Recovered Value Lift', value: lift ? money(lift.net_recovered_value_lift) : '—', desc: 'Incremental net recovered value', colorClass: 'stat-indigo' },
      { title: 'Wasted Retries Saved', value: lift ? `${lift.wasted_retries_reduction || 0}` : '—', desc: 'Fewer wasted retries', colorClass: 'stat-sky' },
      { title: 'False Stops', value: smart?.duplicate_risk_incidents !== undefined ? `${smart.duplicate_risk_incidents}` : '—', desc: 'Duplicate-risk incidents (target: 0)', colorClass: 'stat-amber' },
    ];
  }, [report]);

  const renderMetricsTable = (metrics, engineLabel, colorClass) => {
    if (!metrics) return <p className="text-secondary">No data</p>;
    const rows = [
      { label: 'Total Cases', value: metrics.total_cases },
      { label: 'Recovered Cases', value: metrics.recovered_cases },
      { label: 'Total Recovered Value', value: money(metrics.total_recovered_value) },
      { label: 'Total Retries', value: metrics.total_retries },
      { label: 'Wasted Retries', value: metrics.wasted_retries },
      { label: 'Total Outreach', value: metrics.total_outreach },
      { label: 'Mean Time to Recovery (h)', value: metrics.mean_time_to_recovery_hours },
      { label: 'Stop Count', value: metrics.stop_count },
      { label: 'Total Cost', value: money(metrics.total_cost) },
      { label: 'Net Recovered Value', value: money(metrics.net_recovered_value) },
    ];
    return (
      <table className="data-table">
        <thead>
          <tr>
            <th colSpan="2" className={colorClass}>{engineLabel}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="text-muted">{r.label}</td>
              <td className={r.value && typeof r.value === 'string' && r.value.includes('₹') ? 'currency' : 'mono-cell'}>{r.value ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  return (
    <div className="smart-experiment">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <GitBranch size={18} />
              <span className="panel-title">Experiment Configuration</span>
            </div>
          </div>
          <div className="panel-body">
            <div className="smart-form-grid">
              <div className="form-group">
                <label>People Count</label>
                <input
                  type="number"
                  className="search-input"
                  value={form.people}
                  onChange={(e) => setForm({ ...form, people: parseInt(e.target.value) || 100 })}
                  min="10"
                />
              </div>
              <div className="form-group">
                <label>Hours</label>
                <input
                  type="number"
                  className="search-input"
                  value={form.hours}
                  onChange={(e) => setForm({ ...form, hours: parseInt(e.target.value) || 72 })}
                  min="1"
                />
              </div>
              <div className="form-group">
                <label>Seed</label>
                <input
                  type="number"
                  className="search-input"
                  value={form.seed}
                  onChange={(e) => setForm({ ...form, seed: parseInt(e.target.value) || 42 })}
                  min="0"
                />
              </div>
            </div>
            <button className="btn btn-primary" onClick={runExperiment} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
              <span>{loading ? 'Running Experiment...' : 'Run Experiment'}</span>
            </button>
          </div>
        </div>
      </ScrollFade>

      {report && (
        <>
          <ScrollFade className="animate-scroll-fade">
            <div className="stats-grid smart-stats">
              {summaryCards.map((card, idx) => {
                return (
                  <div key={idx} className={`stat-card ${card.colorClass}`} style={{ '--index': idx }}>
                    <div className="stat-card-header">
                      <span className="stat-title">{card.title}</span>
                    </div>
                    <div className="stat-value">{card.value}</div>
                    <div className="stat-desc">{card.desc}</div>
                  </div>
                );
              })}
            </div>
          </ScrollFade>

          <ScrollFade className="animate-scroll-fade">
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title-group">
                  <BarChart3 size={18} />
                  <span className="panel-title">Side-by-Side Metrics</span>
                </div>
                <button className="btn btn-outline btn-sm" onClick={() => window.open(`/experiments/${report.experiment_id}.json`, '_blank')}>
                  <ExternalLink size={14} />
                  <span>View Raw Report</span>
                </button>
              </div>
              <div className="panel-body">
                <div className="smart-comparison-tables">
                  <div className="comparison-col">
                    {renderMetricsTable(report.baseline?.metrics, 'Baseline Engine', 'stat-sky')}
                  </div>
                  <div className="comparison-col">
                    {renderMetricsTable(report.smart?.metrics, 'Smart Agent (SARA)', 'stat-indigo')}
                  </div>
                </div>
              </div>
            </div>
          </ScrollFade>
        </>
      )}

      {!report && !loading && (
        <ScrollFade className="animate-scroll-fade">
          <div className="panel">
            <div className="panel-body">
              <div className="empty-state">
                <GitBranch size={32} />
                <p>Configure and run an experiment to see baseline vs Smart Agent comparison.</p>
              </div>
            </div>
          </div>
        </ScrollFade>
      )}
    </div>
  );
}

function ParallelExperimentView({ onCaseSelect, refreshTrigger }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [form, setForm] = useState({ people: 200, hours: 72, seed: 42 });
  const [experimentList, setExperimentList] = useState([]);
  const [caseDetail, setCaseDetail] = useState(null);
  const [caseDetailLoading, setCaseDetailLoading] = useState(false);

  const experimentId = report?.experiment_id;

  const runExperiment = async () => {
    const ok = window.confirm(
      `Run parallel experiment: ${form.people} people, ${form.hours} hours, seed=${form.seed}? ` +
      'Both engines will run simultaneously on separate schemas.'
    );
    if (!ok) return;

    setLoading(true);
    setReport(null);
    setCaseDetail(null);
    try {
      const data = await runParallelExperiment(form.people, form.hours, form.seed);
      setReport(data);
    } catch (e) {
      alert('Parallel experiment failed: ' + e.message);
    } finally {
      setLoading(false);
    }
  };

  const loadExperimentList = useCallback(async () => {
    setListLoading(true);
    try {
      const data = await listParallelExperiments(20);
      setExperimentList(data.experiments ?? []);
    } catch (e) {
      console.error('Failed to load experiment list:', e);
    } finally {
      setListLoading(false);
    }
  }, [refreshTrigger]);

  useEffect(() => {
    loadExperimentList();
  }, [loadExperimentList]);

  const summaryCards = useMemo(() => {
    if (!report) return [];

    const b = report.baseline?.metrics;
    const s = report.smart?.metrics;
    const lift = report.lift;

    return [
      { title: 'Recovery Rate Lift', value: `${lift?.incremental_recovery_rate || 0}%`, desc: 'Improvement in recovery rate (pp)', colorClass: 'stat-green' },
      { title: 'Incremental Net Recovered', value: money(lift?.incremental_recovered_value), desc: 'Smart Agent vs Baseline', colorClass: 'stat-indigo' },
      { title: 'Wasted Retries Saved', value: `${lift?.wasted_retry_reduction || 0}`, desc: 'Fewer wasted retries', colorClass: 'stat-sky' },
      { title: 'Duplicate Risk', value: `${s?.duplicate_risk_incidents || 0}`, desc: 'Smart Agent duplicate-risk incidents', colorClass: 'stat-amber' },
    ];
  }, [report]);

  const renderMetricsTable = (metrics, engineLabel, colorClass) => {
    if (!metrics) return <p className="text-secondary">No data</p>;
    const rows = [
      { label: 'Total Cases', value: metrics.total_cases },
      { label: 'Recovered Cases', value: metrics.recovered_cases },
      { label: 'Total Recovered Value', value: money(metrics.total_recovered_value) },
      { label: 'Total Retries', value: metrics.total_retries },
      { label: 'Wasted Retries', value: metrics.wasted_retries },
      { label: 'Total Outreach', value: metrics.total_outreach },
      { label: 'Mean Time to Recovery (h)', value: metrics.mean_time_to_recovery_hours ?? '—' },
      { label: 'Stop Count', value: metrics.stop_count },
      { label: 'Correct Stops', value: metrics.correct_stops },
      { label: 'Duplicate Risk Incidents', value: metrics.duplicate_risk_incidents },
      { label: 'Total Cost', value: money(metrics.total_cost) },
      { label: 'Net Recovered Value', value: money(metrics.net_recovered_value) },
    ];
    return (
      <table className="data-table">
        <thead>
          <tr>
            <th colSpan="2" className={colorClass}>{engineLabel}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="text-muted">{r.label}</td>
              <td className={r.value && typeof r.value === 'string' && r.value.includes('₹') ? 'currency' : 'mono-cell'}>{r.value ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const loadCaseDetail = useCallback(async (experimentId, caseId, engine) => {
    setCaseDetailLoading(true);
    try {
      const data = await fetchParallelExperimentCaseDetail(experimentId, caseId, engine);
      setCaseDetail(data);
    } catch (e) {
      console.error('Failed to load case detail:', e);
    } finally {
      setCaseDetailLoading(false);
    }
  }, []);

  const renderCaseList = (cases, engine) => {
    if (!cases) return null;
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Activity size={18} />
            <span className="panel-title">{engine === 'baseline' ? 'Baseline' : 'Smart Agent'} Cases</span>
            <span className="badge-count">{cases.length} cases</span>
          </div>
          <button className="btn btn-outline btn-sm" onClick={() => setCaseDetail(null)}>
            <ChevronLeft size={14} /> Back to Experiment
          </button>
        </div>
        <div className="panel-body">
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Intent ID</th>
                  <th>Action Type</th>
                  <th>Outcome</th>
                  <th>Failure</th>
                  <th>Amount</th>
                  <th>Retry #</th>
                  <th>Scheduled</th>
                </tr>
              </thead>
              <tbody>
                {cases.length === 0 ? (
                  <tr>
                    <td colSpan="7">
                      <div className="empty-state">
                        <Activity size={24} />
                        <p>No cases found.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  cases.map((c) => (
                    <tr
                      key={c.action_id}
                      onClick={() => loadCaseDetail(experimentId, c.action_id, engine)}
                    >
                      <td className="mono-cell">{c.intent_id.slice(0, 12)}…</td>
                      <td>
                        <span className={`tag-badge ${ACTION_TYPE_COLORS[c.action_type] || 'tag-default'}`}>
                          {ACTION_TYPE_LABELS[c.action_type] || c.action_type}
                        </span>
                      </td>
                      <td>
                        <span className={`tag-badge ${OUTCOME_COLORS[c.outcome || 'PENDING'] || 'tag-unknown'}`}>
                          {OUTCOME_LABELS[c.outcome || 'PENDING'] || (c.outcome || 'PENDING')}
                        </span>
                      </td>
                      <td>
                        <span className="tag-badge tag-run">{c.failure_code || '—'}</span>
                      </td>
                      <td className="currency">{money(c.amount)}</td>
                      <td className="mono-cell">{c.retry_number}</td>
                      <td className="mono-cell timestamp-cell">{formatTimestamp(c.scheduled_for)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  const renderCaseDetail = () => {
    if (!caseDetail) return null;
    if (caseDetail._action === 'list') {
      return renderCaseList(caseDetail.cases, caseDetail.engine);
    }

    const c = caseDetail;
    if (caseDetailLoading) {
      return <p className="text-secondary">Loading case…</p>;
    }

    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <button className="btn btn-outline btn-sm"
              onClick={() => setCaseDetail({ _action: 'list', engine: c.engine, cases: c.cases || [] })}
            >
              <ChevronLeft size={14} /> Case Detail →
            </button>
            <FileText size={16} />
            <span className="panel-title" style={{ cursor: 'pointer' }}>Case Detail</span>
          </div>
        </div>
        <div className="panel-body">
          <div className="smart-case-grid">
            <div className="smart-case-field"><span className="field-label">Action ID</span><span className="field-value mono-cell">{c.action_id.slice(0, 16)}…</span></div>
            <div className="smart-case-field"><span className="field-label">Intent ID</span><span className="field-value mono-cell">{c.intent_id.slice(0, 16)}…</span></div>
            <div className="smart-case-field"><span className="field-label">Engine</span><span className="field-value"><span className={`tag-badge ${c.engine === 'baseline' ? 'tag-run' : 'tag-stop'}`}>{c.engine === 'baseline' ? 'Baseline' : 'Smart Agent'}</span></span></div>
            <div className="smart-case-field"><span className="field-label">Action Type</span><span className="field-value"><span className={`tag-badge ${ACTION_TYPE_COLORS[c.action_type] || 'tag-default'}`}>{ACTION_TYPE_LABELS[c.action_type] || c.action_type}</span></span></div>
            <div className="smart-case-field"><span className="field-label">Outcome</span><span className="field-value"><span className={`tag-badge ${OUTCOME_COLORS[c.outcome || 'PENDING'] || 'tag-unknown'}`}>{OUTCOME_LABELS[c.outcome || 'PENDING'] || (c.outcome || 'PENDING')}</span></span></div>
            <div className="smart-case-field"><span className="field-label">Amount</span><span className="field-value currency">{money(c.amount)}</span></div>
            <div className="smart-case-field"><span className="field-label">Retry #</span><span className="field-value mono-cell">{c.retry_number}</span></div>
            <div className="smart-case-field"><span className="field-label">Failure Code</span><span className="field-value">{c.failure_code || '—'}</span></div>
            <div className="smart-case-field"><span className="field-label">Scheduled For</span><span className="field-value mono-cell">{formatTimestamp(c.scheduled_for)}</span></div>
            <div className="smart-case-field"><span className="field-label">Executed At</span><span className="field-value mono-cell">{formatTimestamp(c.executed_at)}</span></div>
            <div className="smart-case-field"><span className="field-label">Expected Recovery</span><span className="field-value currency">{money(c.expected_recovery)}</span></div>
            <div className="smart-case-field"><span className="field-label">Cost</span><span className="field-value currency">{money(c.cost)}</span></div>
            <div className="smart-case-field full-width"><span className="field-label">Reason</span><span className="field-value text-secondary">{c.reason || '—'}</span></div>
          </div>

          {/* Diagnosis (smart agent only) */}
          {c.engine === 'smart' && c.diagnosis && (
            <>
              <h3 className="smart-section-title">Root Cause Diagnosis</h3>
              <div className="smart-section-body">
                <div className="smart-diagnosis">
                  {c.diagnosis.root_cause && (
                    <div className="diag-row">
                      <span className="diag-label">Root Cause:</span>
                      <span className="diag-value">{c.diagnosis.root_cause}</span>
                    </div>
                  )}
                  {c.diagnosis.confidence !== undefined && (
                    <div className="diag-row">
                      <span className="diag-label">Confidence:</span>
                      <span className="diag-value">{(c.diagnosis.confidence * 100).toFixed(1)}%</span>
                    </div>
                  )}
                  {c.diagnosis.explanation && (
                    <div className="diag-row">
                      <span className="diag-label">Explanation:</span>
                      <span className="diag-value">{c.diagnosis.explanation}</span>
                    </div>
                  )}
                  {c.diagnosis.hypotheses && Array.isArray(c.diagnosis.hypotheses) && (
                    <div className="diag-row">
                      <span className="diag-label">Hypotheses:</span>
                      <div className="hypotheses-list">
                        {c.diagnosis.hypotheses.map((h, i) => (
                          <div key={i} className="hypothesis-item">
                            <span className="hyp-label">{h.label || h.hypothesis || h.name}</span>
                            <span className="hyp-confidence">{h.confidence !== undefined ? `${(h.confidence * 100).toFixed(0)}%` : ''}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {/* Policy Checks (smart agent only) */}
          {c.engine === 'smart' && c.policy_checks && c.policy_checks.length > 0 && (
            <>
              <h3 className="smart-section-title">Policy Checks</h3>
              <div className="smart-section-body">
                <table className="data-table policy-checks-table">
                  <thead><tr><th>Check</th><th>Passed</th><th>Detail</th></tr></thead>
                  <tbody>
                    {c.policy_checks.map((check, i) => (
                      <tr key={i}>
                        <td className="mono-cell">{check.name}</td>
                        <td>
                          <span className={`tag-badge ${check.passed ? 'tag-success' : 'tag-failed'}`}>
                            {check.passed ? 'PASS' : 'BLOCK'}
                          </span>
                        </td>
                        <td className="text-secondary">{check.detail || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Prior Actions (smart agent only) */}
          {c.engine === 'smart' && c.prior_actions && c.prior_actions.length > 0 && (
            <>
              <h3 className="smart-section-title">Prior Actions for This Intent</h3>
              <div className="smart-section-body">
                <div className="table-responsive">
                  <table className="data-table">
                    <thead><tr><th>Action ID</th><th>Type</th><th>Retry #</th><th>Outcome</th><th>Scheduled</th><th>Reason</th></tr></thead>
                    <tbody>
                      {c.prior_actions.map((pa) => (
                        <tr key={pa.action_id}>
                          <td className="mono-cell">{pa.action_id.slice(0, 12)}…</td>
                          <td>
                            <span className={`tag-badge ${ACTION_TYPE_COLORS[pa.action_type] || 'tag-default'}`}>
                              {ACTION_TYPE_LABELS[pa.action_type] || pa.action_type}
                            </span>
                          </td>
                          <td className="mono-cell">{pa.retry_number}</td>
                          <td>
                            <span className={`tag-badge ${OUTCOME_COLORS[pa.outcome || 'PENDING'] || 'tag-unknown'}`}>
                              {OUTCOME_LABELS[pa.outcome || 'PENDING'] || (pa.outcome || 'PENDING')}
                            </span>
                          </td>
                          <td className="mono-cell timestamp-cell">{formatTimestamp(pa.scheduled_for)}</td>
                          <td className="text-secondary">{pa.reason || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {/* Audit Trail (smart agent only) */}
          {c.engine === 'smart' && c.audit_trail && c.audit_trail.length > 0 && (
            <>
              <h3 className="smart-section-title">Audit Trail</h3>
              <div className="smart-section-body">
                <div className="table-responsive">
                  <table className="data-table">
                    <thead><tr><th>Timestamp</th><th>Event Type</th><th>Actor</th><th>Input Hash</th><th>Outcome</th></tr></thead>
                    <tbody>
                      {c.audit_trail.map((evt) => (
                        <tr key={evt.event_id}>
                          <td className="mono-cell timestamp-cell">{formatTimestamp(evt.timestamp)}</td>
                          <td><span className="tag-badge tag-run">{evt.event_type}</span></td>
                          <td>{evt.actor || '—'}</td>
                          <td className="mono-cell">{evt.input_snapshot_hash.slice(0, 12)}…</td>
                          <td className="text-secondary">{evt.outcome || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="smart-parallel-experiment">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <GitBranch size={18} />
              <span className="panel-title">Parallel Experiment Configuration</span>
            </div>
          </div>
          <div className="panel-body">
            <div className="smart-form-grid">
              <div className="form-group">
                <label>People Count</label>
                <input type="number" className="search-input" value={form.people}
                  onChange={(e) => setForm({ ...form, people: parseInt(e.target.value) || 100 })} min="10" />
              </div>
              <div className="form-group">
                <label>Hours</label>
                <input type="number" className="search-input" value={form.hours}
                  onChange={(e) => setForm({ ...form, hours: parseInt(e.target.value) || 72 })} min="1" />
              </div>
              <div className="form-group">
                <label>Seed</label>
                <input type="number" className="search-input" value={form.seed}
                  onChange={(e) => setForm({ ...form, seed: parseInt(e.target.value) || 42 })} min="0" />
              </div>
            </div>
            <button className="btn btn-primary" onClick={runExperiment} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'spin' : ''} />
              <span>{loading ? 'Running Parallel Experiment...' : 'Run Parallel Experiment'}</span>
            </button>
          </div>
        </div>
      </ScrollFade>

      {/* Live experiment results */}
      {report && (
        <>
          <ScrollFade className="animate-scroll-fade">
            <div className="stats-grid smart-stats">
              {summaryCards.map((card, idx) => (
                <div key={idx} className={`stat-card ${card.colorClass}`} style={{ '--index': idx }}>
                  <div className="stat-card-header">
                    <span className="stat-title">{card.title}</span>
                  </div>
                  <div className="stat-value">{card.value}</div>
                  <div className="stat-desc">{card.desc}</div>
                </div>
              ))}
            </div>
          </ScrollFade>

          <ScrollFade className="animate-scroll-fade">
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title-group">
                  <BarChart3 size={18} />
                  <span className="panel-title">Side-by-Side Metrics</span>
                </div>
                <button className="btn btn-outline btn-sm" onClick={() => window.open(`/experiments/${report.experiment_id}.json`, '_blank')}>
                  <ExternalLink size={14} />
                  <span>View Raw Report</span>
                </button>
              </div>
              <div className="panel-body">
                <div className="smart-comparison-tables">
                  <div className="comparison-col">
                    {renderMetricsTable(report.baseline?.metrics, 'Baseline Engine', 'stat-sky')}
                  </div>
                  <div className="comparison-col">
                    {renderMetricsTable(report.smart?.metrics, 'Smart Agent (SARA)', 'stat-indigo')}
                  </div>
                </div>

                <div className="smart-lift-section">
                  <div className="panel-title-group">
                    <TrendingUp size={16} />
                    <span className="panel-title">Lift Summary</span>
                  </div>
                  <p className="text-secondary" style={{ marginTop: '8px', fontSize: '13px' }}>
                    {report.notes || '—'}
                  </p>
                </div>

                {/* Case explorer — tabbed by engine */}
                <div className="smart-case-explorer">
                  <div className="panel-title-group">
                    <Search size={16} />
                    <span className="panel-title">Explore Cases by Engine</span>
                  </div>
                  {experimentId && report?.schemas_preserved ? (
                    <div className="smart-case-tabs">
                      {['baseline', 'smart'].map((eng) => (
                        <button
                          key={eng}
                          className="btn btn-secondary btn-sm"
                          onClick={async () => {
                            const data = await fetchParallelExperimentCases(experimentId, eng, 200);
                            setCaseDetail({ _action: 'list', engine: eng, cases: data.cases });
                          }}
                        >
                          {eng === 'baseline' ? 'Baseline' : 'Smart Agent'} Cases
                        </button>
                      ))}
                    </div>
                  ) : experimentId ? (
                    <p className="text-muted" style={{ marginTop: '4px', fontSize: '12px' }}>
                      Schemas were cleaned up. Run with keep_schemas=true to inspect per-agent audit events.
                    </p>
                  ) : (
                    <p className="text-muted" style={{ marginTop: '4px', fontSize: '12px' }}>
                      Run an experiment to enable case exploration.
                    </p>
                  )}
                </div>
              </div>

              {/* Case detail / list view */}
              {caseDetail && renderCaseDetail()}
            </div>
          </ScrollFade>
        </>
      )}

      {/* Experiment history */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <History size={18} />
              <span className="panel-title">Recent Parallel Experiments</span>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={loadExperimentList} disabled={listLoading}>
              <RefreshCw size={14} className={listLoading ? 'spin' : ''} />
              <span>Refresh</span>
            </button>
          </div>
          <div className="panel-body">
            {experimentList.length === 0 ? (
              <div className="empty-state">
                <GitBranch size={32} />
                <p>No parallel experiments found.</p>
              </div>
            ) : (
              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Experiment ID</th>
                      <th>Baseline Cases</th>
                      <th>Smart Cases</th>
                      <th>Lift (INR)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {experimentList.map((exp) => (
                      <tr key={exp.experiment_id}>
                        <td className="mono-cell">{exp.experiment_id}</td>
                        <td className="mono-cell">{exp.baseline_cases}</td>
                        <td className="mono-cell">{exp.smart_cases}</td>
                        <td className="currency">{money(exp.lift)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </ScrollFade>
    </div>
  );
}

// ---------- Rail Health ----------

function RailHealthView() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(false);
  const [method, setMethod] = useState(null);

  const loadHealth = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchRailHealth(method);
      setHealth(data);
    } catch (e) {
      console.error('Failed to load rail health:', e);
    } finally {
      setLoading(false);
    }
  }, [method]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  // health shape: { overall_health: 0.78, rails: [{ name, health, ... }, ...], method_used: "smart_agent" }
  const overall = health?.overall_health;
  const rails = health?.rails ?? [];
  const barColor = (h) => {
    if (!h) return 'var(--border)';
    if (h >= 0.7) return 'var(--pale-green)';
    if (h >= 0.4) return 'var(--pale-yellow)';
    return 'var(--pale-red)';
  };

  const renderRailRow = (rail) => {
    const h = rail.health ?? 0;
    const pct = Math.round(h * 100);
    return (
      <tr key={rail.name}>
        <td className="mono-cell">{rail.name}</td>
        <td>
          <div className="health-bar">
            <div className="health-fill" style={{ width: `${pct}%`, background: barColor(h) }}></div>
          </div>
        </td>
        <td className="mono-cell">{pct}%</td>
        <td className="text-secondary">{rail.incidents || 0} incidents</td>
        <td>
          {rail.last_check ? <span className="tag-badge tag-run">{formatTimestamp(rail.last_check)}</span> : <span className="text-muted">—</span>}
        </td>
      </tr>
    );
  };

  return (
    <div className="smart-rail-health">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Shield size={18} />
              <span className="panel-title">Rail Health</span>
              {method && <span className="badge-count">method: {method}</span>}
            </div>
            <div className="controls-bar">
              <select
                className="filter-select"
                value={method ?? ''}
                onChange={(e) => setMethod(e.target.value || null)}
              >
                <option value="">All Methods</option>
                <option value="smart_agent">Smart Agent</option>
                <option value="baseline">Baseline</option>
              </select>
              <button className="btn btn-secondary btn-sm" onClick={loadHealth} disabled={loading}>
                <RefreshCw size={14} className={loading ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>
          </div>
          <div className="panel-body">
            {loading ? (
              <p className="text-secondary">Loading rail health…</p>
            ) : !overall && !rails.length ? (
              <div className="empty-state">
                <Shield size={32} />
                <p>No rail health data available.</p>
              </div>
            ) : (
              <>
                <div className="smart-overall-health">
                  <span className="field-label">Overall Health</span>
                  <span className="stat-value currency">{(overall * 100).toFixed(0)}%</span>
                </div>
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Rail</th>
                        <th>Health</th>
                        <th>Score</th>
                        <th>Incidents</th>
                        <th>Last Check</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rails.map(renderRailRow)}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      </ScrollFade>
    </div>
  );
}

// ---------- Main component ----------

function SmartAgentView({ loading: externalLoading, onRefresh }) {
  const [activeSubTab, setActiveSubTab] = useState('cases');
  const [selectedCaseId, setSelectedCaseId] = useState(null);

  const handleCaseSelect = (caseId) => {
    setSelectedCaseId(caseId);
  };

  const handleBackToQueue = () => {
    setSelectedCaseId(null);
  };

  if (selectedCaseId && !activeSubTab.startsWith('experiment')) {
    return (
      <CaseDetail
        caseId={selectedCaseId}
        onBack={handleBackToQueue}
      />
    );
  }

  const renderSubTab = () => {
    switch (activeSubTab) {
      case 'cases':
        return <CasesQueue onCaseSelect={handleCaseSelect} />;
      case 'parallel':
        return <ParallelExperimentView onCaseSelect={handleCaseSelect} />;
      case 'experiment':
        return <ExperimentComparison onBack={() => setActiveSubTab('cases')} />;
      case 'rail-health':
        return <RailHealthView />;
      default:
        return <CasesQueue onCaseSelect={handleCaseSelect} />;
    }
  };

  return (
    <div className="smart-agent-view">
      <div className="smart-subtab-bar">
        {SUB_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeSubTab === tab.key;
          return (
            <button
              key={tab.key}
              className={`subtab-item ${isActive ? 'active' : ''}`}
              onClick={() => {
                setActiveSubTab(tab.key);
                setSelectedCaseId(null);
              }}
            >
              <Icon size={16} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div className="smart-subtab-content">
        {renderSubTab()}
      </div>
    </div>
  );
}

export default SmartAgentView;
