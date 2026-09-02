import { motion } from 'framer-motion';
import {
  AlertCircle,
  BarChart3,
  PieChart,
  RefreshCw,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Bar,
  Pie,
  Cell,
  Legend,
} from 'recharts';
import { useFailureStats } from '../hooks/useApi';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { StatusDot } from '../components/ui/StatusDot';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, CountValue, PercentValue } from '../components/shared/MetricCard';
import { formatCurrencyCompact } from '../lib/utils';
import type { FailureSummary, FailureMethodBreakdown } from '../lib/types';

export default function Failures() {
  const { data: failureStats, loading, refetch: _refetch } = useFailureStats();

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
            Failure Analysis
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Payment failure breakdown by code and recovery method.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </motion.div>

      {/* ── Summary Cards ── */}
      <SummaryCards stats={failureStats} loading={loading} />

      {/* ── Charts ── */}
      <ChartsSection stats={failureStats} loading={loading} />

      {/* ── Method Breakdown ── */}
      <MethodBreakdownSection methods={failureStats?.by_method || []} loading={loading} />

      {/* ── Failure Table ── */}
      <FailureTableSection failures={failureStats?.by_code || []} loading={loading} />
    </motion.div>
  );
}

function SummaryCards({
  stats,
  loading,
}: {
  stats: ReturnType<typeof useFailureStats>['data'];
  loading: boolean;
}) {
  const cards = [
    {
      title: 'Total Failures',
      value: stats ? <CountValue value={stats.total_failures} /> : null,
      icon: <AlertCircle size={20} />,
      color: 'error' as const,
    },
    {
      title: 'Failed Value',
      value: stats ? <CurrencyValue amount={stats.total_amount} /> : null,
      icon: <BarChart3 size={20} />,
      color: 'money' as const,
    },
    {
      title: 'Recovery Rate',
      value: stats ? <PercentValue value={stats.recovery_rate} /> : null,
      icon: <PieChart size={20} />,
      color: 'chartreuse' as const,
    },
    {
      title: 'Avg Retries/Case',
      value: stats ? <CountValue value={stats.avg_retries} /> : null,
      icon: <RefreshCw size={20} />,
      color: 'default' as const,
    },
  ];

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Shimmer key={i} className="h-24 rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
    >
      {cards.map((card) => (
        <motion.div key={card.title} whileHover={{ y: -2 }} transition={{ duration: 0.25 }}>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    {card.title}
                  </p>
                  <p className="mt-1 font-mono text-xl font-bold text-primary">
                    {card.value}
                  </p>
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-chartreuse">
                  {card.icon}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      ))}
    </motion.div>
  );
}

function ChartsSection({
  stats,
  loading,
}: {
  stats: ReturnType<typeof useFailureStats>['data'];
  loading: boolean;
}) {
  if (loading || !stats?.by_code) {
    return (
      <div className="grid gap-6 xl:grid-cols-2">
        <Shimmer className="h-64 w-full rounded-2xl" />
        <Shimmer className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  const failuresByCode = stats.by_code;

  return (
    <motion.div
      className="grid gap-6 xl:grid-cols-2"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
    >
      {/* Bar chart: failures by code */}
      <Card>
        <CardHeader>
          <CardTitle icon={<BarChart3 size={14} />}>Failures by Code</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={failuresByCode} layout="vertical" margin={{ top: 4, right: 12, left: 80, bottom: 0 }}>
                <CartesianGrid stroke="#2A3330" strokeWidth={1} opacity={0.5} horizontal={false} />
                <XAxis type="number" axisLine={false} tickLine={false} hide />
                <YAxis
                  dataKey="failure_code"
                  type="category"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: '#9CA3A0', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
                  width={70}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1A211F',
                    border: '1px solid #2A3330',
                    fontSize: '12px',
                  }}
                  formatter={(value: any, name: any) => [
                    Number(value ?? 0).toLocaleString(),
                    name,
                  ]}
                  labelClassName="text-xs"
                />
                <Bar
                  dataKey="count"
                  fill="rgba(239, 68, 68, 0.6)"
                  radius={[0, 0, 0, 4]}
                  barSize={12}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Pie chart: distribution */}
      <Card>
        <CardHeader>
          <CardTitle icon={<PieChart size={14} />}>Failure Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1A211F',
                    border: '1px solid #2A3330',
                    fontSize: '12px',
                  }}
                  formatter={(value: any, name: any) => [
                    formatCurrencyCompact(Number(value ?? 0)),
                    name,
                  ]}
                />
                <Pie
                  data={failuresByCode}
                  dataKey="total_amount"
                  nameKey="failure_code"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                  strokeWidth={0}
                >
                  {failuresByCode.map((_, i) => (
                    <Cell key={`cell-${i}`} fill={FAILURE_COLORS[i % FAILURE_COLORS.length]} />
                  ))}
                </Pie>
                <Legend
                  layout="horizontal"
                  verticalAlign="bottom"
                  align="center"
                  iconSize={8}
                  wrapperStyle={{ fontSize: '10px', fontFamily: 'JetBrains Mono, monospace' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

const FAILURE_COLORS = [
  '#EF4444', '#F59E0B', '#EC4899', '#8B5CF6',
  '#EC4899', '#F97316', '#06B6D4', '#84CC16',
];

function MethodBreakdownSection({
  methods,
  loading,
}: {
  methods: FailureMethodBreakdown[];
  loading: boolean;
}) {
  if (loading) {
    return <Shimmer className="h-48 w-full rounded-2xl" />;
  }

  if (!methods || methods.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recovery Method Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-tertiary">No method data available.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Recovery Method Breakdown
      </h2>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {methods.map((method) => (
          <motion.div
            key={method.method}
            className="rounded-xl border border-border-subtle bg-elevated p-4"
            whileHover={{ borderColor: 'var(--border-strong)' }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-primary">{method.method}</span>
              <StatusDot
                variant={method.success_rate > 0.5 ? 'success' : method.success_rate > 0.2 ? 'warning' : 'error'}
                size="sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <StatItem label="Attempted" value={method.attempted} />
              <StatItem label="Succeeded" value={method.succeeded} color="text-success" />
              <StatItem label="Failed" value={method.failed} color="text-error" />
              <StatItem label="Success Rate" value={`${(method.success_rate * 100).toFixed(1)}%`} />
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

function FailureTableSection({
  failures,
  loading,
}: {
  failures: FailureSummary[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Failure Code Details
        </h2>
        <Shimmer className="h-64 w-full rounded-2xl" />
      </motion.div>
    );
  }

  if (!failures || failures.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Failure Code Details
        </h2>
        <Card>
          <CardContent className="py-12 text-center text-tertiary">
            <BarChart3 className="mx-auto mb-3 h-6 w-6 opacity-40" />
            <p className="text-sm">No failure data available.</p>
          </CardContent>
        </Card>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Failure Code Details
      </h2>

      <div className="overflow-x-auto rounded-xl border border-border-subtle">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border-subtle bg-elevated/50">
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary">
                Failure Code
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary">
                Reason
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary">
                Count
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary">
                Total Amount
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary">
                Recovery Rate
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary">
                Avg Retries
              </th>
            </tr>
          </thead>
          <tbody>
            {failures.map((failure) => (
              <tr key={failure.failure_code} className="border-b border-border-subtle/30 last:border-0">
                <td className="px-4 py-3">
                  <Badge variant="outline" size="sm">
                    {failure.failure_code}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-tertiary">{failure.failure_reason || '—'}</td>
                <td className="px-4 py-3 text-right font-mono text-primary">{failure.count.toLocaleString()}</td>
                <td className="px-4 py-3 text-right font-mono text-money">
                  {formatCurrencyCompact(failure.total_amount)}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="font-mono text-chartreuse">
                    {(failure.recovery_rate * 100).toFixed(1)}%
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono text-tertiary">
                  {failure.avg_retries_per_case.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}

interface StatItemProps {
  label: string;
  value: string | number;
  color?: string;
}

function StatItem({ label, value, color = 'text-tertiary' }: StatItemProps) {
  return (
    <div>
      <p className="text-xs text-tertiary">{label}</p>
      <p className={`font-mono text-sm font-medium ${color}`}>{value}</p>
    </div>
  );
}
