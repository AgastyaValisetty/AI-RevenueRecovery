import React, { useState, useMemo } from 'react';
import {
  RefreshCw, Activity, Clock, AlertOctagon, CheckCircle2, XCircle, PauseCircle,
  TrendingUp, BarChart3, Search, Inbox,
} from './ui/icons';
import ScrollFade from './ui/ScrollFade';
import { money, pct } from '../utils/format';
import "./RecoveryView.css";

const ACTION_TYPE_LABELS = {
  RETRY: 'Retry',
  SEND_PAYMENT_LINK: 'Payment Link',
  SEND_NOTIFICATION: 'Notification',
  STOP: 'Stop',
};

const OUTCOME_LABELS = {
  PENDING: 'Pending',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  STOPPED: 'Stopped',
  UNKNOWN: 'Unknown',
};

const OUTCOME_ICONS = {
  PENDING: Clock,
  SUCCESS: CheckCircle2,
  FAILED: XCircle,
  STOPPED: PauseCircle,
  UNKNOWN: AlertOctagon,
};

const formatTimestamp = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return '—'; }
};

const RecoveryView = ({ onRefresh, metrics: externalMetrics, actions: externalActions, loading: externalLoading, detailedMetrics, auditMode }) => {
  const [metrics, setMetrics] = useState(externalMetrics ?? null);
  const [actions, setActions] = useState(externalActions ?? []);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(externalLoading ?? false);
  const [search, setSearch] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const pageSize = 50;

  useState(() => {
    if (!externalMetrics && !metrics) {
      setLoading(true);
      Promise.all([
        import('../api').then(m => m.fetchRecoveryMetrics()),
        import('../api').then(m => m.fetchRecoveryActions()),
        import('../api').then(m => m.fetchRecoveryRuns()),
      ]).then(([metricsData, actionsData, runsData]) => {
        setMetrics(metricsData);
        setActions(actionsData?.actions ?? []);
        setRuns(runsData?.runs ?? []);
      }).catch((e) => {
        console.error('Recovery data fetch error:', e);
      }).finally(() => {
        setLoading(false);
      });
    }
  });

  const handleRefresh = () => {
    if (onRefresh) onRefresh();
  };

  const filteredActions = useMemo(() => {
    let filtered = actions;
    if (outcomeFilter) {
      filtered = filtered.filter((a) => (a.outcome || 'UNKNOWN') === outcomeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      filtered = filtered.filter(
        (a) =>
          (a.failure_code && a.failure_code.toLowerCase().includes(q)) ||
          (a.action_type && a.action_type.toLowerCase().includes(q)) ||
          (a.payment_intent_id && a.payment_intent_id.toLowerCase().includes(q))
      );
    }
    return filtered;
  }, [actions, search, outcomeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredActions.length / pageSize));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredActions.slice(start, start + pageSize);
  }, [filteredActions, currentPage]);

  const handlePageChange = (page) => {
    if (page >= 1 && page <= totalPages) setCurrentPage(page);
  };

  const resetFilters = () => {
    setSearch('');
    setOutcomeFilter('');
    setCurrentPage(1);
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
        { title: 'Retries Attempted', value: metrics.total_retries_attempted ?? 0, desc: 'Retry actions created', icon: RefreshCw, colorClass: 'stat-sky' },
        { title: 'Successful', value: metrics.successful_recoveries ?? 0, desc: 'Recovered payments', icon: CheckCircle2, colorClass: 'stat-green' },
        { title: 'Failed', value: metrics.failed_recoveries ?? 0, desc: 'Retries that failed', icon: XCircle, colorClass: 'stat-red' },
        { title: 'Stopped', value: metrics.stopped_recoveries ?? 0, desc: 'Recovery stopped', icon: PauseCircle, colorClass: 'stat-amber' },
        { title: 'Recovered GMV', value: money(metrics.total_recovered_gmv), desc: `Recovery rate: ${recoveryRatePct} (successful attempts / total failed payments)`, icon: TrendingUp, colorClass: 'stat-green' },
      ]
    : [];

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

  const getActionTypeBadgeClass = (actionType) => {
    if (actionType === 'RETRY') return 'tag-badge tag-retry';
    if (actionType === 'STOP') return 'tag-badge tag-stop';
    if (actionType === 'SEND_PAYMENT_LINK') return 'tag-badge tag-link';
    if (actionType === 'SEND_NOTIFICATION') return 'tag-badge tag-notification';
    return 'tag-badge tag-default';
  };

  const getOutcomeColorClass = (outcome) => {
    const map = {
      SUCCESS: 'stat-green',
      FAILED: 'stat-red',
      STOPPED: 'stat-amber',
      PENDING: 'stat-sky',
      UNKNOWN: 'stat-charcoal',
    };
    return map[outcome] || '';
  };

  return (
    <div className="recovery-view">
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
                  ? 'Loading recovery metrics...'
                  : 'No recovery data available. Run the simulation to see recovery metrics.'}
              </p>
            </div>
          </div>
        )}
      </ScrollFade>

      {/* Recovery runs */}
      <ScrollFade className="animate-scroll-fade" style={{ '--index': 1 }}>
        {runs.length > 0 && (
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title-group">
                <Activity size={18} />
                <span className="panel-title">Recovery Runs</span>
                <span className="badge-count">{runs.length} runs</span>
              </div>
            </div>
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Strategy</th>
                    <th>Seed</th>
                    <th>Status</th>
                    <th>Max Retries</th>
                    <th>Actions</th>
                    <th>Recovered GMV</th>
                    <th>Started</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.run_id}>
                      <td className="mono-cell" title={run.run_id}>
                        {run.run_id.slice(0, 13)}...
                      </td>
                      <td>
                        <span className="tag-badge tag-run">{run.engine_type || 'BASELINE'}</span>
                      </td>
                      <td className="mono-cell">{run.seed}</td>
                      <td>
                        <span className={`tag-badge ${
                          run.status === 'COMPLETED' ? 'tag-success' :
                          run.status === 'RUNNING' ? 'tag-pending' :
                          'tag-failed'
                        }`}>
                          {run.status}
                        </span>
                      </td>
                      <td>{run.max_retries}</td>
                      <td>{run.total_recovery_actions ?? 0}</td>
                      <td className="currency">{money(run.recovered_gmv)}</td>
                      <td className="mono-cell timestamp-cell">{formatTimestamp(run.started_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </ScrollFade>

      {/* Recovery Actions table */}
      <ScrollFade className="animate-scroll-fade" style={{ '--index': 2 }}>
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BarChart3 size={18} />
              <span className="panel-title">Recovery Actions</span>
              <span className="badge-count">{filteredActions.length} shown</span>
            </div>
            <div className="controls-bar">
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search failure code, type, or intent..."
                  className="search-input"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setCurrentPage(1);
                  }}
                />
              </div>
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
              {(search || outcomeFilter) && (
                <button className="btn btn-outline btn-sm" onClick={resetFilters}>
                  Clear
                </button>
              )}
              <button className="btn btn-outline btn-sm" onClick={handleRefresh} disabled={loading}>
                <RefreshCw size={14} className={loading ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Type</th>
                  <th>Retry #</th>
                  <th>Failure</th>
                  <th>Amount</th>
                  <th>Scheduled</th>
                  <th>Executed</th>
                  <th>Outcome</th>
                  <th>Customer</th>
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan="9">
                      <div className="empty-state">
                        <Inbox size={32} />
                        <p>
                          {loading
                            ? 'Loading recovery actions...'
                            : 'No recovery actions to show. Run the simulation to generate failed payments.'}
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginated.map((action) => {
                    const OutcomeIcon = OUTCOME_ICONS[action.outcome] || Clock;
                    return (
                      <tr key={action.action_id}>
                        <td className="mono-cell" title={action.action_id}>
                          {action.action_id.slice(0, 13)}...
                        </td>
                        <td>
                          <span className={getActionTypeBadgeClass(action.action_type)}>
                            {ACTION_TYPE_LABELS[action.action_type] || action.action_type}
                          </span>
                        </td>
                        <td className="mono-cell">{action.retry_number ?? '—'}</td>
                        <td>
                          <span className="tag-badge tag-failed">{action.failure_code || '—'}</span>
                          {action.failure_reason && (
                            <div className="reason-sub">{action.failure_reason}</div>
                          )}
                        </td>
                        <td className="currency">{money(action.amount)}</td>
                        <td className="mono-cell timestamp-cell">{formatTimestamp(action.scheduled_for)}</td>
                        <td className="mono-cell timestamp-cell">{formatTimestamp(action.executed_at)}</td>
                        <td>
                          <span className={getOutcomeBadgeClass(action.outcome)}>
                            <OutcomeIcon size={12} />
                            {OUTCOME_LABELS[action.outcome] || action.outcome}
                          </span>
                        </td>
                        <td className={action.customer_declined ? 'text-red mono-cell' : 'mono-cell text-muted'}>
                          {action.customer_declined ? 'Declined' : '—'}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {filteredActions.length > 0 && (
            <div className="pagination">
              <div className="page-info">
                Showing {(currentPage - 1) * pageSize + 1} to{' '}
                {Math.min(currentPage * pageSize, filteredActions.length)} of{' '}
                {filteredActions.length} recovery actions
              </div>
              <div className="page-actions">
                <button
                  className="btn btn-secondary"
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

      {/* Recovery breakdown */}
      <ScrollFade className="animate-scroll-fade" style={{ '--index': 3 }}>
        {metrics && (metrics.by_failure_code || metrics.by_payment_method) && (
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title-group">
                <TrendingUp size={18} />
                <span className="panel-title">Recovery Breakdown</span>
              </div>
            </div>
            <div className="breakdown-list">
              {metrics.by_failure_code && Object.keys(metrics.by_failure_code).length > 0 && (
                <div className="breakdown-group">
                  <div className="breakdown-group-header">
                    <span className="breakdown-group-label">By Failure Code</span>
                  </div>
                  {Object.entries(metrics.by_failure_code).map(([code, count]) => (
                    <div className="breakdown-row" key={code}>
                      <div className="breakdown-main">
                        <span className="reason-code">{code || 'unknown'}</span>
                      </div>
                      <div className="breakdown-meta">
                        <span className="breakdown-count">{count}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {metrics.by_payment_method && Object.keys(metrics.by_payment_method).length > 0 && (
                <div className="breakdown-group">
                  <div className="breakdown-group-header">
                    <span className="breakdown-group-label">By Payment Method</span>
                  </div>
                  {Object.entries(metrics.by_payment_method).map(([method, count]) => (
                    <div className="breakdown-row" key={method}>
                      <div className="breakdown-main">
                        <span className="reason-code">{method || 'unknown'}</span>
                      </div>
                      <div className="breakdown-meta">
                        <span className="breakdown-count">{count}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </ScrollFade>
    </div>
  );
};

export default RecoveryView;
