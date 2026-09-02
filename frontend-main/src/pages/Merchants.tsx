import { motion } from 'framer-motion';
import { useMemo } from 'react';
import {
  Store,
  RefreshCw,
  TrendingUp,
  DollarSign,
  BarChart3,
} from 'lucide-react';
import { useMerchants } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, PercentValue, CountValue } from '../components/shared/MetricCard';
import { formatCurrencyCompact } from '../lib/utils';
import type { Merchant } from '../lib/types';

export default function Merchants() {
  const { data: merchantsData, loading, refetch: _refetch } = useMerchants({ limit: 50 });
  const merchants = merchantsData?.items || [];

  const summaryStats = useMemo(() => {
    const total = merchants.length;
    const active = merchants.filter((m) => m.status === 'active').length;
    const totalVolume = merchants.reduce((sum, m) => sum + m.total_volume, 0);
    const totalFailed = merchants.reduce((sum, m) => sum + m.total_failed, 0);
    const totalRecovered = merchants.reduce((sum, m) => sum + m.total_recovered, 0);
    const avgFailedRate = total > 0 ? (totalFailed / totalVolume) * 100 : 0;
    const avgRecoveryRate = totalFailed > 0 ? (totalRecovered / totalFailed) * 100 : 0;

    return {
      total,
      active,
      totalVolume,
      totalFailed,
      totalRecovered,
      avgFailedRate,
      avgRecoveryRate,
    };
  }, [merchants]);

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
            Merchants
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Merchant performance and recovery analytics.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </motion.div>

      {/* ── Summary ── */}
      <SummaryStats stats={summaryStats} loading={loading} />

      {/* ── Table ── */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Store size={14} />}>
            Merchant Directory ({merchants.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            columns={[
              {
                key: 'name',
                header: 'Name',
                sortable: true,
                render: (row: Merchant) => (
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-chartreuse-bg text-chartreuse">
                      <Store size={14} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-primary">{row.name}</p>
                      <p className="text-xs text-tertiary">{row.category}</p>
                    </div>
                  </div>
                ),
              },
              {
                key: 'status',
                header: 'Status',
                sortable: true,
                render: (row: Merchant) => (
                  <Badge variant={statusVariant(row.status)} size="sm">
                    {row.status}
                  </Badge>
                ),
              },
              {
                key: 'total_volume',
                header: 'Gross Volume',
                sortable: true,
                render: (row: Merchant) => (
                  <span className="font-mono text-sm text-money">
                    {formatCurrencyCompact(row.total_volume)}
                  </span>
                ),
              },
              {
                key: 'failed_rate',
                header: 'Failure Rate',
                sortable: true,
                render: (row: Merchant) => (
                  <div className="flex items-center gap-2">
                    <div className="w-12">
                      <div className="h-1.5 rounded-full bg-border-subtle">
                        <div
                          className="h-1.5 rounded-full bg-chartreuse"
                          style={{ width: `${Math.min(row.failed_rate * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                    <span className="font-mono text-xs text-tertiary">
                      {(row.failed_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                ),
              },
              {
                key: 'total_recovered',
                header: 'Recovered',
                sortable: true,
                render: (row: Merchant) => (
                  <span className="font-mono text-sm text-success">
                    {formatCurrencyCompact(row.total_recovered)}
                  </span>
                ),
              },
            ]}
            data={merchants}
            loading={loading}
            pagination={true}
            pageSize={20}
            emptyMessage="No merchants found"
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}

function statusVariant(status: string): 'success' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'active': return 'success';
    case 'suspended': return 'warning';
    case 'closed': return 'error';
    default: return 'default';
  }
}

function SummaryStats({
  stats,
  loading,
}: {
  stats: {
    total: number;
    active: number;
    totalVolume: number;
    totalFailed: number;
    totalRecovered: number;
    avgFailedRate: number;
    avgRecoveryRate: number;
  };
  loading: boolean;
}) {
  const cards = [
    {
      title: 'Total Merchants',
      value: <CountValue value={stats.total} size="lg" />,
      icon: <Store size={20} />,
    },
    {
      title: 'Active Merchants',
      value: <CountValue value={stats.active} size="lg" />,
      icon: <TrendingUp size={20} />,
    },
    {
      title: 'Gross Volume',
      value: <CurrencyValue amount={stats.totalVolume} size="lg" />,
      icon: <DollarSign size={20} />,
    },
    {
      title: 'Recovery Rate',
      value: <PercentValue value={stats.avgRecoveryRate / 100} delta />,
      icon: <BarChart3 size={20} />,
    },
  ];

  if (loading) {
    return (
      <motion.div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {Array.from({ length: 4 }).map((_, i) => (
          <Shimmer key={i} className="h-20 rounded-xl" />
        ))}
      </motion.div>
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
                  <div className="mt-1">{card.value}</div>
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-tertiary">
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
