import { motion } from 'framer-motion';
import {
  RefreshCw,
  Users,
  Clock,
  Hash,
  CheckCircle,
  Settings,
  Zap,
  Target,
} from 'lucide-react';
import { useSimulation, useSimulationRun, useParallelExperiment, useParallelResults } from '../hooks/useApi';
import { useSimulationTimeline } from '../components/charts/RecoveryTimeline';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { StatusDot } from '../components/ui/StatusDot';
import { Shimmer } from '../components/ui/Shimmer';
import { StatusBadge } from '../components/shared/MetricCard';
import type { TimelineEvent } from '../components/charts/RecoveryTimeline';
import type { ParallelExperimentResult } from '../lib/types';

const SIM_PHASES = [
  { id: 'initialization', label: 'Initialization', description: 'Loading people and payment profiles' },
  { id: 'baseline', label: 'Baseline Engine', description: 'Running vanilla retry logic' },
  { id: 'smart', label: 'SARA Engine', description: 'Running smart recovery agent' },
  { id: 'comparison', label: 'Comparison', description: 'Computing lift metrics' },
  { id: 'finalization', label: 'Finalization', description: 'Storing results and reports' },
];

export default function Simulation() {
  const { data: simState, loading, refetch } = useSimulation(2000);
  const { data: parallelResults } = useParallelResults();
  const { run: startSim, loading: startLoading } = useSimulationRun();
  const { run: runParallel, loading: parallelLoading } = useParallelExperiment();

  const latestExperiment = parallelResults?.[0] ?? null;
  const timelineEvents = simState ? useSimulationTimeline({
    current_phase: simState.current_phase,
    events: simState.events,
  }) : [];

  const handleStart = async () => {
    try {
      await startSim({ people_count: 100, hours: 8760, seed: 42 });
      refetch();
    } catch (err) {
      // Error handled by hook
    }
  };

  const handleParallel = async () => {
    try {
      await runParallel({ people_count: 100, hours: 8760, seed: 42 });
      refetch();
    } catch (err) {
      // Error handled by hook
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-8"
    >
      {/* ── Header ── */}
      <HeaderSection
        simStatus={simState?.status || 'IDLE'}
      />

      {/* ── Controls ── */}
      <ControlsSection
        onStart={handleStart}
        onParallel={handleParallel}
        startLoading={startLoading}
        parallelLoading={parallelLoading}
        status={simState?.status || 'IDLE'}
      />

      {/* ── Phase Tracker ── */}
      <PhaseTracker
        currentPhase={simState?.current_phase || ''}
        status={simState?.status || 'IDLE'}
        events={timelineEvents}
        loading={loading}
      />

      {/* ── Run Results ── */}
      <ResultsSection experiment={latestExperiment} loading={parallelLoading} />
    </motion.div>
  );
}

// ─── Header ───────────────────────────────────────

function HeaderSection({
  simStatus,
}: {
  simStatus: string;
}) {

  return (
    <motion.div
      className="flex items-center justify-between"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div>
        <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
          Simulation Runner
        </h1>
        <p className="mt-1 text-sm text-tertiary">
          Configure population, duration, and engine parameters.
        </p>
      </div>

      <StatusBadge status={simStatus} />
    </motion.div>
  );
}

// ─── Controls ─────────────────────────────────────

function ControlsSection({
  onStart,
  onParallel,
  startLoading,
  parallelLoading,
  status,
}: {
  onStart: () => void;
  onParallel: () => void;
  startLoading: boolean;
  parallelLoading: boolean;
  status: string;
}) {
  const isRunning = status === 'RUNNING';

  return (
    <motion.div
      className="grid gap-6 md:grid-cols-[300px_1fr]"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, duration: 0.4 }}
    >
      {/* Controls panel */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Settings size={14} />}>Engine Parameters</CardTitle>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-tertiary">
              Population
            </label>
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-tertiary" />
              <input
                type="number"
                defaultValue={100}
                min={1}
                max={10000}
                className="w-20 rounded-lg border border-border-subtle bg-elevated px-2 py-1 font-mono text-sm text-primary focus:border-chartreuse focus:outline-none"
              />
              <span className="text-xs text-tertiary">people</span>
            </div>
            <p className="text-xs text-tertiary">
              Number of simulated customers in the population.
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-tertiary">
              Duration
            </label>
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-tertiary" />
              <input
                type="number"
                defaultValue={8760}
                min={1}
                max={87600}
                className="w-20 rounded-lg border border-border-subtle bg-elevated px-2 py-1 font-mono text-sm text-primary focus:border-chartreuse focus:outline-none"
              />
              <span className="text-xs text-tertiary">hours (≈ 1 year)</span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium uppercase tracking-wider text-tertiary">
              Random Seed
            </label>
            <div className="flex items-center gap-2">
              <Hash className="h-4 w-4 text-tertiary" />
              <input
                type="number"
                defaultValue={42}
                min={0}
                className="w-20 rounded-lg border border-border-subtle bg-elevated px-2 py-1 font-mono text-sm text-primary focus:border-chartreuse focus:outline-none"
              />
            </div>
          </div>

          <div className="pt-2 border-t border-border-subtle">
            <Button
              variant="chartreuse"
              size="lg"
              className="w-full"
              icon={startLoading ? undefined : <Zap size={18} />}
              isLoading={startLoading || isRunning}
              onClick={onStart}
              disabled={isRunning || startLoading}
            >
              {startLoading ? 'Starting…' : isRunning ? 'Running…' : 'Run Simulation'}
            </Button>

            <Button
              variant="outline"
              size="lg"
              className="mt-3 w-full"
              icon={parallelLoading ? undefined : <Target size={18} />}
              isLoading={parallelLoading}
              onClick={onParallel}
              disabled={parallelLoading || isRunning}
            >
              {parallelLoading ? 'Running Experiment…' : 'Run Parallel Experiment'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Status panel */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Zap size={14} />}>Live Status</CardTitle>
        </CardHeader>

        <CardContent>
          <div className="text-center py-12">
            <motion.div
              animate={{ scale: [1, 1.05, 1] }}
              transition={{ duration: 2, repeat: Infinity }}
            >
              <StatusDot variant="online" pulse={isRunning} size="lg" label={status} />
            </motion.div>
            <p className="mt-2 text-xs text-tertiary">
              {isRunning
                ? 'Simulation in progress. This may take a few moments.'
                : 'No active simulation.'}
            </p>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// ─── Phase Tracker ─────────────────────────────────

function PhaseTracker({
  currentPhase,
  status,
  events: _events,
  loading,
}: {
  currentPhase: string;
  status: string;
  events: TimelineEvent[];
  loading: boolean;
}) {
  const currentPhaseIndex = SIM_PHASES.findIndex((p) => p.id === currentPhase);
  const isRunning = status === 'RUNNING';

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Lifecycle Phases
      </h2>

      {loading ? (
        <Shimmer className="h-24 w-full rounded-xl" />
      ) : (
        <div className="rounded-xl border border-border-subtle bg-panel p-4">
          <div className="space-y-4">
            {SIM_PHASES.map((phase, index) => {
              const isComplete = index < currentPhaseIndex;
              const isCurrent = index === currentPhaseIndex;

              return (
                <motion.div
                  key={phase.id}
                  className="flex items-center gap-4"
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                >
                  <motion.div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2"
                    style={{
                      backgroundColor: isComplete
                        ? 'var(--chartreuse)'
                        : isCurrent
                          ? 'var(--bg-canvas)'
                          : 'var(--bg-canvas)',
                      borderColor: isComplete
                        ? 'var(--chartreuse)'
                        : isCurrent
                          ? 'var(--chartreuse)'
                          : 'var(--border-subtle)',
                      color: isComplete
                        ? 'var(--bg-canvas)'
                        : isCurrent
                          ? 'var(--chartreuse)'
                          : 'var(--tertiary)',
                    }}
                    animate={{
                      scale: isCurrent && isRunning ? [1, 1.1, 1] : 1,
                    }}
                    transition={{ duration: 1, repeat: isRunning ? Infinity : 0 }}
                  >
                    {isComplete ? (
                      <CheckCircle className="h-4 w-4" />
                    ) : (
                      <span className="text-xs font-bold">{index + 1}</span>
                    )}
                  </motion.div>

                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-sm font-medium ${
                          isComplete ? 'text-primary' : isCurrent ? 'text-chartreuse' : 'text-tertiary'
                        }`}
                      >
                        {phase.label}
                      </span>
                      {isCurrent && isRunning && (
                        <motion.span
                          className="inline-block h-1.5 w-1.5 rounded-full bg-chartreuse"
                          animate={{ opacity: [1, 0.3, 1] }}
                          transition={{ duration: 1, repeat: Infinity }}
                        />
                      )}
                    </div>
                    <p className="text-xs text-tertiary">{phase.description}</p>
                  </div>

                  {isCurrent && (
                    <motion.div
                      className="text-xs font-mono text-chartreuse"
                      initial={{ width: 0 }}
                      animate={{ width: 'auto' }}
                    >
                      active
                    </motion.div>
                  )}
                </motion.div>
              );
            })}
          </div>
        </div>
      )}
    </motion.section>
  );
}

// ─── Results Section ─────────────────────────────────

function ResultsSection({
  experiment,
  loading,
}: {
  experiment: ParallelExperimentResult | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, duration: 0.4 }}
      >
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Latest Result
        </h2>
        <Shimmer className="h-64 w-full rounded-2xl" />
      </motion.section>
    );
  }

  if (!experiment) {
    return (
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, duration: 0.4 }}
      >
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Latest Result
        </h2>
        <Card>
          <CardContent className="py-12 text-center">
            <RefreshCw className="mx-auto mb-3 h-6 w-6 text-tertiary opacity-40" />
            <p className="text-sm text-tertiary">
              Run a simulation to see results here.
            </p>
          </CardContent>
        </Card>
      </motion.section>
    );
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.4 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Latest Result
      </h2>

      <div className="rounded-2xl border border-border-subtle bg-panel p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-primary">
            Experiment #{experiment.experiment_id || 'N/A'}
          </h3>
        </div>
        <p className="text-sm text-tertiary">{experiment.notes}</p>
      </div>
    </motion.section>
  );
}
