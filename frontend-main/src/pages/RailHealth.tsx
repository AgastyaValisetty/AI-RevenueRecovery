import { motion } from 'framer-motion';
import {
  Activity,
  Wifi,
  Signal,
  RefreshCw,
  BarChart3,
  Clock,
} from 'lucide-react';
import { useRailHealth } from '../hooks/useApi';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { StatusDot, type StatusVariant } from '../components/ui/StatusDot';
import { Shimmer } from '../components/ui/Shimmer';
import { formatNumber } from '../lib/utils';
import type { RailHealth } from '../lib/types';

export default function RailHealthPage() {
  const { data: rails, loading, refetch: _refetch } = useRailHealth();

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
            Rail Health
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Payment rail uptime, latency, and failure rates.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </motion.div>

      {/* ── Summary ── */}
      <SummarySection rails={rails || []} loading={loading} />

      {/* ── Rail Grid ── */}
      <RailGridSection rails={rails || []} loading={loading} />
    </motion.div>
  );
}

function SummarySection({
  rails,
  loading,
}: {
  rails: RailHealth[];
  loading: boolean;
}) {
  const operationalRails = rails.filter((r) => r.status === 'operational').length;
  const degradedRails = rails.filter((r) => r.status === 'degraded').length;
  const outageRails = rails.filter((r) => r.status === 'outage').length;
  const avgLatency = rails.length > 0 ? rails.reduce((sum, r) => sum + r.latency_ms, 0) / rails.length : 0;

  const cards = [
    {
      title: 'Operational Rails',
      value: <span className="font-mono text-2xl font-bold text-success">{operationalRails}</span>,
      icon: <Activity size={20} />,
    },
    {
      title: 'Degraded',
      value: <span className="font-mono text-2xl font-bold text-warning">{degradedRails}</span>,
      icon: <Signal size={20} />,
    },
    {
      title: 'Outages',
      value: <span className="font-mono text-2xl font-bold text-error">{outageRails}</span>,
      icon: <Wifi size={20} />,
    },
    {
      title: 'Avg Latency',
      value: <span className="font-mono text-2xl font-bold text-primary">{Math.round(avgLatency)}ms</span>,
      icon: <Clock size={20} />,
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
        <Card key={card.title} hover>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  {card.title}
                </p>
                <p className="mt-1 font-mono text-xl font-bold">{card.value}</p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-tertiary">
                {card.icon}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </motion.div>
  );
}

function RailGridSection({
  rails,
  loading,
}: {
  rails: RailHealth[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
          Payment Rails
        </h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Shimmer key={i} className="h-32 rounded-xl" />
          ))}
        </div>
      </motion.div>
    );
  }

  if (!rails || rails.length === 0) {
    return (
      <motion.div
        className="rounded-xl border border-border-subtle bg-panel p-8 text-center"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <Wifi className="mx-auto mb-3 h-6 w-6 text-tertiary opacity-40" />
        <p className="text-sm text-tertiary">No rail health data available.</p>
      </motion.div>
    );
  }

  const statusVariantMap: Record<string, StatusVariant> = {
    operational: 'success',
    degraded: 'warning',
    outage: 'error',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
    >
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-tertiary">
        Payment Rails
      </h2>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rails.map((rail) => (
          <motion.div
            key={rail.rail_name}
            whileHover={{ y: -2 }}
            transition={{ duration: 0.25 }}
          >
            <Card hover>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{rail.rail_name}</CardTitle>
                  <StatusDot
                    variant={statusVariantMap[rail.status] || 'default'}
                    pulse={rail.status === 'outage'}
                  />
                </div>
              </CardHeader>

              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <RailStat
                    icon={<Activity size={14} />}
                    label="Uptime 24h"
                    value={`${rail.uptime_24h.toFixed(2)}%`}
                  />
                  <RailStat
                    icon={<Clock size={14} />}
                    label="Latency"
                    value={`${rail.latency_ms}ms`}
                  />
                  <RailStat
                    icon={<BarChart3 size={14} />}
                    label="Success Rate"
                    value={`${(rail.success_rate * 100).toFixed(1)}%`}
                  />
                  <RailStat
                    icon={<RefreshCw size={14} />}
                    label="Failures 24h"
                    value={formatNumber(rail.failure_count_24h)}
                  />
                </div>

                <div className="rounded-lg bg-elevated/30 p-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-tertiary">
                      Type: {rail.rail_type}
                    </span>
                    <Badge variant={(statusVariantMap[rail.status] || 'default') as 'success' | 'warning' | 'error' | 'info' | 'default'} size="sm">
                      {rail.status}
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

function RailStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-tertiary">{icon}</span>
      <div>
        <p className="text-xs text-tertiary">{label}</p>
        <p className="font-mono text-sm text-primary">{value}</p>
      </div>
    </div>
  );
}
