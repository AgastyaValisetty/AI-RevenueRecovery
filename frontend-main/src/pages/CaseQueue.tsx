import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Clock,
  PauseCircle,
  TrendingUp,
  BarChart3,
} from 'lucide-react';
import { useSmartCases } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, PercentValue, CountValue, StatusBadge, MetricCard } from '../components/shared/MetricCard';
import { formatCurrency, formatDateTime } from '../lib/utils';
import type { SmartCase } from '../lib/types';

const statusFilters = [
  { value: 'all', label: 'All Cases' },
  { value: 'QUEUED', label: 'Queued' },
  { value: 'IN_PROGRESS', label: 'In Progress' },
  { value: 'RECOVERED', label: 'Recovered' },
  { value: 'STOPPED', label: 'Stopped' },
];

export default function CaseQueue() {
  const navigate = useNavigate();
  const { data: casesData, loading, error, refetch } = useSmartCases({
    limit: 50,
    sort: '-scheduled_for',
  });

  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const filteredCases = useMemo(() => {
    if (!casesData?.items) return [];

    return casesData.items.filter((caseItem) => {
      const matchesSearch =
        caseItem.case_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        caseItem.intent_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        caseItem.failure_code?.toLowerCase().includes(searchTerm.toLowerCase());

      const matchesStatus = statusFilter === 'all' || caseItem.status === statusFilter;

      return matchesSearch && matchesStatus;
    });
  }, [casesData?.items, searchTerm, statusFilter]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-6"
    >
      {/* ── Header ── */}
      <HeaderSection
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
        totalCases={filteredCases.length}
      />

      {/* ── Summary Cards ── */}
      <SummaryCards cases={filteredCases} loading={loading} />

      {/* ── Case Table ── */}
      <CaseTableSection
        cases={filteredCases}
        loading={loading}
        error={error}
        onRowClick={(caseItem) => navigate(`/cases/${caseItem.case_id}`)}
        onRefetch={refetch}
      />
    </motion.div>
  );
}

// ─── Header ───────────────────────────────────────

function HeaderSection({
  searchTerm,
  onSearchChange,
  statusFilter,
  onStatusChange,
  totalCases,
}: {
  searchTerm: string;
  onSearchChange: (val: string) => void;
  statusFilter: string;
  onStatusChange: (val: string) => void;
  totalCases: number;
}) {
  return (
    <motion.div
      className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div>
        <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
          Dispatch Board
        </h1>
        <p className="mt-1 text-sm text-tertiary">
          {totalCases} active cases under SARA management
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
          <input
            type="text"
            placeholder="Search cases..."
            value={searchTerm}
            onChange={(e) => onSearchChange(e.target.value)}
            className="rounded-lg border border-border-subtle bg-elevated px-4 py-2 pl-10 text-sm text-primary placeholder-tertiary focus:border-chartreuse focus:outline-none focus:ring-1 focus:ring-chartreuse"
          />
        </div>

        <select
          value={statusFilter}
          onChange={(e) => onStatusChange(e.target.value)}
          className="rounded-lg border border-border-subtle bg-elevated px-3 py-2 text-sm text-primary focus:border-chartreuse focus:outline-none focus:ring-1 focus:ring-chartreuse"
        >
          {statusFilters.map((filter) => (
            <option key={filter.value} value={filter.value}>
              {filter.label}
            </option>
          ))}
        </select>

        <Button variant="secondary" size="sm" icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </div>
    </motion.div>
  );
}

// ─── Summary Cards ─────────────────────────────────

function SummaryCards({
  cases,
  loading,
}: {
  cases: SmartCase[];
  loading: boolean;
}) {
  const stats = useMemo(() => {
    const total = cases.length;
    const queued = cases.filter((c) => c.status === 'QUEUED').length;
    const inProgress = cases.filter((c) => c.status === 'IN_PROGRESS').length;
    const recovered = cases.filter((c) => c.status === 'RECOVERED').length;
    const stopped = cases.filter((c) => c.status === 'STOPPED').length;
    const recoveredValue = cases
      .filter((c) => c.status === 'RECOVERED')
      .reduce((sum, c) => sum + parseFloat(c.amount), 0);
    const avgRecoveryRate =
      total > 0 ? (cases.filter((c) => c.status === 'RECOVERED').length / total) * 100 : 0;

    return { total, queued, inProgress, recovered, stopped, recoveredValue, avgRecoveryRate };
  }, [cases]);

  const cards = [
    {
      title: 'Total Cases',
      value: <CountValue value={stats.total} size="xl" />,
      icon: <BarChart3 size={20} />,
      color: 'default' as const,
    },
    {
      title: 'Queued',
      value: <CountValue value={stats.queued} size="xl" color="text-warning" />,
      icon: <Clock size={20} />,
      color: 'warning' as const,
    },
    {
      title: 'In Progress',
      value: <CountValue value={stats.inProgress} size="xl" color="text-info" />,
      icon: <AlertCircle size={20} />,
      color: 'default' as const,
    },
    {
      title: 'Recovered',
      value: <CurrencyValue amount={stats.recoveredValue} size="xl" />,
      icon: <CheckCircle size={20} />,
      color: 'chartreuse' as const,
    },
    {
      title: 'Stopped',
      value: <CountValue value={stats.stopped} size="xl" color="text-tertiary" />,
      icon: <PauseCircle size={20} />,
      color: 'default' as const,
    },
    {
      title: 'Avg Recovery Rate',
      value: <PercentValue value={stats.avgRecoveryRate} delta />,
      icon: <TrendingUp size={20} />,
      color: 'money' as const,
    },
  ];

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Shimmer key={i} className="h-24 rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, duration: 0.4 }}
    >
      {cards.map((card) => (
        <MetricCard
          key={card.title}
          title={card.title}
          value={card.value}
          icon={card.icon}
          variant={card.color}
        />
      ))}
    </motion.div>
  );
}

// ─── Case Table ───────────────────────────────────

function CaseTableSection({
  cases,
  loading,
  error,
  onRowClick,
  onRefetch,
}: {
  cases: SmartCase[];
  loading: boolean;
  error: string | null;
  onRowClick: (caseItem: SmartCase) => void;
  onRefetch: () => void;
}) {
  const columns = [
    {
      key: 'case_id',
      header: 'Case ID',
      sortable: true,
      render: (row: SmartCase) => (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-1.5 rounded-full bg-chartreuse" />
          <span className="font-mono text-xs text-primary">{row.case_id?.slice(0, 8)}</span>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      render: (row: SmartCase) => <StatusBadge status={row.status} size="sm" />,
    },
    {
      key: 'failure_code',
      header: 'Failure',
      sortable: true,
      render: (row: SmartCase) => {
        const colorMap: Record<string, string> = {
          insufficient_funds: 'text-blue-400',
          expired_card: 'text-purple-400',
          incorrect_cvc: 'text-orange-400',
          processing_error: 'text-error',
          declined: 'text-warning',
        };
        const color = colorMap[row.failure_code || ''] || 'text-tertiary';
        return (
          <span className={`text-xs font-mono ${color}`}>
            {row.failure_code || '—'}
          </span>
        );
      },
    },
    {
      key: 'amount',
      header: 'Amount',
      sortable: true,
      render: (row: SmartCase) => (
        <span className="font-mono text-sm text-money">
          {formatCurrency(parseFloat(row.amount))}
        </span>
      ),
    },
    {
      key: 'payment_method',
      header: 'Method',
      render: (row: SmartCase) => (
        <span className="text-xs text-tertiary">{row.payment_method}</span>
      ),
    },
    {
      key: 'retry_number',
      header: 'Retry #',
      render: (row: SmartCase) => (
        <span className="font-mono text-xs text-tertiary">#{row.retry_number}</span>
      ),
    },
    {
      key: 'scheduled_for',
      header: 'Scheduled',
      render: (row: SmartCase) => (
        <span className="text-xs text-tertiary">
          {row.scheduled_for ? formatDateTime(row.scheduled_for) : '—'}
        </span>
      ),
    },
    {
      key: 'expected_recovery',
      header: 'Expected',
      render: (row: SmartCase) => (
        <span className="font-mono text-xs text-tertiary">
          {(row.expected_recovery * 100).toFixed(0)}%
        </span>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Smart Cases</CardTitle>
          {error && (
            <button
              type="button"
              onClick={onRefetch}
              className="flex items-center gap-1.5 text-xs text-tertiary hover:text-primary"
            >
              <RefreshCw size={12} />
              Retry
            </button>
          )}
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <DataTable
          columns={columns as any}
          data={cases}
          loading={loading}
          pagination={true}
          pageSize={20}
          onRowClick={onRowClick}
          emptyMessage="No cases match your filters"
        />
      </CardContent>
    </Card>
  );
}
