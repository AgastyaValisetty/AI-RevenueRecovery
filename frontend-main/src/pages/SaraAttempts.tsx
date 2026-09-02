import { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  RefreshCw,
  Target,
  Activity,
  CheckCircle,
  XCircle,
  PauseCircle,
  AlertOctagon,
  TrendingUp,
  Clock,
} from 'lucide-react';
import { useRecoveryMetrics, useRecoveryActions } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, CountValue } from '../components/shared/MetricCard';
import { formatCurrency, formatDateTime } from '../lib/utils';
import type { RecoveryAction, RecoveryMetrics } from '../lib/types';

const OUTCOME_LABELS: Record<string, string> = {
  PENDING: 'Pending',
  SUCCESS: 'Success',
  FAILED: 'Failed',
  STOPPED: 'Stopped',
  UNKNOWN: 'Unknown',
};

const OUTCOME_BADGE: Record<string, 'success' | 'error' | 'warning' | 'default'> = {
  PENDING: 'default',
  SUCCESS: 'success',
  FAILED: 'error',
  STOPPED: 'warning',
  UNKNOWN: 'default',
};

export default function SaraAttempts() {
  const { data: metricsData, loading: metricsLoading, refetch: refetchMetrics } = useRecoveryMetrics({
    engine_type: 'AI_AGENT',
  });
  const { data: actionsData, loading: actionsLoading, refetch: refetchActions } = useRecoveryActions({
    action_type: 'RETRY',
    engine_type: 'AI_AGENT',
    limit: 5000,
  });

  const loading = metricsLoading || actionsLoading;
  const attempts = actionsData?.actions ?? [];

  const refetch = () => {
    refetchMetrics();
    refetchActions();
  };

  // Recovery rate: successful_recoveries / total_retries_attempted * 100
  const recoveryRatePct = useMemo(() => {
    const total = metricsData?.total_retries_attempted ?? 0;
    const recovered = metricsData?.retries_successful ?? 0;
    if (total === 0) return { value: 0, formatted: '0.0%' };
    const pct = (recovered / total) * 100;
    return { value: pct, formatted: `${pct.toFixed(1)}%` };
  }, [metricsData]);

  const summaryCards = metricsData
    ? [
        {
          title: 'Total Actions',
          value: <CountValue value={metricsData.total_recovery_actions} size="lg" />,
          desc: 'All recovery actions',
          icon: <Activity size={18} />,
          colorClass: 'text-tertiary',
        },
        {
          title: 'Retries Attempted',
          value: <CountValue value={metricsData.retry_actions} size="lg" />,
          desc: 'Retry actions created',
          icon: <RefreshCw size={18} />,
          colorClass: 'text-chartreuse',
        },
        {
          title: 'Successful',
          value: <CountValue value={metricsData.successful_recoveries} size="lg" />,
          desc: 'Recovered payments',
          icon: <CheckCircle size={18} />,
          colorClass: 'text-success',
        },
        {
          title: 'Failed',
          value: <CountValue value={metricsData.failed_recoveries} size="lg" />,
          desc: 'Retries that failed',
          icon: <XCircle size={18} />,
          colorClass: 'text-error',
        },
        {
          title: 'Stopped',
          value: <CountValue value={metricsData.stopped_recoveries} size="lg" />,
          desc: 'Recovery stopped',
          icon: <PauseCircle size={18} />,
          colorClass: 'text-warning',
        },
        {
          title: 'Recovered GMV',
          value: <CurrencyValue amount={metricsData.total_recovered_gmv} size="lg" />,
          desc: `Recovery rate: ${recoveryRatePct.formatted}`,
          icon: <TrendingUp size={18} />,
          colorClass: 'text-money',
        },
      ]
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-6"
    >
      {/* ── Header ── */}
      <motion.div
        className="flex items-center justify-between"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
            SARA Attempts Ledger
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Lifetime recovery retry data — total actions, retries, outcomes, and recovered GMV
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={() => refetch()}>
          Refresh
        </Button>
      </motion.div>

      {/* ── Summary Cards ── */}
      {metricsLoading ? (
        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <Shimmer key={i} className="h-24 rounded-xl" />
          ))}
        </motion.div>
      ) : !metricsData?.recovery_enabled ? (
        <div className="rounded-xl border border-border-subtle bg-panel p-8 text-center">
          <AlertOctagon className="mx-auto mb-3 h-6 w-6 text-tertiary" />
          <p className="text-sm text-tertiary">
            Recovery system is not enabled. Run a simulation to generate recovery data.
          </p>
        </div>
      ) : (
        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          {summaryCards.map((card) => (
            <Card key={card.title}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                      {card.title}
                    </p>
                    <div className="mt-2">{card.value}</div>
                    <p className="mt-1 text-xs text-tertiary">{card.desc}</p>
                  </div>
                  <div
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                    style={{
                      background: 'rgba(201, 243, 91, 0.05)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {card.icon}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </motion.div>
      )}

      {/* ── SARA Retry Ledger ── */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Target size={14} />}>
            SARA Retry Ledger ({attempts.length} retries)
          </CardTitle>
          <div className="mt-2 flex items-center gap-4 text-xs text-tertiary">
            <span>Showing lifetime RETRY actions</span>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            columns={[
              {
                key: 'retry_number',
                header: 'Retry #',
                sortable: true,
                render: (row: RecoveryAction) => (
                  <span className="font-mono text-xs text-tertiary">
                    {row.retry_number ?? '—'}
                  </span>
                ),
              },
              {
                key: 'failure_code',
                header: 'Failure Code',
                sortable: true,
                render: (row: RecoveryAction) => (
                  <span className="font-mono text-xs text-tertiary">
                    {row.failure_code || '—'}
                  </span>
                ),
              },
              {
                key: 'failure_reason',
                header: 'Failure Reason',
                render: (row: RecoveryAction) => (
                  <span className="text-sm text-secondary max-w-xs truncate block">
                    {row.failure_reason || '—'}
                  </span>
                ),
              },
              {
                key: 'amount',
                header: 'Amount',
                sortable: true,
                render: (row: RecoveryAction) => (
                  <span className="font-mono text-sm text-primary">
                    {row.amount ? formatCurrency(parseFloat(row.amount)) : '—'}
                  </span>
                ),
              },
              {
                key: 'scheduled_for',
                header: 'Scheduled',
                sortable: true,
                render: (row: RecoveryAction) => (
                  <span className="font-mono text-xs text-tertiary">
                    {formatDateTime(row.scheduled_for)}
                  </span>
                ),
              },
              {
                key: 'executed_at',
                header: 'Executed',
                sortable: true,
                render: (row: RecoveryAction) => (
                  <span className="font-mono text-xs text-tertiary">
                    {formatDateTime(row.executed_at)}
                  </span>
                ),
              },
              {
                key: 'outcome',
                header: 'Outcome',
                render: (row: RecoveryAction) => {
                  const outcome = row.outcome || 'UNKNOWN';
                  const Icon =
                    outcome === 'SUCCESS'
                      ? CheckCircle
                      : outcome === 'FAILED'
                        ? XCircle
                        : outcome === 'STOPPED'
                          ? PauseCircle
                          : outcome === 'PENDING'
                            ? Clock
                            : AlertOctagon;
                  return (
                    <Badge variant={OUTCOME_BADGE[outcome]} size="sm">
                      <div className="flex items-center gap-1">
                        <Icon size={12} />
                        {OUTCOME_LABELS[outcome] || outcome}
                      </div>
                    </Badge>
                  );
                },
              },
              {
                key: 'customer_declined',
                header: 'Customer Declined',
                render: (row: RecoveryAction) => (
                  <span
                    className={
                      row.customer_declined
                        ? 'font-mono text-xs text-error'
                        : 'font-mono text-xs text-tertiary'
                    }
                  >
                    {row.customer_declined ? 'Yes' : 'No'}
                  </span>
                ),
              },
            ]}
            data={attempts}
            loading={loading}
            pagination={true}
            pageSize={25}
            emptyMessage="No SARA retry attempts found"
            searchable={true}
            searchPlaceholder="Search failure code, reason, or amount…"
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}
