import { motion } from 'framer-motion';
import { useMemo } from 'react';
import {
  RefreshCw,
  Target,
  BarChart3,
  ArrowUpRight,
} from 'lucide-react';
import { useParallelResults } from '../hooks/useApi';
import { RecoveryCurve, RecoveryRing } from '../components/charts/RecoveryCurve';
import { StatusBadge } from '../components/shared/MetricCard';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Shimmer } from '../components/ui/Shimmer';
import { formatCurrencyCompact, formatDuration, calculateRecoveryRate } from '../lib/utils';
import type { ParallelExperimentResult, RunMetrics } from '../lib/types';

export default function Comparison() {
  const { data: experiments, loading, refetch } = useParallelResults();
  const latest = experiments?.[0];

  if (loading) {
    return (
      <div className="space-y-8">
        <Shimmer className="h-8 w-48" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Shimmer key={i} className="h-32 rounded-xl" />
          ))}
        </div>
        <Shimmer className="h-[360px] w-full rounded-2xl" />
      </div>
    );
  }

  if (!latest) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <div className="text-center">
          <BarChart3 className="mx-auto mb-4 h-12 w-12 text-tertiary opacity-40" />
          <p className="text-tertiary">No experiment data available.</p>
          <Button
            variant="chartreuse"
            size="sm"
            className="mt-4"
            onClick={() => refetch()}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-8"
    >
      {/* ── Header ── */}
      <HeaderSection experiment={latest} />

      {/* ── Scoreboard ── */}
      <ScoreboardSection experiment={latest} />

      {/* ── Recovery Curve ── */}
      <RecoveryCurveSection experiment={latest} />

      {/* ── Breakdown ── */}
      <BreakdownSection experiment={latest} />

      {/* ── Notes ── */}
      <NotesSection experiment={latest} />
    </motion.div>
  );
}

function HeaderSection({ experiment }: { experiment: ParallelExperimentResult }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
          Recovery Comparison
        </h1>
        <p className="mt-1 text-sm text-tertiary">
          Experiment #{experiment.experiment_id} · Seed {experiment.seed} ·
          {experiment.people_count.toLocaleString()} people · {experiment.hours / 1000}k hours
        </p>
      </div>
      <div className="flex items-center gap-3">
        <StatusBadge status={experiment.baseline ? 'COMPLETED' : 'IDLE'} />
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />} onClick={() => {}}>
          Refresh
        </Button>
      </div>
    </div>
  );
}

function ScoreboardSection({ experiment }: { experiment: ParallelExperimentResult }) {
  const baseline = experiment.baseline;
  const smart = experiment.smart;

  const cards = [
    {
      name: 'BASELINE',
      metrics: baseline,
      color: 'text-tertiary' as const,
      ringColor: '#9CA3A0',
    },
    {
      name: 'SARA',
      metrics: smart,
      color: 'text-chartreuse' as const,
      ringColor: '#C9F35B',
    },
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {cards.map((card) => (
        <ScoreboardCard
          key={card.name}
          name={card.name}
          metrics={card.metrics}
          colorClass={card.color}
          ringColor={card.ringColor}
        />
      ))}
    </div>
  );
}

interface ScoreboardCardProps {
  name: string;
  metrics: RunMetrics;
  colorClass: string;
  ringColor: string;
}

function ScoreboardCard({ name, metrics, colorClass, ringColor }: ScoreboardCardProps) {
  const recoveryRate = calculateRecoveryRate(metrics.recovered_cases, metrics.total_cases);

  return (
    <motion.div
      className="rounded-2xl border border-border-subtle bg-panel p-6"
      initial={{ opacity: 0, x: name === 'BASELINE' ? -20 : 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
    >
      <div className="mb-6 flex items-center justify-between">
        <h3 className={`text-sm font-medium uppercase tracking-wider ${colorClass}`}>
          {name}
        </h3>
        {name === 'SARA' && (
          <span className="rounded-full bg-chartraise-bg px-2.5 py-0.5 text-xs font-mono text-chartreuse">
            +{metrics.recovered_cases - metrics.total_cases} recovered
          </span>
        )}
      </div>

      <div className="mb-6 flex items-center gap-6">
        <RecoveryRing
          percentage={recoveryRate * 100}
          size={100}
          strokeWidth={6}
          color={ringColor}
          label="Recovery Rate"
        />

        <div className="space-y-4">
          <div>
            <p className="text-xs text-tertiary uppercase tracking-wider">Net Recovered</p>
            <p className="font-mono text-xl font-bold text-money">
              {formatCurrencyCompact(parseFloat(metrics.net_recovered_value))}
            </p>
          </div>
          <div>
            <p className="text-xs text-tertiary uppercase tracking-wider">Total Cost</p>
            <p className="font-mono text-sm text-primary">
              {formatCurrencyCompact(parseFloat(metrics.total_cost), 'INR')}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <StatItem label="Cases" value={metrics.total_cases} />
        <StatItem label="Recovered" value={metrics.recovered_cases} color="text-success" />
        <StatItem label="Retries" value={metrics.total_retries} />
        <StatItem label="Wasted" value={metrics.wasted_retries} color="text-error" />
        <StatItem
          label="Mean TTR"
          value={metrics.mean_time_to_recovery_hours ? formatDuration(metrics.mean_time_to_recovery_hours, true) : '—'}
          colSpan
        />
        <StatItem label="Stops" value={metrics.stop_count} />
      </div>
    </motion.div>
  );
}

interface StatItemProps {
  label: string;
  value: string | number;
  color?: string;
  colSpan?: boolean;
}

function StatItem({ label, value, color = 'text-tertiary' }: StatItemProps) {
  return (
    <div>
      <p className="text-xs text-tertiary uppercase">{label}</p>
      <p className={`font-mono text-sm font-medium ${color}`}>{value}</p>
    </div>
  );
}

function RecoveryCurveSection({ experiment }: { experiment: ParallelExperimentResult }) {
  // Generate synthetic curve data from metrics — in production this would be
  // a time-series of cumulative recovered value per hour
  const curveData = useMemo(() => {
    const hours = experiment.hours;
    const steps = 24;
    const stepHours = hours / steps;

    const baselineFinal = parseFloat(experiment.baseline.net_recovered_value);
    const smartFinal = parseFloat(experiment.smart.net_recovered_value);

    return Array.from({ length: steps + 1 }).map((_, i) => {
      const hour = Math.round(i * stepHours);
      // Simulate exponential recovery curve
      const progress = i / steps;
      const curveFactor = 1 - Math.exp(-5 * progress); // exponential approach

      return {
        hour,
        baseline: baselineFinal * curveFactor,
        smart: smartFinal * curveFactor,
      };
    });
  }, [experiment]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.5 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Cumulative Net Recovery Curve
      </h2>
      <RecoveryCurve
        data={curveData}
        height={320}
        baselineMetrics={experiment.baseline}
        smartMetrics={experiment.smart}
      />
    </motion.div>
  );
}

function BreakdownSection({ experiment }: { experiment: ParallelExperimentResult }) {
  const breakdown = [
    {
      category: 'Recovery Rate',
      baseline: calculateRecoveryRate(
        experiment.baseline.recovered_cases,
        experiment.baseline.total_cases,
      ) * 100,
      smart: calculateRecoveryRate(
        experiment.smart.recovered_cases,
        experiment.smart.total_cases,
      ) * 100,
      delta: experiment.incremental_recovery_rate,
      unit: 'pp',
      positive: true,
    },
    {
      category: 'Wasted Retries',
      baseline: experiment.baseline.wasted_retries,
      smart: experiment.smart.wasted_retries,
      delta: -experiment.wasted_retry_reduction,
      unit: '',
      positive: true,
      inverse: true,
    },
    {
      category: 'Total Retries',
      baseline: experiment.baseline.total_retries,
      smart: experiment.smart.total_retries,
      delta: experiment.smart.total_retries - experiment.baseline.total_retries,
      unit: '',
      positive: false,
    },
    {
      category: 'Action Cost',
      baseline: parseFloat(experiment.baseline.total_cost),
      smart: parseFloat(experiment.smart.total_cost),
      delta: parseFloat(experiment.total_cost_savings),
      unit: 'INR',
      positive: true,
    },
    {
      category: 'Mean Time to Recovery',
      baseline: experiment.baseline.mean_time_to_recovery_hours ?? 0,
      smart: experiment.smart.mean_time_to_recovery_hours ?? 0,
      delta: experiment.time_to_recovery_improvement ?? 0,
      unit: 'h',
      positive: true,
    },
    {
      category: 'Net Recovered Value',
      baseline: parseFloat(experiment.baseline.net_recovered_value),
      smart: parseFloat(experiment.smart.net_recovered_value),
      delta: parseFloat(experiment.incremental_recovered_value),
      unit: 'INR',
      positive: true,
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.5 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Key Metrics Breakdown
      </h2>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {breakdown.map((item) => {
          const isCurrency = item.unit === 'INR';
          const isPercent = item.category === 'Recovery Rate';
          const showArrow = item.delta !== 0;
          const improved = item.inverse ? item.delta < 0 : item.delta > 0;

          return (
            <motion.div
              key={item.category}
              className="rounded-xl border border-border-subtle bg-elevated p-4"
              whileHover={{ borderColor: 'var(--border-strong)' }}
            >
              <p className="text-xs text-tertiary uppercase">{item.category}</p>

              <div className="mt-3 grid grid-cols-3 items-center gap-2">
                <div className="flex flex-col items-center">
                  <span className="text-xs text-tertiary">Baseline</span>
                  <span className="font-mono text-sm text-tertiary">
                    {isCurrency
                      ? formatCurrencyCompact(item.baseline)
                      : isPercent
                        ? item.baseline.toFixed(1) + '%'
                        : item.unit
                          ? Math.round(item.baseline).toLocaleString() + item.unit
                          : Math.round(item.baseline).toLocaleString()}
                  </span>
                </div>

                <div className="flex flex-col items-center">
                  <span className="text-xs text-tertiary">SARA</span>
                  <span className="font-mono text-sm text-chartreuse">
                    {isCurrency
                      ? formatCurrencyCompact(item.smart)
                      : isPercent
                        ? item.smart.toFixed(1) + '%'
                        : item.unit
                          ? Math.round(item.smart).toLocaleString() + item.unit
                          : Math.round(item.smart).toLocaleString()}
                  </span>
                </div>

                <div className="flex flex-col items-center">
                  <span className="text-xs text-tertiary">Δ Lift</span>
                  <span
                    className={`font-mono text-sm ${
                      improved ? 'text-success' : 'text-error'
                    }`}
                  >
                    {showArrow && (
                      <ArrowUpRight
                        className={`inline h-3 w-3 ${improved ? 'text-success' : 'text-error'}`}
                        style={{
                          transform: improved ? 'rotate(0)' : 'rotate(180deg)',
                        }}
                      />
                    )}
                    {isCurrency
                      ? formatCurrencyCompact(Math.abs(item.delta))
                      : item.unit
                        ? Math.abs(item.delta).toFixed(1) + item.unit
                        : Math.abs(item.delta).toLocaleString()}
                  </span>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </motion.div>
  );
}

function NotesSection({ experiment }: { experiment: ParallelExperimentResult }) {
  if (!experiment.notes) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4, duration: 0.5 }}
    >
      <Card>
        <CardHeader>
          <CardTitle icon={<Target size={14} />}>Analysis Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-tertiary">{experiment.notes}</p>
        </CardContent>
      </Card>
    </motion.div>
  );
}
