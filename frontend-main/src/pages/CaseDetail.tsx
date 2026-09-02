import { motion } from 'framer-motion';
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  RefreshCw,
  Brain,
  Shield,
  Calendar,
  Play,
  CheckCircle,
  XCircle,
  AlertCircle,
  Clock,
  DollarSign,
  CreditCard,
  Hash,
  Target,
} from 'lucide-react';
import { useCaseDetail, useCounterfactualRun } from '../hooks/useApi';
import { RecoveryTimeline, useCaseTimeline } from '../components/charts/RecoveryTimeline';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { StatusDot } from '../components/ui/StatusDot';
import { Shimmer } from '../components/ui/Shimmer';
import { StatusBadge } from '../components/shared/MetricCard';
import { formatCurrency, formatDateTime } from '../lib/utils';
import type { SmartCase } from '../lib/types';
import type { TimelineEvent } from '../components/charts/RecoveryTimeline';

interface CounterfactualResult {
  original_outcome: string;
  counterfactual_outcome: string;
  counterfactual_recovery: number;
  explanation: string;
  action_sequence: Array<{
    action_type: string;
    scheduled_for: string;
    outcome: string;
    reason: string;
  }>;
}

export default function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const { data: caseData, loading, error, refetch } = useCaseDetail(caseId || '');
  const { run: runCounterfactual, loading: counterfactualLoading } = useCounterfactualRun();
  const [counterfactual, setCounterfactual] = useState<CounterfactualResult | null>(null);

  if (!caseId) {
    return <div>Invalid case ID</div>;
  }

  if (loading) {
    return <CaseDetailSkeleton />;
  }

  if (!caseData) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="text-center">
          <AlertCircle className="mx-auto mb-2 h-6 w-6 text-error" />
          <p className="text-sm text-tertiary">
            Failed to load case: {error}
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={refetch}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const timelineEvents = useCaseTimeline(caseData);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      className="space-y-6"
    >
      {/* ── Header ── */}
      <HeaderSection smartCase={caseData} onBack={() => navigate('/cases')} onRefetch={refetch} />

      {/* ── Layout: Grid ── */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Left column: Case detail + policy gate */}
        <div className="space-y-6 xl:col-span-2">
          {/* ── Case Overview ── */}
          <CaseOverviewSection smartCase={caseData} />

          {/* ── Policy Gate ── */}
          <PolicyGateSection smartCase={caseData} />

          {/* ── Diagnosis ── */}
          <DiagnosisSection smartCase={caseData} />

          {/* ── Timeline ── */}
          <TimelineSection events={timelineEvents} smartCase={caseData} />
        </div>

        {/* Right column: Counterfactual */}
        <div className="space-y-6">
          <CounterfactualSection
            smartCase={caseData}
            counterfactual={counterfactual}
            loading={counterfactualLoading}
            onRun={() => {
              runCounterfactual(caseId).then((result) => {
                setCounterfactual(result as CounterfactualResult);
              });
            }}
          />
        </div>
      </div>
    </motion.div>
  );
}

// ─── Header ────────────────────────────────────────

function HeaderSection({
  smartCase,
  onBack,
  onRefetch,
}: {
  smartCase: SmartCase;
  onBack: () => void;
  onRefetch: () => void;
}) {
  return (
    <motion.div
      className="flex items-center justify-between"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-tertiary transition-colors hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Back to Dispatch Board</span>
      </button>

      <div className="flex items-center gap-3">
        <StatusBadge status={smartCase.status} />
        <Button
          variant="outline"
          size="sm"
          icon={<RefreshCw size={14} />}
          onClick={onRefetch}
        >
          Refresh
        </Button>
      </div>
    </motion.div>
  );
}

// ─── Case Overview ─────────────────────────────────

function CaseOverviewSection({ smartCase: c }: { smartCase: SmartCase }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, duration: 0.4 }}
    >
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-tertiary">
        Case Overview
      </h2>

      <Card className="overflow-hidden">
        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <DetailItem
              icon={<DollarSign size={16} />}
              label="Amount"
              value={formatCurrency(parseFloat(c.amount))}
            />
            <DetailItem
              icon={<CreditCard size={16} />}
              label="Payment Method"
              value={c.payment_method}
            />
            <DetailItem
              icon={<Hash size={16} />}
              label="Retry #"
              value={String(c.retry_number)}
            />
            <DetailItem
              icon={<Calendar size={16} />}
              label="Scheduled"
              value={c.scheduled_for ? formatDateTime(c.scheduled_for) : '—'}
            />
          </div>

          {c.reason && (
            <div className="mt-6 rounded-lg bg-elevated/50 border border-border-subtle p-4">
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Recovery Reasoning
              </p>
              <p className="mt-1.5 text-sm text-secondary">{c.reason}</p>
            </div>
          )}

          {c.failure_code && (
            <div className="mt-4 flex items-center gap-3">
              <span className="text-xs text-tertiary">Failure:</span>
              <Badge variant="error">{c.failure_code}</Badge>
              {c.failure_reason && (
                <span className="text-xs text-tertiary">{c.failure_reason}</span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}

interface DetailItemProps {
  icon: React.ReactNode;
  label: string;
  value: string;
}

function DetailItem({ icon, label, value }: DetailItemProps) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-tertiary">{icon}</span>
        <span className="text-xs text-tertiary">{label}</span>
      </div>
      <p className="mt-1 font-mono text-sm text-primary">{value}</p>
    </div>
  );
}

// ─── Policy Gate ──────────────────────────────────

function PolicyGateSection({ smartCase: c }: { smartCase: SmartCase }) {
  if (!c.decision) return null;

  const { decision, policy_checks, confidence, reason } = c.decision;
  const passedCount = policy_checks.filter((pc) => pc.passed).length;
  const totalCount = policy_checks.length;
  const gatePassed = passedCount === totalCount;

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15, duration: 0.4 }}
    >
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-tertiary">
        Policy Gate
      </h2>

      <Card className="overflow-hidden">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle icon={<Shield size={14} />}>
              Policy Decision: {decision}
            </CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-tertiary">
                Confidence: {(confidence * 100).toFixed(0)}%
              </span>
              {gatePassed ? (
                <StatusDot variant="success" label="Passed" />
              ) : (
                <StatusDot variant="error" label="Failed" />
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent>
          {reason && (
            <p className="mb-4 text-sm text-tertiary">{reason}</p>
          )}

          <div className="space-y-3">
            {policy_checks.map((check, i) => (
              <motion.div
                key={check.name}
                className="flex items-center justify-between rounded-lg border border-border-subtle bg-elevated/30 px-4 py-2.5"
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 + 0.2 }}
              >
                <div className="flex items-center gap-2.5">
                  {check.passed ? (
                    <CheckCircle className="h-4 w-4 text-success" />
                  ) : (
                    <XCircle className="h-4 w-4 text-error" />
                  )}
                  <span className="text-sm font-medium text-primary">
                    {check.name}
                  </span>
                </div>
                <span className="text-xs text-tertiary max-w-xs text-right">
                  {check.detail}
                </span>
              </motion.div>
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.section>
  );
}

// ─── Diagnosis ────────────────────────────────────

function DiagnosisSection({ smartCase: c }: { smartCase: SmartCase }) {
  if (!c.diagnosis) return null;

  const { root_cause, confidence, explanation, hypotheses } = c.diagnosis;

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4 }}
    >
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-tertiary">
        Diagnosis
      </h2>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle icon={<Brain size={14} />}>Root Cause Analysis</CardTitle>
        </CardHeader>

        <CardContent className="space-y-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
              Root Cause
            </p>
            <p className="mt-1.5 text-sm font-medium text-primary">{root_cause}</p>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Confidence
              </p>
              <div className="mt-1 h-2 w-full max-w-24 rounded-full bg-border-subtle">
                <div
                  className="h-2 rounded-full bg-chartreuse"
                  style={{ width: `${Math.min(confidence, 1) * 100}%` }}
                />
              </div>
              <span className="text-xs font-mono text-chartreuse">
                {(confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          {explanation && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Explanation
              </p>
              <p className="mt-1.5 text-sm text-secondary">{explanation}</p>
            </div>
          )}

          {hypotheses && hypotheses.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Hypotheses
              </p>
              <div className="mt-2 space-y-2">
                {hypotheses.map((h, i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-border-subtle bg-elevated/20 px-3 py-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-primary">
                        {h.hypothesis}
                      </span>
                      <Badge variant="outline" size="sm">
                        {(h.likelihood * 100).toFixed(0)}%
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-tertiary">{h.evidence}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}

// ─── Timeline ──────────────────────────────────────

function TimelineSection({
  events,
  smartCase: _c,
}: {
  events: TimelineEvent[];
  smartCase: SmartCase;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.25, duration: 0.4 }}
    >
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-tertiary">
        Audit Trail
      </h2>

      <Card>
        <CardContent className="p-4">
          {events.length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <Clock className="mx-auto mb-2 h-5 w-5 opacity-40" />
              <p className="text-sm">No events recorded.</p>
            </div>
          ) : (
            <RecoveryTimeline events={events} height={320} />
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}

// ─── Counterfactual ─────────────────────────────────

function CounterfactualSection({
  smartCase: _,
  counterfactual,
  loading,
  onRun,
}: {
  smartCase: SmartCase;
  counterfactual: CounterfactualResult | null;
  loading: boolean;
  onRun: () => void;
}) {
  const hasRun = counterfactual !== null;

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15, duration: 0.4 }}
    >
      <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-tertiary">
        Counterfactual Explorer
      </h2>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle icon={<Target size={14} />}>
            What if SARA had chosen differently?
          </CardTitle>
        </CardHeader>

        <CardContent>
          {!hasRun && (
            <div className="py-6 text-center">
              <Target className="mx-auto mb-3 h-8 w-8 text-tertiary opacity-50" />
              <p className="mb-4 max-w-sm text-center text-sm text-tertiary">
                Simulate an alternative action sequence for this case and
                compare outcomes side by side.
              </p>
              <Button
                variant="chartreuse"
                size="md"
                icon={loading ? undefined : <Play size={16} />}
                isLoading={loading}
                onClick={onRun}
              >
                {loading ? 'Simulating…' : 'Run Counterfactual'}
              </Button>
            </div>
          )}

          {hasRun && counterfactual && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
              className="space-y-4"
            >
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg border border-border-subtle bg-elevated/30 p-4 text-center">
                  <p className="text-xs text-tertiary uppercase">
                    Original Outcome
                  </p>
                  <p className="mt-1 text-sm font-medium text-primary">
                    {counterfactual.original_outcome}
                  </p>
                </div>
                <div className="rounded-lg border border-chartreuse-border bg-chartreuse-bg/30 p-4 text-center">
                  <p className="text-xs text-tertiary uppercase">
                    Counterfactual Outcome
                  </p>
                  <p className="mt-1 text-sm font-medium text-chartreuse">
                    {counterfactual.counterfactual_outcome}
                  </p>
                  <p className="mt-1 font-mono text-xs text-money">
                    {formatCurrency(counterfactual.counterfactual_recovery)}
                  </p>
                </div>
              </div>

              {counterfactual.explanation && (
                <p className="text-sm text-tertiary">
                  {counterfactual.explanation}
                </p>
              )}

              <Button
                variant="outline"
                size="sm"
                icon={<RefreshCw size={14} />}
                onClick={onRun}
                disabled={loading}
              >
                Re-simulate
              </Button>
            </motion.div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}

// ─── Skeleton ──────────────────────────────────────

function CaseDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Shimmer className="h-5 w-40 rounded" />
        <div className="flex gap-3">
          <Shimmer className="h-6 w-20 rounded-full" />
          <Shimmer className="h-8 w-24 rounded-full" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Shimmer className="h-48 rounded-xl" />
          <Shimmer className="h-40 rounded-xl" />
          <Shimmer className="h-40 rounded-xl" />
          <Shimmer className="h-64 rounded-xl" />
        </div>
        <div>
          <Shimmer className="h-64 rounded-xl" />
        </div>
      </div>
    </div>
  );
}
