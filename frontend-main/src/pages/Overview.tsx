import { motion } from 'framer-motion';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Clock,
  ChevronRight,
  RefreshCw,
  BarChart3,
  DollarSign,
  AlertCircle,
} from 'lucide-react';
import { useSimulation, useParallelResults } from '../hooks/useApi';
import { RecoveryField } from '../components/charts/RecoveryField';
import { RecoveryTimeline, useSimulationTimeline } from '../components/charts/RecoveryTimeline';
import { MetricCard, CurrencyValue, PercentValue, CountValue, StatusBadge } from '../components/shared/MetricCard';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Shimmer, SkeletonText } from '../components/ui/Shimmer';
import { formatCurrencyCompact, formatDuration } from '../lib/utils';
import type { SimulationState, ParallelExperimentResult } from '../lib/types';

const container = {
  hidden: { opacity: 0, y: 20 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.5,
      ease: 'easeOut',
      staggerChildren: 0.05,
    },
  },
};

const item = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

export default function Overview() {
  const { data: simState, loading: simLoading } = useSimulation(3000);
  const { data: parallelResults, loading: parallelLoading } = useParallelResults();

  const latestExperiment = parallelResults?.[0] ?? null;

  // Build timeline events from simulation state
  const timelineEvents = useMemo(() => {
    if (!simState) return [];
    return useSimulationTimeline({
      current_phase: simState.current_phase,
      events: simState.events,
    });
  }, [simState]);

  return (
    <motion.div
      variants={container}
      initial="hidden"
      animate="show"
      className="space-y-8"
    >
      {/* ── Hero Section ─────────────────────────── */}
      <motion.section variants={item}>
        <HeroSection
          simState={simState}
          simLoading={simLoading}
          latestExperiment={latestExperiment}
        />
      </motion.section>

      {/* ── Proof Metrics ────────────────────────── */}
      <motion.section variants={item}>
        <ProofMetricsSection
          experiment={latestExperiment}
          loading={parallelLoading}
        />
      </motion.section>

      {/* ── Recovery Field ───────────────────────── */}
      <motion.section variants={item}>
        <RecoveryFieldSection experiment={latestExperiment} loading={parallelLoading} />
      </motion.section>

      {/* ── Timeline ─────────────────────────────── */}
      <motion.section variants={item}>
        <TimelineSection
          events={timelineEvents}
          simLoading={simLoading}
        />
      </motion.section>
    </motion.div>
  );
}

// ─── Hero Section ──────────────────────────────────

function HeroSection({
  simState,
  simLoading,
  latestExperiment,
}: {
  simState: SimulationState | null;
  simLoading: boolean;
  latestExperiment: ParallelExperimentResult | null;
}) {
  const isRunning = simState?.status === 'RUNNING';

  // Main value: either from latest experiment or simulated live
  const netRecovered = latestExperiment
    ? formatCurrencyCompact(latestExperiment.smart?.net_recovered_value)
    : isRunning
      ? formatCurrencyCompact(simState?.events?.[simState.events.length - 1]?.message || '0')
      : '—';

  const recoveryRate = latestExperiment
    ? (latestExperiment.smart.recovered_cases / latestExperiment.smart.total_cases) * 100
    : 0;

  return (
    <div className="relative overflow-hidden rounded-3xl border border-border-subtle bg-elevated">
      <div className="absolute inset-0 bg-gradient-to-b from-chartreuse-bg/5 via-transparent to-transparent" />

      <div className="relative px-8 py-12 md:px-12 md:py-16">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-mono uppercase tracking-widest text-tertiary">
              Net Recovered Value
            </p>
            {simLoading && !latestExperiment ? (
              <Shimmer className="h-12 w-64" />
            ) : (
              <motion.h1
                className="mt-2 font-display text-5xl font-bold text-chartreuse tracking-tighter md:text-6xl"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
              >
                {netRecovered}
              </motion.h1>
            )}
            <p className="mt-3 text-sm text-tertiary">
              {recoveryRate > 0
                ? `${recoveryRate.toFixed(1)}% recovery rate · ${latestExperiment?.incremental_recovery_rate.toFixed(1)} pp lift over baseline`
                : 'SARA — Simulated AI Recovery Agent'}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <StatusBadge status={simState?.status || 'IDLE'} />
            <Button
              variant="outline"
              size="sm"
              icon={<RefreshCw size={14} />}
              onClick={() => window.location.reload()}
            >
              Refresh
            </Button>
          </div>
        </div>

        {/* Subtle decorative grid */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `
              linear-gradient(to right, var(--chartreuse) 1px, transparent 1px),
              linear-gradient(to bottom, var(--chartreuse) 1px, transparent 1px)
            `,
            backgroundSize: '40px 40px',
          }}
        />
      </div>
    </div>
  );
}

// ─── Proof Metrics Section ────────────────────────

function ProofMetricsSection({
  experiment,
  loading,
}: {
  experiment: ParallelExperimentResult | null;
  loading: boolean;
}) {
  const navigate = useNavigate();

  const cards = [
    {
      title: 'Recovery Rate',
      icon: <BarChart3 size={20} />,
      value: experiment ? (
        <PercentValue
          value={(experiment.smart.recovered_cases / experiment.smart.total_cases) * 100}
          delta
        />
      ) : (
        <span className="text-tertiary">—</span>
      ),
      delta: experiment
        ? `${experiment.incremental_recovery_rate.toFixed(1)} pp`
        : undefined,
      color: 'chartreuse' as const,
    },
    {
      title: 'Incremental Value',
      icon: <DollarSign size={20} />,
      value: experiment ? (
        <CurrencyValue amount={parseFloat(experiment.incremental_recovered_value)} size="xl" />
      ) : (
        <span className="text-tertiary">—</span>
      ),
      delta: experiment ? `+${experiment.notes.match(/(\d+\.\d+)%/i)?.[0] || ''}` : undefined,
      color: 'money' as const,
    },
    {
      title: 'Wasted Retries Saved',
      icon: <RefreshCw size={20} />,
      value: experiment ? (
        <CountValue value={experiment.wasted_retry_reduction} prefix="−" size="xl" />
      ) : (
        <span className="text-tertiary">—</span>
      ),
      delta: experiment
        ? `${experiment.smart.wasted_retries} wasted`
        : undefined,
      color: 'chartreuse' as const,
    },
    {
      title: 'Recovery Time',
      icon: <Clock size={20} />,
      value: experiment?.time_to_recovery_improvement ? (
        <span className="font-mono text-3xl font-bold text-primary">
          {formatDuration(experiment.time_to_recovery_improvement, true)}
        </span>
      ) : (
        <span className="text-tertiary">—</span>
      ),
      delta: experiment
        ? `${experiment.baseline.mean_time_to_recovery_hours?.toFixed(1)}h → ${experiment.smart.mean_time_to_recovery_hours?.toFixed(1)}h`
        : undefined,
      color: 'default' as const,
    },
  ];

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Shimmer key={i} className="h-32 rounded-xl">
            <SkeletonText lines={2} className="h-32" />
          </Shimmer>
        ))}
      </div>
    );
  }

  if (!experiment) {
    return (
      <div className="rounded-xl border border-border-subtle bg-panel p-8 text-center">
        <AlertCircle className="mx-auto mb-3 h-6 w-6 text-tertiary" />
        <p className="text-sm text-tertiary">
          No experiment data available. Run a parallel experiment to see recovery metrics.
        </p>
        <Button
          variant="chartreuse"
          size="sm"
          className="mt-4"
          icon={<ChevronRight size={14} />}
          onClick={() => navigate('/simulation')}
        >
          Go to Simulation
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wider text-tertiary">
          Recovery Intelligence
        </h2>
        <button
          type="button"
          onClick={() => navigate('/comparison')}
          className="flex items-center gap-1 text-xs font-mono text-chartreuse hover:text-chartreuse-dim transition-colors"
        >
          View full report <ChevronRight size={12} />
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <MetricCard
            key={card.title}
            title={card.title}
            value={card.value}
            icon={card.icon}
            trend={card.delta ? 'up' : 'none'}
            trendValue={card.delta}
            variant={card.color}
          />
        ))}
      </div>
    </div>
  );
}

// ─── Recovery Field Section ───────────────────────

function RecoveryFieldSection({
  experiment,
  loading,
}: {
  experiment: ParallelExperimentResult | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Shimmer className="h-[320px] w-full rounded-2xl">
        <div className="h-full w-full" />
      </Shimmer>
    );
  }

  if (!experiment) return null;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wider text-tertiary">
          Recovery Field
        </h2>
        <span className="text-xs font-mono text-tertiary">
          {experiment.smart.total_cases} cases · {experiment.smart.recovered_cases} recovered
        </span>
      </div>

      <RecoveryField
        metrics={experiment.smart}
        height={320}
      />
    </div>
  );
}

// ─── Timeline Section ─────────────────────────────

function TimelineSection({
  events,
  simLoading,
}: {
  events: ReturnType<typeof useSimulationTimeline>;
  simLoading: boolean;
}) {
  if (simLoading) {
    return (
      <div>
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Event Stream
        </h2>
        <Shimmer className="h-[280px] w-full rounded-xl">
          <div className="h-[280px] w-full" />
        </Shimmer>
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Event Stream</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="py-8 text-center text-tertiary">
            <RefreshCw className="mx-auto mb-2 h-5 w-5 opacity-40" />
            <p className="text-sm">No events yet. Start a simulation to see the timeline.</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div>
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Event Stream
      </h2>
      <RecoveryTimeline
        events={events}
        height={320}
      />
    </div>
  );
}
