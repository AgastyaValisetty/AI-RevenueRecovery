import { motion } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import {
  User,
  ArrowLeft,
  Shield,
  Banknote,
  Clock,
  CheckCircle,
  BarChart3,
} from 'lucide-react';
import { usePerson, usePersonRecoverySummary } from '../hooks/useApi';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { StatusDot } from '../components/ui/StatusDot';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, PercentValue } from '../components/shared/MetricCard';
import { formatDuration, formatDateTime } from '../lib/utils';
import type { PersonRecoverySummary } from '../lib/types';

export default function PersonDetail() {
  const { personId } = useParams<{ personId: string }>();
  const navigate = useNavigate();
  const { data: person, loading: personLoading, error } = usePerson(personId || '');
  const { data: recovery, loading: recoveryLoading } = usePersonRecoverySummary(personId || '');

  if (personLoading || !person) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="space-y-6"
      >
        <Shimmer className="h-12 w-64 rounded" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Shimmer key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Shimmer className="h-96 w-full rounded-xl" />
      </motion.div>
    );
  }

  if (error && !person) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center py-12"
      >
        <p className="text-error">Error loading person: {error}</p>
      </motion.div>
    );
  }

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
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            icon={<ArrowLeft size={14} />}
            onClick={() => navigate(-1)}
          />
          <div>
            <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
              {person.name}
            </h1>
            <p className="mt-1 text-sm text-tertiary">
              {person.email} • Customer ID: {person.person_id.slice(0, 12)}...
            </p>
          </div>
        </div>
      </motion.div>

      {/* ── Recovery Summary ── */}
      <RecoverySummary summary={recovery} loading={recoveryLoading} />

      {/* ── Profile & Details ── */}
      <motion.div
        className="grid gap-6 lg:grid-cols-3"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {/* Profile Card */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle icon={<User size={14} />}>Profile</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-chartreuse-bg text-chartreuse">
              <User size={24} />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Full Name
              </p>
              <p className="mt-1 text-sm font-medium text-primary">{person.name}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Email
              </p>
              <p className="mt-1 text-sm text-secondary">{person.email}</p>
            </div>
            {person.phone && (
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  Phone
                </p>
                <p className="mt-1 text-sm text-secondary">{person.phone}</p>
              </div>
            )}
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Employment
              </p>
              <Badge variant="outline" size="sm">
                {person.employment_status.replace(/_/g, ' ')}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* Details Card */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle icon={<Shield size={14} />}>Risk & Account Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  Risk Tier
                </p>
                <div className="mt-1 flex items-center gap-2">
                  <StatusDot
                    variant={
                      person.risk_tier === 'low'
                        ? 'success'
                        : person.risk_tier === 'medium'
                          ? 'warning'
                          : 'error'
                    }
                  />
                  <span className="text-sm font-medium text-primary">
                    {person.risk_tier.toUpperCase()}
                  </span>
                </div>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  Settlement Account
                </p>
                <p className="mt-1 font-mono text-sm text-primary">
                  {person.settlement_account_id.slice(0, 16)}...
                </p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  Member Since
                </p>
                <p className="mt-1 text-sm text-secondary">
                  {formatDateTime(person.created_at)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  Tags
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {person.tags?.map((tag) => (
                    <Badge key={tag} variant="outline" size="sm">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* ── Recovery Details ── */}
      {recovery && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <Card>
            <CardHeader>
              <CardTitle icon={<BarChart3 size={14} />}>Recovery Performance</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    Total Failed
                  </p>
                  <p className="mt-1 text-2xl font-bold text-primary">
                    {recovery.total_failed}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    Recovered
                  </p>
                  <p className="mt-1 text-2xl font-bold text-success">
                    {recovery.total_recovered}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    Value Recovered
                  </p>
                  <div className="mt-1">
                    <CurrencyValue amount={recovery.total_value_recovered} size="md" />
                  </div>
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    Recovery Rate
                  </p>
                  <div className="mt-1">
                    <PercentValue value={recovery.recovery_rate} size="md" />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </motion.div>
  );
}

function RecoverySummary({
  summary,
  loading,
}: {
  summary: PersonRecoverySummary | null;
  loading: boolean;
}) {
  if (loading || !summary) {
    return (
      <motion.div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {Array.from({ length: 3 }).map((_, i) => (
          <Shimmer key={i} className="h-20 rounded-xl" />
        ))}
      </motion.div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
    >
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-tertiary">
              <Banknote size={20} />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Value At Risk
              </p>
              <div className="mt-1">
                <CurrencyValue amount={summary.total_value_failed} size="lg" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-success-bg text-success">
              <CheckCircle size={20} />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Value Recovered
              </p>
              <div className="mt-1">
                <CurrencyValue amount={summary.total_value_recovered} size="lg" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-tertiary">
              <Clock size={20} />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                Avg. Recovery Time
              </p>
              <div className="mt-1 text-xl font-bold text-primary">
                {summary.avg_recovery_time_hours
                  ? formatDuration(summary.avg_recovery_time_hours)
                  : '—'}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
