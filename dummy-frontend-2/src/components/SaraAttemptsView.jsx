import React, { useState, useEffect, useMemo } from 'react';
import {
  BookOpen,
  Search,
  RefreshCw,
  Filter,
  Activity,
  RefreshCw as RefreshIcon,
  CheckCircle2,
  XCircle,
  PauseCircle,
  TrendingUp,
  BarChart3,
  AlertOctagon,
} from './ui/icons';
import ScrollFade from './ui/ScrollFade';
import { money, pct } from '../utils/format';
import { fetchRecoveryMetrics, fetchRecoveryActions, fetchParallelExperimentMetrics, fetchParallelExperimentRetries, listParallelExperiments } from '../api';
import "./SaraAttemptsView.css";

const OUTCOME_LABELS = {
  PENDING: 'Pending',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  STOPPED: 'Stopped',
  UNKNOWN: 'Unknown',
};

const OUTCOME_ICONS = {
  PENDING: 'Clock',
  SUCCESS: 'CheckCircle2',
  FAILED: 'XCircle',
  STOPPED: 'PauseCircle',
  UNKNOWN: 'AlertOctagon',
};

const formatTimestamp = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return '—'; }
};

const SaraAttemptsView = ({ onRefresh, experimentId }) => {
  const [metrics, setMetrics] = useState(null);
  const [attempts, setAttempts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const pageSize = 100;

  // Fetch lifetime SARA retry data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Resolve which experiment to read from. Prefer the prop, but on a
        // page refresh the prop is null — in that case look up the most
        // recent preserved experiment so the data survives a reload.
        let resolvedExperimentId = experimentId;
        if (!resolvedExperimentId) {
          try {
            const experiments = await listParallelExperiments(1);
            if (experiments?.experiments?.length) {
              const latest = experiments.experiments[0];
              resolvedExperimentId = latest.experiment_id || latest.id;
            }
          } catch (listErr) {
            console.warn('Could not list parallel experiments:', listErr);
          }
        }

        // Prefer the parallel experiment schema when one is available — that's
        // where SARA's AI_AGENT run actually lives. Fall back to the lifetime view.
        if (resolvedExperimentId) {
          try {
            const [metricsData, actionsData] = await Promise.all([
              fetchParallelExperimentMetrics(resolvedExperimentId, 'smart'),
              fetchParallelExperimentRetries(resolvedExperimentId, 'smart', 5000),
            ]);
            setMetrics(metricsData);
            setAttempts(actionsData?.actions ?? []);
            setLoading(false);
            return;
          } catch (parallelErr) {
            console.warn(
              'Parallel experiment schema unavailable, falling back to lifetime SARA data:',
              parallelErr
            );
            // fall through to lifetime query
          }
        }

        const metricsData = await fetchRecoveryMetrics(null, 'AI_AGENT');
        setMetrics(metricsData);

        const actionsData = await fetchRecoveryActions(5000, undefined, 'RETRY', 'AI_AGENT');
        setAttempts(actionsData?.actions ?? []);
      } catch (e) {
        console.error('Failed to fetch SARA attempts data:', e);
        setError(e.message || 'Failed to load SARA attempts data');
        setMetrics(null);
        setAttempts([]);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [refreshKey, experimentId]);

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1);
    if (onRefresh) onRefresh();
  };

  const filteredAttempts = useMemo(() => {
    let filtered = attempts;
    if (outcomeFilter) {
      filtered = filtered.filter((a) => (a.outcome || 'UNKNOWN') === outcomeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      filtered = filtered.filter(
        (a) =>
          (a.failure_code && a.failure_code.toLowerCase().includes(q)) ||
          (a.failure_reason && a.failure_reason.toLowerCase().includes(q)) ||
          (a.payment_intent_id && a.payment_intent_id.toLowerCase().includes(q)) ||
          (a.action_type && a.action_type.toLowerCase().includes(q))
      );
    }
    return filtered;
  }, [attempts, search, outcomeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredAttempts.length / pageSize));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredAttempts.slice(start, start + pageSize);
  }, [filteredAttempts, currentPage]);

  const handlePageChange = (page) => {
    if (page >= 1 && page <= totalPages) setCurrentPage(page);
  };

  const resetFilters = () => {
    setSearch('');
    setOutcomeFilter('');
    setCurrentPage(1);
  };

  const getOutcomeBadgeClass = (outcome) => {
    const map = {
      SUCCESS: 'tag-success',
      FAILED: 'tag-failed',
      STOPPED: 'tag-stopped',
      PENDING: 'tag-pending',
      UNKNOWN: 'tag-unknown',
    };
    return `tag-badge ${map[outcome] || ''}`;
  };

  // Recovery rate: successful_attempts / total_failed_payments.
  // Numerator is the agent's successful retry attempts; denominator is the
  // GLOBAL count of failed transactions (not this agent's own retry count).
  const recoveryRatePct = useMemo(() => {
    const total = metrics?.total_failed_payments ?? 0;
    const succeededAttempts = metrics?.retries_successful ?? 0;
    if (total === 0) return '0.0%';
    return `${((succeededAttempts / total) * 100).toFixed(1)}%`;
  }, [metrics]);

  const summaryCards = metrics
    ? [
        { title: 'Total Actions', value: metrics.total_recovery_actions ?? 0, desc: 'All recovery actions', icon: Activity, colorClass: 'stat-indigo' },
        { title: 'Failed Payments', value: metrics.total_failed_payments ?? 0, desc: 'Distinct failed intents', icon: AlertOctagon, colorClass: 'stat-indigo' },
        { title: 'Retries Attempted', value: metrics.retry_actions ?? 0, desc: 'Retry actions created', icon: RefreshIcon, colorClass: 'stat-sky' },
        { title: 'Successful', value: metrics.successful_recoveries ?? 0, desc: 'Recovered payments', icon: CheckCircle2, colorClass: 'stat-green' },
        { title: 'Failed', value: metrics.failed_recoveries ?? 0, desc: 'Retries that failed', icon: XCircle, colorClass: 'stat-red' },
        { title: 'Stopped', value: metrics.stopped_recoveries ?? 0, desc: 'Recovery stopped', icon: PauseCircle, colorClass: 'stat-amber' },
        { title: 'Recovered GMV', value: money(metrics.total_recovered_gmv), desc: `Recovery rate: ${recoveryRatePct} (successful attempts / total failed payments)`, icon: TrendingUp, colorClass: 'stat-green' },
      ]
    : [];

  return (
    <div className="sara-attempts-view">
      {/* Summary Cards */}
      <ScrollFade className="animate-scroll-fade">
        {metrics ? (
          <div className="stats-grid recovery-stats">
            {summaryCards.map((card, idx) => {
              const Icon = card.icon;
              return (
                <div key={idx} className={`stat-card ${card.colorClass}`} style={{ '--index': idx }}>
                  <div className="stat-card-header">
                    <span className="stat-title">{card.title}</span>
                    <div className="stat-icon-wrapper">
                      <Icon size={18} />
                    </div>
                  </div>
                  <div className="stat-value">{card.value}</div>
                  <div className="stat-desc">{card.desc}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="panel">
            <div className="panel-body">
              <p className="text-secondary">
                {loading
                  ? 'Loading SARA attempts metrics...'
                  : error
                    ? `Error: ${error}`
                    : 'No SARA attempts data available. Run the simulation to see metrics.'}
              </p>
            </div>
          </div>
        )}
      </ScrollFade>

      {/* SARA Attempts Ledger */}
      <ScrollFade className="animate-scroll-fade" style={{ '--index': 1 }}>
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BookOpen size={18} />
              <span className="panel-title">SARA Retry Ledger</span>
              <span className="badge-count">{filteredAttempts.length} Retries</span>
            </div>
            <div className="controls-bar">
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search by failure code, reason, or amount…"
                  className="search-input"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setCurrentPage(1);
                  }}
                />
              </div>

              <div className="filter-group">
                <Filter size={14} />
                <select
                  className="select-filter"
                  value={outcomeFilter}
                  onChange={(e) => {
                    setOutcomeFilter(e.target.value);
                    setCurrentPage(1);
                  }}
                >
                  <option value="">All Outcomes</option>
                  <option value="PENDING">Pending</option>
                  <option value="SUCCESS">Success</option>
                  <option value="FAILED">Failed</option>
                  <option value="STOPPED">Stopped</option>
                </select>
              </div>

              {(search || outcomeFilter) && (
                <button className="btn btn-outline btn-sm" onClick={resetFilters}>
                  Clear
                </button>
              )}

              <button
                className="btn btn-outline"
                onClick={handleRefresh}
                disabled={loading}
                style={{ padding: '6px 14px', fontSize: '12px' }}
              >
                <RefreshCw size={12} className={loading ? 'spinner' : ''} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Retry #</th>
                  <th>Failure Code</th>
                  <th>Failure Reason</th>
                  <th>Amount</th>
                  <th>ENPV</th>
                  <th>Prob. of Success</th>
                  <th>Expected Recovery</th>
                  <th>Scheduled</th>
                  <th>Executed</th>
                  <th>Outcome</th>
                  <th>Customer Declined</th>
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan="11">
                      <div className="empty-state">
                        <BookOpen size={32} />
                        <p>{loading ? 'Loading SARA retry attempts…' : 'No SARA retry attempts found.'}</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginated.map((attempt, i) => {
                    const OutcomeIcon = OUTCOME_ICONS[attempt.outcome] || 'Clock';
                    // ENPV and probability are persisted in the audit event's
                    // decision JSON for SARA decisions. Older rows or non-SARA
                    // actions won't have them, so we fall back to '—'.
                    const decision = attempt.decision || {};
                    const enpv = decision.expected_net_value;
                    const prob = decision.recovery_probability;
                    return (
                      <tr key={attempt.action_id || i}>
                        <td className="mono-cell">{attempt.retry_number ?? '—'}</td>
                        <td>
                          <span className="font-mono text-xs text-tertiary">
                            {attempt.failure_code || '—'}
                          </span>
                        </td>
                        <td className="text-sm text-secondary max-w-xs truncate block">
                          {attempt.failure_reason || '—'}
                        </td>
                        <td className="currency">
                          ₹{parseFloat(attempt.amount || 0).toLocaleString()}
                        </td>
                        <td className="mono-cell text-sm">
                          {enpv != null && enpv !== '' ? `₹${parseFloat(enpv).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '—'}
                        </td>
                        <td className="mono-cell text-sm">
                          {prob != null ? pct(prob) : '—'}
                        </td>
                        <td className="mono-cell text-sm">
                          {attempt.expected_recovery != null && attempt.expected_recovery !== ''
                            ? `₹${parseFloat(attempt.expected_recovery).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
                            : '—'}
                        </td>
                        <td className="mono-cell" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                          {formatTimestamp(attempt.scheduled_for)}
                        </td>
                        <td className="mono-cell" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                          {formatTimestamp(attempt.executed_at)}
                        </td>
                        <td>
                          <span className={getOutcomeBadgeClass(attempt.outcome)}>
                            <OutcomeIcon size={12} />
                            {OUTCOME_LABELS[attempt.outcome] || attempt.outcome}
                          </span>
                        </td>
                        <td className={attempt.customer_declined ? 'text-red mono-cell' : 'mono-cell text-muted'}>
                          {attempt.customer_declined ? 'Yes' : 'No'}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {filteredAttempts.length > 0 && (
            <div className="pagination">
              <div className="page-info">
                Showing {(currentPage - 1) * pageSize + 1} to{' '}
                {Math.min(currentPage * pageSize, filteredAttempts.length)} of{' '}
                {filteredAttempts.length} retry attempts
              </div>
              <div className="page-actions">
                <button
                  className="btn btn-secondary"
                  style={{ padding: '6px 12px' }}
                  disabled={currentPage === 1 || loading}
                  onClick={() => handlePageChange(currentPage - 1)}
                >
                  Previous
                </button>
                <span className="page-number">
                  {currentPage} / {totalPages}
                </span>
                <button
                  className="btn btn-secondary"
                  style={{ padding: '6px 12px' }}
                  disabled={currentPage === totalPages || loading}
                  onClick={() => handlePageChange(currentPage + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </ScrollFade>
    </div>
  );
};

export default SaraAttemptsView;
